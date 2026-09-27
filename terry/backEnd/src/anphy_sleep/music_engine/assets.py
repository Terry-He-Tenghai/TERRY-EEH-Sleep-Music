"""Offline, deterministic asset preparation; technical checks never approve music.

prepare writes a pending PCM WAV plus provenance. freeze requires a human review
bound to that exact WAV hash. Neither operation edits the playback catalog.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import soundfile as sf
import scipy
from scipy.signal import resample_poly


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def metrics(samples: np.ndarray, sample_rate: int) -> dict:
    if not samples.size or not np.isfinite(samples).all():
        raise ValueError("Audio must contain finite samples")
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))
    return {
        "sample_rate_hz": sample_rate, "channels": samples.shape[1],
        "frames": len(samples), "duration_s": len(samples) / sample_rate,
        "peak": peak, "rms": rms,
        "rms_dbfs": 20 * math.log10(rms) if rms else None,
        "peak_dbfs": 20 * math.log10(peak) if peak else None,
        "clipping_samples": int(np.count_nonzero(np.abs(samples) >= 1)),
        "max_adjacent_step": float(np.max(np.abs(np.diff(samples, axis=0)))) if len(samples) > 1 else 0.,
        "loop_boundary_step": float(np.max(np.abs(samples[-1] - samples[0]))),
    }


def _publish(destination: Path, files: dict[str, bytes]) -> None:
    # A new directory only: retries/concurrent runs cannot overwrite an artifact.
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        with (destination / name).open("xb") as handle:
            handle.write(data)


def _json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def prepare(source: Path, destination: Path, *, provenance: str,
            duration_s: float = 60., sample_rate: int = 48000,
            target_rms_dbfs: float = -24., peak_dbfs: float = -3.) -> dict:
    """Trim (never repeat/pad), resample, make stereo and RMS-normalize with peak cap.

    RMS dBFS is not integrated LUFS or a physical listening safety measurement.
    Endpoint metrics do not constitute a perceptually seamless loop check.
    """
    if not provenance.strip():
        raise ValueError("Source/provenance is required")
    if (not math.isfinite(duration_s) or not 1 <= duration_s <= 600
            or sample_rate not in (24000, 44100, 48000)
            or not math.isfinite(target_rms_dbfs) or not -60 <= target_rms_dbfs <= -12
            or not math.isfinite(peak_dbfs) or not -12 <= peak_dbfs <= -1):
        raise ValueError("Invalid preparation settings")
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 256_000_000:
        raise ValueError("Expected a regular audio file <=256 MB")
    raw = source.read_bytes()
    with sf.SoundFile(io.BytesIO(raw)) as audio:
        if audio.channels not in (1, 2) or not 8000 <= audio.samplerate <= 192000:
            raise ValueError("Only mono/stereo audio at 8–192 kHz is supported")
        if audio.frames < round(duration_s * audio.samplerate):
            raise ValueError("Source is shorter than requested duration; no automatic repetition")
        if audio.frames / audio.samplerate > 1200 or audio.frames * audio.channels > 60_000_000:
            raise ValueError("Source exceeds 20 minute / 60 million sample inspection limit")
        original_rate = audio.samplerate
        samples = audio.read(dtype="float64", always_2d=True)
    source_metrics = metrics(samples, original_rate)
    samples = samples[:round(duration_s * original_rate)]
    divisor = math.gcd(original_rate, sample_rate)
    samples = resample_poly(samples, sample_rate // divisor, original_rate // divisor, axis=0)
    samples = samples[:round(duration_s * sample_rate)]
    if samples.shape[1] == 1:
        samples = np.repeat(samples, 2, axis=1)
    rms = float(np.sqrt(np.mean(samples ** 2)))
    if rms < 1e-9:
        raise ValueError("Silent audio cannot be normalized")
    gain = min(10 ** (target_rms_dbfs / 20) / rms,
               10 ** (peak_dbfs / 20) / float(np.max(np.abs(samples))))
    samples *= gain
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    wav = buffer.getvalue()
    decoded, _ = sf.read(io.BytesIO(wav), always_2d=True)
    report = {"version": 1, "status": "pending", "source_name": source.name,
              "source_sha256": digest(raw), "source": provenance,
              "output_file": "base_music_v1.wav", "output_sha256": digest(wav),
              "software": {"numpy": np.__version__, "scipy": scipy.__version__,
                           "soundfile": sf.__version__, "libsndfile": sf.__libsndfile_version__},
              "settings": {"duration_s": duration_s, "sample_rate_hz": sample_rate,
                           "target_rms_dbfs": target_rms_dbfs, "peak_cap_dbfs": peak_dbfs,
                           "applied_gain": gain, "normalization": "RMS, not LUFS"},
              "source_metrics": source_metrics, "output_metrics": metrics(decoded, sample_rate),
              "limitations": "Requires full listening, loop audition and license verification; no clinical or SPL safety claim."}
    review = {"sha256": digest(wav), "status": "pending", "reviewed_by": "",
              "reviewed_at": None, "copyright_checked": False, "audio_checked": False,
              "loop_checked": False, "license": "", "notes": ""}
    _publish(destination, {"base_music_v1.wav": wav, "report.json": _json(report),
                           "review.json": _json(review), "source" + source.suffix.lower(): raw})
    return report


def freeze(prepared: Path, destination: Path) -> dict:
    """Copy only reviewed, hash-matching output to a new immutable-by-policy version."""
    names = ("base_music_v1.wav", "report.json", "review.json")
    if prepared.is_symlink() or any((prepared / name).is_symlink() for name in names):
        raise ValueError("Symlink artifacts are not accepted")
    wav = (prepared / names[0]).read_bytes()
    report = json.loads((prepared / names[1]).read_text())
    review = json.loads((prepared / names[2]).read_text())
    sha = digest(wav)
    if sha != report.get("output_sha256") or sha != review.get("sha256"):
        raise ValueError("Review/report hash does not match prepared WAV")
    if (review.get("status") != "approved"
            or not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip()
            or not isinstance(review.get("license"), str) or not review["license"].strip()
            or any(review.get(key) is not True for key in ("copyright_checked", "audio_checked", "loop_checked"))):
        raise ValueError("Complete human listening, loop and copyright review required")
    try:
        reviewed_at = date.fromisoformat(review["reviewed_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("A valid review date is required") from error
    if reviewed_at > date.today():
        raise ValueError("Review date cannot be in the future")
    decoded, rate = sf.read(io.BytesIO(wav), always_2d=True)
    if metrics(decoded, rate)["clipping_samples"]:
        raise ValueError("Clipped output cannot be frozen")
    frozen = {**report, "status": "frozen", "review": review}
    _publish(destination, {names[0]: wav, names[1]: _json(frozen), names[2]: _json(review)})
    return frozen
