"""Bounded, asynchronous recording of unfiltered acquisition samples."""
import csv
import json
from pathlib import Path
import queue
import threading
import time
import uuid

import numpy as np


ROOT = Path(__file__).parent / 'recordings'


class RawRecording:
    def __init__(self, metadata, root=ROOT):
        self.path = Path(root) / f'{time.strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:12]}'
        self.path.mkdir(parents=True)
        self.metadata = dict(metadata, unit='uV', filtered=False, started_at_s=time.time(),
                             samples_written=0, error=None, complete=False)
        self.queue = queue.Queue(maxsize=256)
        self.lock = threading.Lock()
        self.accepting = True
        self.handle = (self.path / 'raw_eeg.csv').open('w', newline='', encoding='utf-8')
        try:
            self.writer = csv.writer(self.handle)
            self.writer.writerow(['sample_index', 'relative_time_s', 'hardware_timestamp_s',
                                  'package_id', 'received_at_s',
                                  *[f'{name}_uV' for name in metadata['channels']]])
            self.handle.flush()
            self._save_metadata()
        except Exception:
            self.handle.close()
            raise
        self.thread = threading.Thread(target=self._run, name='eeg-raw-writer', daemon=True)
        self.thread.start()

    def _save_metadata(self):
        temporary = self.path / 'metadata.tmp'
        temporary.write_text(json.dumps(self.metadata, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
        temporary.replace(self.path / 'metadata.json')

    def status(self):
        with self.lock:
            return dict(enabled=True, path=str(self.path.resolve()),
                        samples_written=self.metadata['samples_written'],
                        error=self.metadata['error'], complete=self.metadata['complete'])

    def submit(self, samples, start, timestamps=None, packages=None):
        with self.lock:
            if not self.accepting or self.metadata['error']:
                return
            item = (np.array(samples, copy=True), start,
                    None if timestamps is None else np.array(timestamps, copy=True),
                    None if packages is None else np.array(packages, copy=True), time.time())
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                self.metadata['error'] = '原始数据保存队列已满，文件不完整；请检查磁盘速度和空间。'

    def close(self):
        with self.lock:
            if not self.accepting:
                return
            self.accepting = False
        self.queue.put(None)
        self.thread.join()

    def _run(self):
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                samples, start, timestamps, packages, received = item
                rate = self.metadata['sample_rate_hz']
                self.writer.writerows(
                    [start + i, (start + i) / rate,
                     '' if timestamps is None else timestamps[i],
                     '' if packages is None else packages[i], received, *samples[:, i]]
                    for i in range(samples.shape[1]))
                self.handle.flush()
                with self.lock:
                    self.metadata['samples_written'] += samples.shape[1]
                self._save_metadata()
        except Exception as exc:
            with self.lock:
                self.metadata['error'] = f'原始数据写盘失败，文件可能不完整：{exc}'
            # Keep draining so close() cannot block on a full queue after failure.
            while self.queue.get() is not None:
                pass
        finally:
            try:
                self.handle.close()
            except Exception as exc:
                self.metadata['error'] = f'原始数据文件关闭失败：{exc}'
            with self.lock:
                self.metadata['ended_at_s'] = time.time()
                self.metadata['complete'] = self.metadata['error'] is None
            try:
                self._save_metadata()
            except Exception as exc:
                with self.lock:
                    self.metadata['error'] = f'原始数据元信息保存失败：{exc}'
                    self.metadata['complete'] = False
