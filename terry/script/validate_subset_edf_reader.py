"""Validate the production selected-signal EDF reader against MNE on real data."""
from pathlib import Path
import sys
import numpy as np
import mne
from train_sleep_subset_models import load_selected_edf

if __name__ == '__main__':
    edf = Path(sys.argv[1])
    x, rate, info, selected = load_selected_edf(edf, 6)
    raw = mne.io.read_raw_edf(edf, include=selected, preload=False, infer_types=False, verbose='ERROR')
    raw.reorder_channels(selected)
    for start in (10, 1800, 7200):
        actual = raw.get_data(start=start * rate, stop=(start + 40) * rate) * 1e6
        np.testing.assert_allclose(x[:, start * rate:(start + 40) * rate], actual, atol=1e-8, rtol=1e-10)
    print('Production EDF selected-channel calibration matches MNE at 10s, 1800s, 7200s:', x.shape, rate)
    raw.close()
