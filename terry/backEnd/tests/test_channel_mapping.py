import numpy as np
import pytest

from channel_mapping import CAP_ORDER, MODEL_ORDER, map_cap_to_model


def test_map_cap_to_legacy_model_preserves_measured_sites():
    samples = np.arange(16 * 7, dtype=float).reshape(16, 7)
    mapped = map_cap_to_model(samples, CAP_ORDER)
    assert mapped.shape == (16, 7)
    for name in set(MODEL_ORDER) - {"Fz", "Cz"}:
        np.testing.assert_array_equal(mapped[MODEL_ORDER.index(name)], samples[CAP_ORDER.index(name)])
    np.testing.assert_array_equal(mapped[MODEL_ORDER.index("Fz")],
                                  (samples[CAP_ORDER.index("F3")] + samples[CAP_ORDER.index("F4")]) / 2)
    np.testing.assert_array_equal(mapped[MODEL_ORDER.index("Cz")],
                                  (samples[CAP_ORDER.index("C3")] + samples[CAP_ORDER.index("C4")]) / 2)


@pytest.mark.parametrize("channels,samples", [
    (CAP_ORDER[:8], np.zeros((8, 10))),
    (CAP_ORDER[::-1], np.zeros((16, 10))),
    (CAP_ORDER, np.zeros((15, 10))),
])
def test_map_rejects_reduced_or_reordered_input(channels, samples):
    with pytest.raises(ValueError, match="16 physical cap channels"):
        map_cap_to_model(samples, channels)
