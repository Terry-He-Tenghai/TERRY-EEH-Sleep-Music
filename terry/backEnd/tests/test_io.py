from pathlib import Path

import mne
import numpy as np

from anphy_sleep.io import (
    find_stable_n2_onset,
    read_sleep_annotations,
    select_target_channels,
)


def test_annotation_parsing_and_stable_n2(tmp_path: Path) -> None:
    annotation = tmp_path / "stages.txt"
    annotation.write_text(
        "W,0,30\nN1,30,30\nN2,60,30\nN2,90,30\nN1,120,30\n",
        encoding="utf-8",
    )
    stages = read_sleep_annotations(annotation)
    assert list(stages["stage"]) == ["W", "N1", "N2", "N2", "N1"]
    assert find_stable_n2_onset(stages, 60) == 60


def test_legacy_temporal_channel_aliases() -> None:
    channels = [
        "Fp1",
        "Fp2",
        "F3",
        "F4",
        "F7",
        "F8",
        "Fz",
        "C3",
        "C4",
        "Cz",
        "T3",
        "T4",
        "P3",
        "P4",
        "O1",
        "O2",
    ]
    raw = mne.io.RawArray(
        np.zeros((16, 1_000)),
        mne.create_info(channels, 250, "eeg"),
        verbose="ERROR",
    )
    selected, mapping = select_target_channels(
        raw,
        [*channels[:10], "T7", "T8", *channels[12:]],
        {"T7": "T3", "T8": "T4"},
    )
    assert selected.ch_names[10:12] == ["T7", "T8"]
    assert mapping["T7"] == "T3"
