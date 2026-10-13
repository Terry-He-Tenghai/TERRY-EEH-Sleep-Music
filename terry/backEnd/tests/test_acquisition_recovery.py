"""Failure injection without a physical board or network connection."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from brainflow.exit_codes import BrainFlowError

from test_web_acquisition import web
from session_reports import Reports


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    store = Reports(tmp_path / 'reports')
    monkeypatch.setattr(web, 'reports', store)
    store.start({'mode': 'brainflow'})
    service = web.AcquisitionService()
    service._adaptive = SimpleNamespace(stop=Mock())
    service._sham = SimpleNamespace(stop=Mock())
    monkeypatch.setattr(web.ace_automatic, 'stop', Mock())
    board = SimpleNamespace(stop_stream=Mock(), release_session=Mock())
    service._board = board
    return service, board, store


def test_original_error_survives_failed_reporting_and_cleanup(acquisition, monkeypatch):
    service, board, store = acquisition

    def source(request):
        service._phase = 'prepare_session'
        raise RuntimeError('BOARD_WRITE_ERROR:4')

    monkeypatch.setattr(service, '_run_brainflow', source)
    monkeypatch.setattr(store, 'attach', Mock(side_effect=OSError('disk full')))
    monkeypatch.setattr(store, 'finish', Mock(side_effect=OSError('disk full')))
    service._sham.stop.side_effect = RuntimeError('sham cleanup')
    service._adaptive.stop.side_effect = RuntimeError('inference cleanup')
    board.stop_stream.side_effect = RuntimeError('stream never started')
    service._run(web.StartRequest(mode='brainflow'), 1)
    board.release_session.assert_called_once()
    assert service._board is None
    assert not service.status().streaming
    assert 'prepare_session' in service.status().error
    assert 'BOARD_WRITE_ERROR:4' in service.status().error


@pytest.mark.parametrize('code', [4, 17])
def test_prepare_error_explains_connection_checks(acquisition, monkeypatch, code):
    service, board, store = acquisition

    def source(request):
        service._phase = 'prepare_session'
        raise BrainFlowError('unable to prepare streaming session', code)

    monkeypatch.setattr(service, '_run_brainflow', source)
    board.release_session.side_effect = BrainFlowError('unable to release streaming session', 15)
    service._run(web.StartRequest(mode='brainflow'), 1)
    assert '192.168.4.1:12345' in service.status().error
    assert '设备供电' in service.status().error
    assert store.load(store.current['id'])['acquisition_error']['exception_type'] == 'BrainFlowError'
    board.stop_stream.assert_not_called()
    board.release_session.assert_called_once()


def test_error_is_saved_with_phase_and_traceback(acquisition, monkeypatch):
    service, board, store = acquisition

    def source(request):
        service._phase = 'stream_no_data'
        raise RuntimeError('no new samples')

    monkeypatch.setattr(service, '_run_brainflow', source)
    service._run(web.StartRequest(mode='brainflow'), 1)
    report = store.load(store.current['id'])
    assert report['end_reason'] == 'acquisition_error'
    error = report['acquisition_error']
    assert error['phase'] == 'stream_no_data'
    assert 'RuntimeError: no new samples' in error['traceback']
    assert error['backend_root'] == str(web.BACKEND_ROOT)
    board.release_session.assert_called_once()


def test_board_released_before_recording_cleanup(acquisition, monkeypatch):
    service, board, store = acquisition

    def close():
        board.release_session.assert_called_once()
        raise OSError('writer failed')

    service._recording = SimpleNamespace(close=close, status=lambda: {'error': 'writer failed'})
    monkeypatch.setattr(service, '_run_demo', lambda request: service._stop_event.set())
    service._run(web.StartRequest(), 1)
    assert service._board is None
    assert store.current['end_reason'] == 'manual_stop'


def test_health_identifies_loaded_source():
    import asyncio
    result = asyncio.run(web.health())
    assert result['backend_root'] == str(web.BACKEND_ROOT)
    assert result['acquisition_revision'] == web.ACQUISITION_REVISION


@pytest.mark.parametrize('phase', [
    'prepare_session', 'configure_sample_rate', 'configure_channels',
    'start_stream', 'initial_read', 'read_stream',
])
def test_hardware_stage_failure_releases_session(acquisition, monkeypatch, phase):
    from brainflow import board_shim
    import numpy as np
    service, board, store = acquisition
    configuration = 0
    reads = 0

    def fail_at(stage):
        if phase == stage:
            raise RuntimeError('injected device failure')

    def configure(command):
        nonlocal configuration
        configuration += 1
        fail_at('configure_sample_rate' if configuration == 1 else 'configure_channels')

    def read():
        nonlocal reads
        reads += 1
        fail_at('initial_read' if reads == 1 else 'read_stream')
        return np.empty((32, 0))

    class Board:
        def __new__(cls, identifier, params):
            assert params.timeout == 10
            return board

        get_eeg_channels = staticmethod(lambda identifier: list(range(16)))
        get_timestamp_channel = staticmethod(lambda identifier: 16)
        get_package_num_channel = staticmethod(lambda identifier: 17)

    board.prepare_session = lambda: fail_at('prepare_session')
    board.config_board = configure
    board.start_stream = lambda: fail_at('start_stream')
    board.get_board_data = read
    monkeypatch.setattr(board_shim, 'BoardShim', Board)
    service._run(web.StartRequest(mode='brainflow'), 1)
    assert store.current['acquisition_error']['phase'] == phase
    board.release_session.assert_called_once()
    assert board.stop_stream.call_count == (1 if phase in ('initial_read', 'read_stream') else 0)
    assert not service.status().streaming
