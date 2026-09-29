import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import date

import numpy as np
import pytest
import soundfile as sf

from anphy_sleep.music_engine.assets import freeze, prepare


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "candidate.wav"
    sf.write(path, .1 * np.sin(2 * np.pi * 220 * np.arange(32000) / 16000), 16000)
    return path


def prepared(source, tmp_path):
    directory = tmp_path / "prepared"
    prepare(source, directory, provenance="Synthetic test, not approved music", duration_s=1)
    return directory


def approve(directory):
    path = directory / "review.json"
    review = json.loads(path.read_text())
    review.update(status="approved", reviewed_by="Test fixture only", reviewed_at=date.today().isoformat(),
                  audio_checked=True, copyright_checked=True, loop_checked=True, license="Synthetic test")
    path.write_text(json.dumps(review))


def test_prepare_deterministic_pending(source, tmp_path):
    first = prepare(source, tmp_path / "a", provenance="Synthetic test", duration_s=1)
    second = prepare(source, tmp_path / "b", provenance="Synthetic test", duration_s=1)
    assert first == second
    assert first["status"] == "pending"
    assert first["output_metrics"]["frames"] == 48000
    assert first["output_metrics"]["channels"] == 2
    assert first["output_metrics"]["clipping_samples"] == 0
    assert first["output_metrics"]["peak_dbfs"] <= -2.99
    assert first["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (tmp_path / "a/source.wav").read_bytes() == source.read_bytes()
    assert not json.loads((tmp_path / "a/review.json").read_text())["audio_checked"]


def test_freeze_requires_human_review(source, tmp_path):
    directory = prepared(source, tmp_path)
    with pytest.raises(ValueError, match="human"):
        freeze(directory, tmp_path / "frozen")
    assert not (tmp_path / "frozen").exists()
    approve(directory)
    result = freeze(directory, tmp_path / "frozen")
    assert result["status"] == "frozen"
    assert (tmp_path / "frozen/base_music_v1.wav").read_bytes() == (directory / "base_music_v1.wav").read_bytes()
    with pytest.raises(FileExistsError):
        freeze(directory, tmp_path / "frozen")


def test_modified_audio_rejected(source, tmp_path):
    directory = prepared(source, tmp_path)
    approve(directory)
    with (directory / "base_music_v1.wav").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="hash"):
        freeze(directory, tmp_path / "frozen")


@pytest.mark.parametrize("field,value", [("loop_checked", False), ("audio_checked", "true"),
                                         ("copyright_checked", False), ("license", ""), ("reviewed_by", None),
                                         ("reviewed_at", "invalid"), ("reviewed_at", "2999-01-01")])
def test_incomplete_review_rejected(source, tmp_path, field, value):
    directory = prepared(source, tmp_path)
    approve(directory)
    path = directory / "review.json"
    review = json.loads(path.read_text())
    review[field] = value
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError):
        freeze(directory, tmp_path / "frozen")


@pytest.mark.parametrize("kwargs", [{"duration_s": 3}, {"duration_s": float("nan")},
                                    {"sample_rate": 250}, {"target_rms_dbfs": 0},
                                    {"peak_dbfs": float("inf")}])
def test_invalid_settings(source, tmp_path, kwargs):
    with pytest.raises(ValueError):
        prepare(source, tmp_path / "out", provenance="Test", **kwargs)
    assert not (tmp_path / "out").exists()


def test_symlink_rejected(source, tmp_path, symlink_or_skip):
    link = tmp_path / "linked.wav"
    symlink_or_skip(link, source)
    with pytest.raises(ValueError, match="regular"):
        prepare(link, tmp_path / "out", provenance="Test", duration_s=1)
    directory = prepared(source, tmp_path)
    approve(directory)
    wav = directory / "base_music_v1.wav"
    wav.unlink()
    wav.symlink_to(source)
    with pytest.raises(ValueError, match="Symlink"):
        freeze(directory, tmp_path / "frozen")


def test_peak_cap_and_source_clipping(tmp_path):
    source = tmp_path / "loud.wav"
    samples = np.full(16000, .01)
    samples[8000] = 1.2
    sf.write(source, samples, 16000, subtype="FLOAT")
    report = prepare(source, tmp_path / "out", provenance="Synthetic impulse test", duration_s=1)
    assert report["source_metrics"]["clipping_samples"] == 1
    assert report["output_metrics"]["clipping_samples"] == 0
    assert report["output_metrics"]["peak_dbfs"] <= -2.99
    assert report["status"] == "pending"


def test_no_overwrite(source, tmp_path):
    directory = prepared(source, tmp_path)
    original = (directory / "base_music_v1.wav").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(source, directory, provenance="Test", duration_s=1)
    assert (directory / "base_music_v1.wav").read_bytes() == original


def test_cli_prepare_and_freeze(source, tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/prepare_music_asset.py"
    directory = tmp_path / "prepared-cli"
    result = subprocess.run([sys.executable, str(script), "prepare", str(source), str(directory),
                             "--provenance", "Synthetic CLI test", "--duration", "1"],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["status"] == "pending"
    approve(directory)
    result = subprocess.run([sys.executable, str(script), "freeze", str(directory), str(tmp_path / "frozen-cli")],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["status"] == "frozen"


def test_silence_rejected(tmp_path):
    source = tmp_path / "silent.wav"
    sf.write(source, np.zeros(16000), 16000)
    with pytest.raises(ValueError, match="Silent"):
        prepare(source, tmp_path / "out", provenance="Test", duration_s=1)
