import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
from pydantic import ValidationError

spec = importlib.util.spec_from_file_location('terry_web_app', Path(__file__).parents[1] / 'app.py')
web = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = web
spec.loader.exec_module(web)


@pytest.mark.parametrize('rate', [250, 500, 1000])
def test_demo_rate_and_packet_time(rate):
    service = web.AcquisitionService()
    service._sample_rate_hz = rate
    messages = []
    def capture(message):
        messages.append(message)
        service._stop_event.set()
    service._publish = capture
    service._run_demo()
    packet = messages[0]
    assert packet['sample_rate_hz'] == rate
    assert len(packet['samples_uv'][0]) == rate // 10
    service._publish_chunk(np.zeros((16, 10)), rate * 2)
    assert messages[-1]['timestamp_s'] == 2.0
    assert service.status().sample_rate_hz == rate


def test_invalid_sample_rate():
    with pytest.raises(ValidationError):
        web.StartRequest(sample_rate_hz=2000)


def test_full_cap_montage_and_hardware_channel_power():
    assert web.CAP_CHANNEL_NAMES == (
        'Fp1', 'Fp2', 'C3', 'C4', 'P7', 'P8', 'O1', 'O2',
        'F7', 'F8', 'F3', 'F4', 'T7', 'T8', 'P3', 'P4',
    )
    commands = web.AcquisitionService._channel_config(24)
    assert len(commands) == 16 * 9
    for index in range(16):
        assert commands[index * 9 + 2] == '0'
    service = web.AcquisitionService()
    service._channels = web.CAP_CHANNEL_NAMES
    from display_filter import DisplayFilter
    service._display_filter = DisplayFilter(250, len(service._channels))
    received = []
    service._publish = received.append
    service._publish_chunk(np.ones((16, 25)), 0)
    assert received[0]['channels'] == list(web.CAP_CHANNEL_NAMES)
    assert len(received[0]['samples_uv']) == 16


def test_sixteen_channel_display_denoises_each_channel_without_changing_raw_input():
    from display_filter import DisplayFilter

    rate = 250
    time = np.arange(rate * 4) / rate
    raw = np.vstack([
        20 * np.sin(2 * np.pi * 10 * time + channel) +
        160 * np.sin(2 * np.pi * 50 * time + channel / 4)
        for channel in range(16)
    ])
    service = web.AcquisitionService()
    service._channels = web.CAP_CHANNEL_NAMES
    service._display_filter = DisplayFilter(rate, 16)
    inference = []
    packets = []
    service._adaptive.submit = lambda chunk, *args, **kwargs: inference.append(chunk.copy())
    service._publish = packets.append
    for start in range(0, raw.shape[1], 125):
        service._publish_chunk(raw[:, start:start + 125], start)

    displayed = np.concatenate([np.asarray(packet['samples_uv']) for packet in packets], axis=1)
    assert all(packet['channels'] == list(web.CAP_CHANNEL_NAMES) for packet in packets)
    np.testing.assert_array_equal(np.concatenate(inference, axis=1), raw)
    assert displayed.shape == raw.shape
    for channel in range(16):
        assert np.std(displayed[channel, rate * 2:]) < np.std(raw[channel, rate * 2:]) / 3
        assert np.std(displayed[channel, rate * 2:]) > 5


def test_live_reduced_montage_blocks_legacy_classifier():
    from adaptive_web import AdaptiveWebService, _Session

    events = []
    adaptive = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', 250, web.CAP_CHANNEL_NAMES[:8])
    adaptive._session = ctx
    adaptive._process(ctx)
    assert events[-1]['status'] == 'blocked'
    assert events[-1]['reason'] == 'live_inference_requires_16_channels'
    assert events[-1]['probabilities'] is None


def test_live_cap_montage_does_not_masquerade_as_existing_model(monkeypatch):
    from adaptive_web import AdaptiveWebService, _Session

    monkeypatch.setenv('TERRY_EEG_EXPERIMENTAL_16CH_MAPPING', '0')
    monkeypatch.setenv('TERRY_EEG_CHANNEL_MAP_CONFIRMED', '1')
    events = []
    adaptive = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', 250, web.CAP_CHANNEL_NAMES)
    adaptive._session = ctx
    adaptive._process(ctx)
    assert events[-1]['status'] == 'blocked'
    assert events[-1]['reason'] == 'configured_channel_order_mismatch'
    assert events[-1]['probabilities'] is None


def test_experimental_mapping_reaches_model_baseline_with_verified_cap(monkeypatch):
    from adaptive_web import AdaptiveWebService, _Session

    monkeypatch.setenv('TERRY_EEG_EXPERIMENTAL_16CH_MAPPING', '1')
    monkeypatch.setenv('TERRY_EEG_CHANNEL_MAP_CONFIRMED', '1')
    events = []
    adaptive = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', 250, web.CAP_CHANNEL_NAMES)
    adaptive._session = ctx

    def publish(event):
        events.append(event)
        if event.get('reason') == 'collecting_baseline_and_state_windows':
            ctx.cancelled.set()

    adaptive._publish = publish
    adaptive._process(ctx)
    assert events[-1]['status'] == 'waiting'
    assert events[-1]['reason'] == 'collecting_baseline_and_state_windows'


def test_experimental_mapping_rejects_unconfirmed_cap(monkeypatch):
    from adaptive_web import AdaptiveWebService, _Session

    monkeypatch.setenv('TERRY_EEG_EXPERIMENTAL_16CH_MAPPING', '1')
    monkeypatch.setenv('TERRY_EEG_CHANNEL_MAP_CONFIRMED', '0')
    events = []
    adaptive = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', 250, web.CAP_CHANNEL_NAMES)
    adaptive._session = ctx
    adaptive._process(ctx)
    assert events[-1]['status'] == 'blocked'
    assert events[-1]['reason'].startswith('physical_channel_map_unconfirmed')


def test_live_sixteen_channel_model_mismatch_cannot_start_ace(monkeypatch):
    from adaptive_web import _Session

    monkeypatch.setenv('TERRY_EEG_EXPERIMENTAL_16CH_MAPPING', '0')
    monkeypatch.setenv('TERRY_EEG_CHANNEL_MAP_CONFIRMED', '1')
    service = web.AcquisitionService()
    service._channels = web.CAP_CHANNEL_NAMES
    service._adaptive_generation = 1
    ctx = _Session(1, 'LIVE', 250, web.CAP_CHANNEL_NAMES)
    service._adaptive._session = ctx
    service._adaptive._last = service._adaptive._empty_event(1, 'LIVE')
    web.ace_automatic.start(1, 'ambient')
    try:
        service._adaptive._process(ctx)
        assert service._adaptive.status()['reason'] == 'configured_channel_order_mismatch'
        assert web.ace_automatic.status()['status'] == 'paused'
        assert web.ace_automatic.status()['audio_url'] is None
    finally:
        web.ace_automatic.stop()


def test_brainflow_packet_keeps_all_cap_channels_in_order(monkeypatch):
    from brainflow import board_shim

    packet = np.zeros((32, 2))
    packet[:16] = np.arange(1, 17)[:, None]
    packet[16] = [1.0, 1.004]
    packet[17] = [1, 2]

    class Board:
        def __init__(self, *args):
            self.reads = 0

        def prepare_session(self):
            pass

        def config_board(self, command):
            pass

        def start_stream(self):
            pass

        def get_board_data(self):
            self.reads += 1
            return packet if self.reads == 2 else np.empty((32, 0))

        @staticmethod
        def get_eeg_channels(board_id):
            return list(range(16))

        @staticmethod
        def get_timestamp_channel(board_id):
            return 16

        @staticmethod
        def get_package_num_channel(board_id):
            return 17

    monkeypatch.setattr(board_shim, 'BoardShim', Board)
    service = web.AcquisitionService()
    service._channels = web.CAP_CHANNEL_NAMES
    received = []

    def publish(samples, start, **kwargs):
        received.append((samples, start, kwargs))
        service._stop_event.set()

    service._publish_chunk = publish
    service._run_brainflow(web.StartRequest(mode='brainflow'))
    samples, start, metadata = received[0]
    assert start == 0
    assert samples.shape == (16, 2)
    np.testing.assert_array_equal(samples[:, 0], np.arange(1, 17))
    np.testing.assert_array_equal(metadata['package_ids'], [1, 2])


def test_first_samples_mark_connected():
    service = web.AcquisitionService()
    service._publish_chunk(np.zeros((16, 25)), 0)
    assert service.status().connected
    assert service.status().samples_emitted == 25


def test_display_filter_is_stateful_and_does_not_change_inference_input():
    from display_filter import DisplayFilter

    rate = 250
    times = np.arange(rate * 4) / rate
    samples = np.tile(30 * np.sin(2 * np.pi * 10 * times) +
                      180 * np.sin(2 * np.pi * 50 * times), (16, 1))
    display = DisplayFilter(rate)
    split = np.concatenate((display.process(samples[:, :421]),
                            display.process(samples[:, 421:])), axis=1)
    reference = DisplayFilter(rate).process(samples)
    np.testing.assert_allclose(split, reference, atol=1e-10)
    assert np.std(split[0, rate * 2:]) < np.std(samples[0, rate * 2:]) / 3
    assert np.std(split[0, rate * 2:]) > 10

    service = web.AcquisitionService()
    received = []
    service._adaptive.submit = lambda chunk, *args, **kwargs: received.append(chunk.copy())
    packets = []
    service._publish = packets.append
    service._publish_chunk(samples[:, :250], 0)
    np.testing.assert_array_equal(received[0], samples[:, :250])
    assert not np.allclose(packets[0]['samples_uv'], samples[:, :250])


def test_display_filter_resets_on_invalid_samples():
    from display_filter import DisplayFilter

    display = DisplayFilter(250)
    chunk = np.ones((16, 25))
    display.process(chunk)
    chunk[0, 0] = np.nan
    assert np.isfinite(display.process(chunk)).all()
    np.testing.assert_allclose(display.process(np.ones((16, 25)))[0],
                               DisplayFilter(250).process(np.ones((16, 25)))[0])


@pytest.mark.parametrize('rate', [250, 500, 1000])
def test_display_matches_lk_mini_implementation(rate, monkeypatch):
    from display_filter import DisplayFilter

    vendor = Path(__file__).parents[3] / 'LK-Mini-EEG16-Python'
    monkeypatch.syspath_prepend(str(vendor))
    from eeg_filter import EegFilter

    rng = np.random.default_rng(42)
    times = np.arange(rate * 3) / rate
    raw = np.vstack([20 * np.sin(2 * np.pi * 10 * times + channel) +
                     90 * np.sin(2 * np.pi * 50 * times) + rng.normal(0, 2, len(times))
                     for channel in range(16)])
    expected = np.vstack([EegFilter().process_samples(rate, values.tolist()) for values in raw])
    display = DisplayFilter(rate)
    actual = np.concatenate((display.process(raw[:, :137]), display.process(raw[:, 137:])), axis=1)
    np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)

    service = web.AcquisitionService()
    service._sample_rate_hz = rate
    service._channels = web.CAP_CHANNEL_NAMES
    service._display_filter = DisplayFilter(rate, 16)
    packets, inference = [], []
    service._publish = packets.append
    service._adaptive.submit = lambda samples, *args: inference.append(samples.copy())
    for start in range(0, raw.shape[1], 137):
        service._publish_chunk(raw[:, start:start + 137], start)
    displayed = np.concatenate([packet['samples_uv'] for packet in packets], axis=1)
    np.testing.assert_allclose(displayed, expected, atol=2e-4, rtol=1e-4)
    np.testing.assert_array_equal(np.concatenate(inference, axis=1), raw)
    assert all(packet['channels'] == list(web.CAP_CHANNEL_NAMES) for packet in packets)


@pytest.mark.parametrize('invalid', [np.nan, np.inf, -np.inf])
def test_invalid_display_block_never_bypasses_filter(invalid):
    from display_filter import DisplayFilter

    raw = np.full((16, 25), 1000.0)
    raw[15, 0] = invalid
    display = DisplayFilter(250, 16)
    filtered = display.process(raw)
    assert np.isfinite(filtered).all()
    np.testing.assert_array_equal(filtered[15], np.zeros(25))
    assert raw[15, 1] == 1000.0


def test_empty_display_packet_preserves_filter_state():
    from display_filter import DisplayFilter

    display = DisplayFilter(250, 16)
    reference = DisplayFilter(250, 16)
    samples = np.ones((16, 30))
    display.process(samples)
    reference.process(samples)
    assert display.process(np.empty((16, 0))).shape == (16, 0)
    np.testing.assert_array_equal(display.process(samples), reference.process(samples))


def test_display_invalid_channel_does_not_reset_other_channels():
    from display_filter import DisplayFilter

    data = np.ones((16, 100))
    interrupted = DisplayFilter(250)
    uninterrupted = DisplayFilter(250)
    interrupted.process(data)
    uninterrupted.process(data)
    broken = data.copy()
    broken[0, 0] = np.nan
    result = interrupted.process(broken)
    expected = uninterrupted.process(data)
    assert np.isfinite(result).all()
    np.testing.assert_allclose(result[1:], expected[1:])


def test_stop_keeps_live_thread_and_does_not_release_board():
    class Thread:
        def join(self, timeout):
            pass

        def is_alive(self):
            return True

    service = web.AcquisitionService()
    thread = Thread()
    service._thread = thread
    board = object()
    service._board = board
    service.stop()
    assert service._thread is thread
    assert service._board is board
    service.start(web.StartRequest())
    assert service._thread is thread
    assert service._stop_event.is_set()


@pytest.mark.parametrize('rate,command', [(250, '~6'), (500, '~5'), (1000, '~4')])
def test_no_data_times_out(monkeypatch, rate, command):
    commands = []
    from brainflow import board_shim

    class Board:
        def __init__(self, *args):
            pass

        def prepare_session(self):
            pass

        def config_board(self, command):
            commands.append(command)

        def start_stream(self):
            pass

        def get_board_data(self):
            return np.empty((32, 0))

        def stop_stream(self):
            pass

        def release_session(self):
            pass

        @staticmethod
        def get_eeg_channels(board_id):
            return list(range(16))

        @staticmethod
        def get_timestamp_channel(board_id):
            return 16

        @staticmethod
        def get_package_num_channel(board_id):
            return 17

    monkeypatch.setattr(board_shim, 'BoardShim', Board)
    times = iter([0.0, 11.0])
    monkeypatch.setattr(web.time, 'monotonic', lambda: next(times))
    service = web.AcquisitionService()
    request = web.StartRequest(mode='brainflow', sample_rate_hz=rate)
    service._sample_rate_hz = rate
    with pytest.raises(RuntimeError, match='10 秒'):
        service._run_brainflow(request)
    service._release_board()
    assert commands[0] == command
    assert len(commands[1]) == 16 * 9
    assert all(commands[1][index * 9 + 2] == '0' for index in range(16))
    assert service._board is None
