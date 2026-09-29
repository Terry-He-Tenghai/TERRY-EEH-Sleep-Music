"""Read-only EDF replay checking parity of training and live CNN preprocessing.

This validates numerical integration, not classification accuracy or headset/ACE
availability. No audio generation requests are made.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import mne
import numpy as np
import torch
from scipy.signal import resample_poly

BACKEND = Path(__file__).resolve().parents[1] / 'backEnd'
sys.path.insert(0, str(BACKEND))
from waveform_classifier import WaveformClassifier, training_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edf', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--windows', type=int, default=10)
    args = parser.parse_args()
    if args.windows < 1:
        parser.error('windows must be positive')
    code = training_code()
    labels = code.channel_selection(code.header_info(args.edf))
    raw = mne.io.read_raw_edf(args.edf, include=labels, preload=False, verbose='ERROR')
    raw.reorder_channels(labels)
    rate = int(raw.info['sfreq'])
    models = {count: WaveformClassifier(code.CAP16, 250, count) for count in (8, 16)}
    accepted = rejected = 0
    maximum_difference = 0.0
    try:
        for stage, start, duration in code.read_labels(args.labels):
            if stage not in code.STAGES or start < 10 or start + duration > raw.n_times / rate:
                continue
            data = raw.get_data(start=int((start - 10) * rate), stop=int((start + 30) * rate)) * 1e6
            factor = math.gcd(rate, 250)
            live_buffer = resample_poly(data, 250 // factor, rate // factor, axis=-1)
            offline, reason = code.preprocess_window(data, rate)
            for count, classifier in models.items():
                classifier.reset()
                result = classifier.update(live_buffer, start + 30)
                if reason:
                    if result['status'] != 'invalid':
                        raise AssertionError('QC differs between source and 250Hz replay')
                    continue
                if result['status'] != 'ready':
                    raise AssertionError('Valid offline window rejected in replay')
                with torch.inference_mode():
                    expected = torch.softmax(classifier.model(torch.from_numpy(code.model_input(offline, count)[None])), dim=1)[0].numpy()
                actual = np.array([result['probabilities'][name] for name in code.STAGES])
                difference = float(np.max(np.abs(actual - expected)))
                maximum_difference = max(maximum_difference, difference)
                np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)
            if reason:
                rejected += 1
            else:
                accepted += 1
            if accepted + rejected >= args.windows:
                break
    finally:
        raw.close()
    if accepted == 0:
        raise RuntimeError('No valid windows tested')
    print(json.dumps({'edf': str(args.edf), 'accepted_windows': accepted, 'rejected_windows': rejected,
                      'models': ['cap8', 'cap16'], 'maximum_probability_difference': maximum_difference,
                      'scope': 'offline/live numerical parity only; no device or ACE request'}, indent=2))


if __name__ == '__main__':
    main()
