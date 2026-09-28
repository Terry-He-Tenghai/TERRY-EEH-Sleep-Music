"""Optional YASA EEG-only adapter. Failure never interrupts spectral feedback.

Source: https://yasa-sleep.org/generated/yasa.SleepStaging.html
Rolling latest-epoch prediction has truncated future context and is experimental.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import logging

import numpy as np
import yaml

_LOG = logging.getLogger(__name__)
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='yasa-staging')
STAGES = ('W', 'N1', 'N2', 'N3', 'REM')
# Music policy, not a remapping of clinical stage probabilities.
MUSIC = {'W': 'M1', 'N1': 'M2', 'N2': 'M3', 'N3': 'M3', 'REM': 'M2'}


def predict_yasa(samples_uv, rate, channel):
    import mne
    import yasa
    raw = mne.io.RawArray(samples_uv[None, :] * 1e-6,
                         mne.create_info([channel], rate, 'eeg'), verbose=False)
    # No extra filtering/normalization; YASA owns preprocessing/resampling.
    staging = yasa.SleepStaging(raw, eeg_name=channel)
    row = staging.predict().proba.iloc[-1].to_dict()
    probabilities = {key: float(row['WAKE' if key == 'W' and 'WAKE' in row else 'R' if key == 'REM' and 'R' in row else key]) for key in STAGES}
    values = np.array(list(probabilities.values()))
    if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1) or abs(values.sum() - 1) > .01:
        raise ValueError('Invalid YASA probabilities')
    stage = max(probabilities, key=probabilities.get)
    return {'probabilities': probabilities, 'stage': stage, 'music_target': MUSIC[stage]}


class PretrainedClassifier:
    def __init__(self, names, rate, config=None, predictor=predict_yasa, executor=None):
        self.names, self.rate = tuple(names), rate
        self.predictor, self.executor = predictor, executor or _POOL
        self.future = None
        self.buffer = np.empty(0)
        self.channel = None
        self.last_end = None
        self.last_submitted = -1e9
        self.result = None
        self.revision = 0
        self.error = None
        try:
            if config is None:
                config = yaml.safe_load(Path(__file__).with_name('config.pretrained.yaml').read_text(encoding='utf-8'))
            self.config = config
            if not isinstance(config, dict):
                raise ValueError('Invalid pretrained configuration')
            self.reason = ('disabled' if config.get('enabled') is not True else
                           'channel_map_unconfirmed' if config.get('channel_map_confirmed') is not True else
                           'reference_unconfirmed_or_unsupported' if config.get('reference') not in ('M1', 'M2', 'Fpz') else None)
        except Exception:
            self.config = {}
            self.reason = 'configuration_error'

    def reset(self):
        self.buffer = np.empty(0)
        self.channel = None
        self.result = None
        self.last_end = None
        self.last_submitted = -1e9
        self.revision += 1
        # A running job cannot be cancelled; its revision prevents reuse.
        if self.future is not None and self.future.cancel():
            self.future = None

    def update(self, window, end_s, clean_channels):
        base = {'model': 'YASA 0.7.0 EEG-only', 'experimental': True,
                'reference': self.config.get('reference', 'unknown'),
                'context': 'rolling_latest_epoch_unvalidated', 'probabilities': None}
        if self.reason:
            return {**base, 'status': 'fallback', 'reason': self.reason}
        reference = self.config['reference']
        allowed = ('C4',) if reference == 'M1' else ('C3',) if reference == 'M2' else ('C3', 'C4')
        candidates = [name for name in allowed if name in self.names and name in clean_channels]
        chosen = self.channel if self.channel in candidates else next(iter(candidates), None)
        contiguous = self.last_end is None or abs(end_s - self.last_end - window.shape[1] / self.rate) < .01
        if chosen is None or chosen != self.channel or not contiguous:
            self.reset()
        if chosen is None:
            return {**base, 'status': 'fallback', 'reason': 'matching_clean_central_channel_missing'}
        self.channel, self.last_end = chosen, end_s
        row = window[self.names.index(chosen)]
        if not np.isfinite(row).all():
            self.reset()
            return {**base, 'status': 'fallback', 'reason': 'matching_channel_missing_samples'}
        self.buffer = np.concatenate((self.buffer, row))[-int(600 * self.rate):]
        if self.future is not None and self.future.done():
            try:
                prediction = self.future.result()
                if self.job_revision == self.revision:
                    self.result = {**prediction, 'window_end_s': self.job_end, 'channel': chosen}
                    self.error = None
            except Exception:
                self.error = 'model_load_or_prediction_failed'
                _LOG.exception('YASA failed; keeping spectral feedback')
            self.future = None
        if self.buffer.size >= 300 * self.rate and self.future is None and end_s - self.last_submitted >= 30:
            # Align the buffer to completed 30-second epochs, no partial epoch.
            n = int(self.buffer.size // (30 * self.rate) * (30 * self.rate))
            self.job_end = end_s
            self.job_revision = self.revision
            self.last_submitted = end_s
            self.future = self.executor.submit(self.predictor, self.buffer[-n:].copy(), self.rate, chosen)
        if self.result and 0 <= end_s - self.result['window_end_s'] <= 36:
            return {**base, **self.result, 'status': 'ready', 'reason': 'rolling_prediction_unvalidated'}
        return {**base, 'status': 'fallback', 'channel': chosen,
                'collected_seconds': self.buffer.size / self.rate,
                'reason': self.error or ('warming_up_300_seconds' if self.buffer.size < 300 * self.rate else 'predicting')}
