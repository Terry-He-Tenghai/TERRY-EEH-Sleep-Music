import shutil
from pathlib import Path

import numpy as np
import yaml

from anphy_sleep.config import load_config
from anphy_sleep.device_bridge import (
    HARDWARE_CHANNEL_NAMES,
    LiveSleepOnsetMonitor,
    adc_to_uv,
    open_live_sleep_monitor,
)
from anphy_sleep.music import NoOpMusicController
from anphy_sleep.music_runtime import AdaptiveMusicRuntime
from anphy_sleep.streaming import RealtimeSession

from test_streaming import _model_bundles


def _hardware_config_with_models(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "config.hardware.yaml"
    prediction_path, state_path = _model_bundles(tmp_path)
    model_dir = tmp_path / "models"
    model_dir.mkdir(exist_ok=True)
    shutil.copy(prediction_path, model_dir / "future_n2_logistic_continuous.joblib")
    shutil.copy(state_path, model_dir / "sleep_state_logistic_30s.joblib")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["data"]["results_dir"] = str(tmp_path)
    raw["music"]["enabled"] = True
    raw["music"]["player_backend"] = "null"
    raw["music"]["cache_file"] = str(tmp_path / "music" / "cache.json")
    config_path = tmp_path / "config.hardware.yaml"
    config_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def test_adc_to_uv_is_finite_and_scaled() -> None:
    zero = adc_to_uv(0)
    positive = adc_to_uv(1000)
    negative = adc_to_uv(-1000)
    assert zero == 0.0
    assert positive > 0
    assert negative < 0
    assert np.isfinite([zero, positive, negative]).all()


def test_live_monitor_emits_windows_from_cap_frames(tmp_path: Path) -> None:
    config, _ = load_config(Path(__file__).parents[1] / "config.hardware.yaml")
    prediction_path, state_path = _model_bundles(tmp_path)
    session = RealtimeSession(
        config,
        prediction_path,
        state_path,
        session_id="live-cap",
    )
    log_path = tmp_path / "sleep_onset.jsonl"
    monitor = LiveSleepOnsetMonitor(session, log_path=log_path, chunk_samples=25)
    rng = np.random.default_rng(0)
    outputs = []
    for _ in range(250 * 8):
        frame = rng.integers(-2000, 2000, size=16).tolist()
        outputs.extend(monitor.push_adc_frame(frame))
    monitor.close()

    assert session.signal.target_channels == HARDWARE_CHANNEL_NAMES
    assert len(outputs) >= 1
    assert outputs[0].state.window_end_s == 6.0
    assert log_path.is_file()
    assert log_path.read_text(encoding="utf-8").strip()


def test_open_live_monitor_requires_trained_models(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config.hardware.yaml"
    missing_config = tmp_path / "config.hardware.yaml"
    text = source.read_text(encoding="utf-8").replace(
        "results_dir: results/hardware",
        f"results_dir: {tmp_path / 'empty'}",
    )
    missing_config.write_text(text, encoding="utf-8")
    try:
        open_live_sleep_monitor(missing_config)
    except FileNotFoundError:
        return
    raise AssertionError("missing model files should raise FileNotFoundError")


def test_open_live_monitor_wires_music_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SUNO_API_KEY", "test-key")
    config_path = _hardware_config_with_models(tmp_path)
    monitor = open_live_sleep_monitor(config_path, enable_music=True)
    try:
        assert isinstance(monitor.music_runtime, AdaptiveMusicRuntime)
        assert isinstance(monitor.session.music_controller, AdaptiveMusicRuntime)
        assert monitor.music_runtime is monitor.session.music_controller
        assert "音乐未开启" not in monitor.hud_text()
    finally:
        monitor.close()
    assert monitor.music_runtime is None


def test_open_live_monitor_can_disable_music(tmp_path: Path) -> None:
    config_path = _hardware_config_with_models(tmp_path)
    monitor = open_live_sleep_monitor(config_path, enable_music=False)
    try:
        assert monitor.music_runtime is None
        assert isinstance(monitor.session.music_controller, NoOpMusicController)
    finally:
        monitor.close()
