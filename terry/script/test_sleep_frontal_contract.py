"""CPU contract tests for independent frontal waveform training."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import torch
import train_sleep_subset_models as old
import train_sleep_frontal_models as frontal


class FrontalContractTests(unittest.TestCase):
    def test_montages_and_old_contract_unchanged(self):
        self.assertEqual(old.MONTAGES[2], ("C3", "C4"))
        self.assertEqual(old.pipeline_for(2)["version"], "cap-waveform-subset-v1")
        self.assertEqual(frontal.MONTAGES, {
            2: ("Fp1", "Fp2"), 4: ("Fp1", "Fp2", "F3", "F4"),
            6: ("Fp1", "Fp2", "F3", "F4", "F7", "F8")})
        for count, channels in frontal.MONTAGES.items():
            pipeline = frontal.pipeline_for(count)
            self.assertEqual(pipeline["version"], frontal.VERSION)
            self.assertEqual(pipeline["channels"], list(channels))
            self.assertEqual(pipeline["qc"]["required_clean_channels"], list(channels))
            self.assertFalse(pipeline["qc"]["require_all_16_clean"])

    def test_preprocessing_and_cpu_models(self):
        torch.set_num_threads(2)
        t = np.arange(10000) / 250
        for count in frontal.MONTAGES:
            x = np.stack([15 * np.sin(2 * np.pi * (8 + i) * t) for i in range(count)])
            processed, reason = frontal.preprocess_window(x, 250, count)
            self.assertIsNone(reason)
            inp = frontal.model_input(processed, count)
            self.assertEqual(inp.shape, (count, 7500))
            np.testing.assert_allclose(inp.mean(axis=0), 0, atol=1e-7)
            model = frontal.build_model(torch, count).eval()
            checkpoint = {"architecture": frontal.ARCHITECTURE,
                          "channels": list(frontal.MONTAGES[count]),
                          "pipeline": frontal.pipeline_for(count),
                          "classes": list(frontal.STAGES), "deployment_ready": False,
                          "state_dict": model.state_dict()}
            frontal.validate_checkpoint(checkpoint, count)
            model.load_state_dict(checkpoint["state_dict"], strict=True)
            with torch.inference_mode():
                logits = model(torch.from_numpy(inp[None]))
            self.assertEqual(tuple(logits.shape), (1, 3))
            self.assertTrue(torch.isfinite(logits).all())
            checkpoint["architecture"] = "build_model:cap-waveform-subset-v1"
            with self.assertRaises(ValueError):
                frontal.validate_checkpoint(checkpoint, count)
            x[0] = 0
            self.assertEqual(frontal.preprocess_window(x, 250, count)[1], "flat_signal")

    def test_central_cache_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "subject.json").write_text(json.dumps({"source": {"pipeline": old.pipeline_for(2)}}))
            with self.assertRaisesRegex(ValueError, "incompatible cache contract"):
                frontal.EpochDataset(path, ["subject"], 2)

    def test_channel_selection_independent(self):
        info = {"labels": ["EEG " + c for c in ("C3", "C4", "Fp1", "Fp2", "F3", "F4", "F7", "F8")],
                "units": ["uV"] * 8}
        self.assertEqual(frontal.channel_selection(info, 6),
                         ["EEG " + c for c in frontal.MONTAGES[6]])


if __name__ == "__main__":
    unittest.main()
