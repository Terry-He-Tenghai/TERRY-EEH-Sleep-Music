"""Read-only selected-electrode EDF parity replay, no remote music requests."""
import argparse
import json
import math
import sys
from pathlib import Path

import mne
import numpy as np
import torch
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backEnd'))
from waveform_classifier import WaveformClassifier, frontal_training_code, training_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edf', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--windows', type=int, default=10)
    args = parser.parse_args()
    if args.windows < 1:
        parser.error('windows must be positive')
    base, code = training_code(), frontal_training_code()
    header = base.header_info(args.edf)
    selected = code.channel_selection(header, 6)
    raw = mne.io.read_raw_edf(args.edf, include=selected, preload=False, verbose='ERROR')
    raw.reorder_channels(selected)
    rate = int(raw.info['sfreq'])
    models = {count: WaveformClassifier(base.CAP16, 250, count) for count in code.MONTAGES}
    maximum, accepted, rejected = {c: 0. for c in models}, {c: 0 for c in models}, {c: 0 for c in models}
    checked = 0
    try:
        for stage, start, duration in base.read_labels(args.labels):
            if stage not in base.STAGES or start < 10 or start + duration > raw.n_times / rate:
                continue
            data = raw.get_data(start=int((start - 10) * rate), stop=int((start + 30) * rate)) * 1e6
            for count, classifier in models.items():
                indices = [code.MONTAGES[6].index(name) for name in code.MONTAGES[count]]
                source = data[indices]
                offline, reason = code.preprocess_window(source, rate, count)
                factor = math.gcd(rate, 250)
                capture = np.full((16, 10000), np.nan)
                capture[[base.CAP16.index(name) for name in code.MONTAGES[count]]] = resample_poly(source, 250 // factor, rate // factor, axis=-1)
                classifier.reset()
                result = classifier.update(capture, start + 30)
                if reason:
                    assert result['status'] == 'invalid', 'QC parity mismatch'
                    rejected[count] += 1
                    continue
                assert result['status'] == 'ready'
                with torch.inference_mode():
                    expected = torch.softmax(classifier.model(torch.from_numpy(code.model_input(offline, count)[None])), dim=1)[0].numpy()
                actual = np.array([result['probabilities'][name] for name in base.STAGES])
                maximum[count] = max(maximum[count], float(np.max(np.abs(actual - expected))))
                np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)
                accepted[count] += 1
            checked += 1
            if checked >= args.windows:
                break
    finally:
        raw.close()
    if not all(accepted.values()):
        raise RuntimeError('No valid parity window for at least one model')
    print(json.dumps({'accepted': accepted, 'rejected': rejected, 'maximum_probability_difference': maximum,
                      'scope': 'EDF parity only, not hardware validation'}, indent=2))


if __name__ == '__main__':
    main()
