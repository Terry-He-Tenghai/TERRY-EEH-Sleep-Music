from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt


@dataclass(frozen=True)
class WaveformParameters:
    """Safe, normalized controls for a local music render."""

    master_gain: float = 0.75
    brightness: float = 0.35
    reverb_send: float = 0.20
    stereo_width: float = 0.65
    fade_seconds: float = 8.0

    def validate(self) -> None:
        for name in ("master_gain", "brightness", "reverb_send", "stereo_width"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.fade_seconds < 0:
            raise ValueError("fade_seconds must be non-negative")


@dataclass(frozen=True)
class WaveformMetrics:
    rms: float
    peak: float
    clipped_samples: int
    spectral_centroid_hz: float
    high_frequency_ratio: float
    discontinuities: int


def _stereo(audio: np.ndarray) -> np.ndarray:
    values = np.asarray(audio, dtype=np.float64)
    if values.ndim == 1:
        values = np.vstack([values, values])
    if values.ndim != 2 or values.shape[0] != 2:
        raise ValueError("audio must have shape (samples,) or (2, samples)")
    return values


def _fade(audio: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 0 or audio.shape[1] == 0:
        return audio
    length = min(samples, audio.shape[1] // 2)
    if length == 0:
        return audio
    envelope = np.ones(audio.shape[1], dtype=np.float64)
    envelope[:length] = np.linspace(0.0, 1.0, length)
    envelope[-length:] *= np.linspace(1.0, 0.0, length)
    return audio * envelope


def _lowpass(audio: np.ndarray, sample_rate_hz: int, cutoff_hz: float) -> np.ndarray:
    if cutoff_hz >= sample_rate_hz / 2.0 - 1.0:
        return audio
    sos = butter(3, max(20.0, cutoff_hz), btype="lowpass", fs=sample_rate_hz, output="sos")
    return sosfilt(sos, audio, axis=1)


def _reverb(audio: np.ndarray, sample_rate_hz: int, send: float) -> np.ndarray:
    if send <= 0 or audio.shape[1] == 0:
        return audio
    result = audio.copy()
    for delay_seconds, amount in ((0.17, 0.28), (0.31, 0.18), (0.47, 0.10)):
        delay = max(1, int(round(delay_seconds * sample_rate_hz)))
        if delay >= audio.shape[1]:
            continue
        result[:, delay:] += audio[:, :-delay] * amount * send
    return result


def process_waveform(
    audio: np.ndarray,
    sample_rate_hz: int,
    parameters: WaveformParameters | None = None,
) -> tuple[np.ndarray, WaveformMetrics]:
    """Apply deterministic gain, brightness, reverb, width, fades, and limiting."""
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    params = parameters or WaveformParameters()
    params.validate()
    result = _stereo(audio)
    cutoff = 500.0 + 7_500.0 * params.brightness
    result = _lowpass(result, sample_rate_hz, cutoff)
    result = _reverb(result, sample_rate_hz, params.reverb_send)
    mid = (result[0] + result[1]) / 2.0
    side = (result[0] - result[1]) / 2.0 * params.stereo_width
    result = np.vstack([mid + side, mid - side])
    result *= params.master_gain
    result = _fade(result, int(round(params.fade_seconds * sample_rate_hz)))
    clipped_samples = int(np.count_nonzero(np.abs(result) > 1.0))
    result = np.tanh(result)
    metrics = waveform_metrics(result, sample_rate_hz, clipped_samples=clipped_samples)
    return np.asarray(result, dtype=np.float32), metrics


def waveform_metrics(
    audio: np.ndarray,
    sample_rate_hz: int,
    clipped_samples: int | None = None,
) -> WaveformMetrics:
    """Compute offline safety and change metrics for a mono or stereo buffer."""
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    values = _stereo(audio)
    mono = values.mean(axis=0)
    if mono.size == 0:
        return WaveformMetrics(0.0, 0.0, 0, 0.0, 0.0, 0)
    spectrum = np.abs(np.fft.rfft(mono))
    frequencies = np.fft.rfftfreq(mono.size, 1.0 / sample_rate_hz)
    total = float(spectrum.sum())
    centroid = float((spectrum * frequencies).sum() / total) if total else 0.0
    high = float(spectrum[frequencies >= 2_000.0].sum())
    discontinuities = int(np.count_nonzero(np.abs(np.diff(mono)) > 0.35))
    return WaveformMetrics(
        rms=float(np.sqrt(np.mean(mono**2))),
        peak=float(np.max(np.abs(values))),
        clipped_samples=int(clipped_samples or 0),
        spectral_centroid_hz=centroid,
        high_frequency_ratio=high / total if total else 0.0,
        discontinuities=discontinuities,
    )


def write_wav_file(audio: np.ndarray, path: str | Path, sample_rate_hz: int) -> Path:
    """Write a float buffer as a 16-bit PCM WAV file."""
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    values = np.asarray(np.clip(_stereo(audio).T, -1.0, 1.0) * 32767.0, dtype=np.int16)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(destination, sample_rate_hz, values)
    return destination


def crossfade(left: np.ndarray, right: np.ndarray, fade_samples: int) -> np.ndarray:
    """Join two buffers with a linear equal-power-ish crossfade."""
    first = _stereo(left)
    second = _stereo(right)
    if fade_samples <= 0:
        return np.hstack([first, second]).astype(np.float32)
    length = min(fade_samples, first.shape[1], second.shape[1])
    if length == 0:
        return np.hstack([first, second]).astype(np.float32)
    overlap = first[:, -length:] * np.linspace(1.0, 0.0, length)
    overlap += second[:, :length] * np.linspace(0.0, 1.0, length)
    return np.hstack([first[:, :-length], overlap, second[:, length:]]).astype(np.float32)
