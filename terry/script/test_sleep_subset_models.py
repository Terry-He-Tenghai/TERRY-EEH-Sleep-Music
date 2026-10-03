"""Contract tests; run with python -m unittest discover -s terry/script -p test_sleep_subset_models.py."""
import unittest
import numpy as np
import train_sleep_waveform_models as old
import train_sleep_subset_models as subset


class SubsetContractTests(unittest.TestCase):
    def waveform(self, count, rate=250):
        t = np.arange(40 * rate) / rate
        return np.stack([15 * np.sin(2 * np.pi * (5 + i) * t) for i in range(count)])

    def test_exact_montages_and_independent_pipeline(self):
        self.assertEqual(subset.MONTAGES, {2: ('C3', 'C4'), 4: ('Fp1', 'Fp2', 'C3', 'C4'), 6: ('Fp1', 'Fp2', 'C3', 'C4', 'F3', 'F4')})
        for c in subset.MONTAGES:
            p = subset.pipeline_for(c)
            self.assertEqual(p['channels'], list(subset.MONTAGES[c]))
            self.assertFalse(p['qc']['require_all_16_clean'])
            self.assertEqual(p['sample_rate_hz'], 250)
            self.assertEqual(p['past_context_seconds'], 10)
            self.assertEqual(p['window_seconds'], 30)
            p['qc']['maximum_filtered_ptp_uv'] = 0
            self.assertEqual(subset.pipeline_for(c)['qc']['maximum_filtered_ptp_uv'], 500)
        self.assertTrue(old.PIPELINE['qc']['require_all_16_clean'])
        self.assertEqual(old.PIPELINE['version'], 'cap-waveform-v1')

    def test_selected_only_and_identical_old_temporal_filter(self):
        for rate in (250, 512):
            all16 = self.waveform(16, rate)
            expected, reason = old.preprocess_window(all16, rate)
            self.assertIsNone(reason)
            for c, names in subset.MONTAGES.items():
                indexes = [old.CAP16.index(n) for n in names]
                actual, reason = subset.preprocess_window(all16[indexes], rate, c)
                self.assertIsNone(reason)
                self.assertEqual(actual.shape, (c, 7500))
                np.testing.assert_allclose(actual, expected[indexes], rtol=0, atol=0)
                referenced = subset.model_input(actual, c)
                np.testing.assert_allclose(referenced.sum(axis=0), 0, atol=1e-6)
                np.testing.assert_allclose(referenced, (actual - actual.mean(axis=0)) / 100)

    def test_quality_rejections(self):
        for c in subset.MONTAGES:
            x = self.waveform(c)
            x[0] = 0
            self.assertEqual(subset.preprocess_window(x, 250, c)[1], 'flat_signal')
            x = self.waveform(c)
            x[0, 0] = np.nan
            self.assertEqual(subset.preprocess_window(x, 250, c)[1], 'nonfinite')
            x = self.waveform(c) * 100
            self.assertEqual(subset.preprocess_window(x, 250, c)[1], 'high_amplitude')
            with self.assertRaises(ValueError):
                subset.preprocess_window(self.waveform(c)[:, :-1], 250, c)
            with self.assertRaises(ValueError):
                subset.model_input(self.waveform(c), c)

    def test_unused_channels_need_not_exist(self):
        info = {'labels': ['EEG C3-REF', 'C4'], 'units': ['uV', 'uV']}
        self.assertEqual(subset.channel_selection(info, 2), info['labels'])
        with self.assertRaises(ValueError):
            subset.channel_selection(info, 4)
        x = self.waveform(16)
        x[old.CAP16.index('O1')] = 0
        self.assertEqual(old.preprocess_window(x, 250)[1], 'flat_signal')
        for c, names in subset.MONTAGES.items():
            chosen = x[[old.CAP16.index(n) for n in names]]
            self.assertIsNone(subset.preprocess_window(chosen, 250, c)[1])

    def test_direct_edf_reader_calibration_and_truncation(self):
        import tempfile
        from pathlib import Path
        def field(value, width):
            return str(value).encode('ascii').ljust(width, b' ')
        header = (b'0       ' + b' ' * 160 + b'01.01.25' + b'00.00.00' + field(768, 8)
                  + b' ' * 44 + field(2, 8) + field(1, 8) + field(2, 4))
        values = [('labels', 16, ['C3', 'C4']), ('transducer', 80, ['', '']),
                  ('units', 8, ['uV', 'uV']), ('physical_min', 8, [-100, -200]),
                  ('physical_max', 8, [100, 200]), ('digital_min', 8, [-32768, -32768]),
                  ('digital_max', 8, [32767, 32767]), ('prefilter', 80, ['', '']),
                  ('samples_per_record', 8, [250, 250]), ('reserved', 32, ['', ''])]
        signal_header = b''.join(field(v, width) for _, width, vs in values for v in vs)
        records = np.stack([np.arange(500, dtype='<i2'), np.arange(500, 1000, dtype='<i2')])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.edf'
            path.write_bytes(header + signal_header + records.tobytes())
            actual, rate, _, selected = subset.load_selected_edf(path, 2)
            self.assertEqual(rate, 250)
            self.assertEqual(selected, ['C3', 'C4'])
            digital = np.stack([records[:, :250].reshape(-1), records[:, 250:].reshape(-1)]).astype(float)
            expected = (digital + 32768) * np.array([200, 400])[:, None] / 65535 - np.array([100, 200])[:, None]
            np.testing.assert_allclose(actual, expected)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                subset.load_selected_edf(path, 2)

    def test_models(self):
        import torch
        for c in subset.MONTAGES:
            model = subset.build_model(torch, c).eval()
            with torch.inference_mode():
                self.assertEqual(tuple(model(torch.zeros(2, c, 7500)).shape), (2, 3))

if __name__ == '__main__':
    unittest.main()
