import csv
import json
import threading

import numpy as np

from raw_recording import RawRecording


def test_raw_samples_and_hardware_metadata_are_preserved(tmp_path):
    recording = RawRecording(dict(channels=['Fp1', 'Fp2'], sample_rate_hz=250,
                                  gain=24, mode='brainflow', report_id='test'), tmp_path)
    raw = np.array([[10000.12345678, np.nan, np.inf], [4, 5, 6]])
    recording.submit(raw, 25, np.array([1, 1.004, 1.008]), np.array([254, 255, 0]))
    raw[:] = 0
    recording.close()
    recording.close()
    with (recording.path / 'raw_eeg.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert float(rows[0]['Fp1_uV']) == 10000.12345678
    assert rows[1]['Fp1_uV'] == 'nan'
    assert rows[2]['Fp1_uV'] == 'inf'
    assert [int(float(row['package_id'])) for row in rows] == [254, 255, 0]
    assert float(rows[0]['relative_time_s']) == .1
    assert float(rows[1]['hardware_timestamp_s']) == 1.004
    meta = json.loads((recording.path / 'metadata.json').read_text())
    assert meta['filtered'] is False
    assert meta['unit'] == 'uV'
    assert meta['complete'] is True
    assert meta['samples_written'] == 3
    assert recording.status()['complete'] is True


def test_demo_has_no_fabricated_hardware_clock(tmp_path):
    recording = RawRecording(dict(channels=['C3'], sample_rate_hz=500, mode='demo'), tmp_path)
    recording.submit(np.ones((1, 3)), 10)
    recording.close()
    with (recording.path / 'raw_eeg.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]['hardware_timestamp_s'] == ''
    assert rows[0]['package_id'] == ''
    assert float(rows[0]['relative_time_s']) == .02


def test_disk_failure_is_visible_and_close_does_not_deadlock(tmp_path):
    recording = RawRecording(dict(channels=['C3'], sample_rate_hz=250), tmp_path)
    class BrokenWriter:
        def writerows(self, rows):
            raise OSError('disk full')
    recording.writer = BrokenWriter()
    recording.submit(np.ones((1, 3)), 0)
    recording.close()
    assert 'disk full' in recording.status()['error']
    assert recording.status()['complete'] is False
    assert recording.status()['samples_written'] == 0


def test_queue_overflow_is_reported_as_incomplete(tmp_path):
    recording = RawRecording(dict(channels=['C3'], sample_rate_hz=250), tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = recording.writer
    class SlowWriter:
        def writerows(self, rows):
            entered.set()
            assert release.wait(5)
            original.writerows(rows)
    recording.writer = SlowWriter()
    recording.submit(np.ones((1, 1)), 0)
    assert entered.wait(5)
    for index in range(257):
        recording.submit(np.ones((1, 1)), index + 1)
    assert recording.status()['error']
    release.set()
    recording.close()
    assert recording.status()['complete'] is False
    assert recording.status()['samples_written'] == 257
