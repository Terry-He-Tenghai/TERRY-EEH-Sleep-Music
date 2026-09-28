import time

import numpy as np
import pytest

from adaptive_web import AdaptiveWebService, _Session
from channel_mapping import CAP_ORDER
from degraded_classifier import classify_window


@pytest.mark.parametrize('channel_count,physical_count', [(8, 8), (8, 16), (16, 16)])
def test_live_spectral_feedback_uses_selected_measured_channels(channel_count, physical_count):
    rate = 250
    seconds = np.arange(rate * 6) / rate
    samples = np.vstack([
        20 * np.sin(2 * np.pi * (5 + index % 7) * seconds + index / 3)
        for index in range(physical_count)
    ])
    events = []
    service = AdaptiveWebService(events.append)
    ctx = _Session(1, 'LIVE', rate, CAP_ORDER[:physical_count], classification_channels=channel_count,
                   music_source='ace')
    service._session = ctx
    def capture(event):
        events.append(event)
        if (event.get('state') or {}).get('status') == 'ok':
            ctx.cancelled.set()
    service._publish = capture
    ctx.chunks.put((samples, 0, rate, seconds, time.monotonic(),
                    np.arange(rate * 6) % 256))
    service._process(ctx)
    ready = next(event for event in events if event['state'] and event['state']['status'] == 'ok')
    assert ready['classification_channels'] == channel_count
    assert ready['inference_mode'] == 'spectral_heuristic'
    assert ready['probability_origin'] == 'eeg_spectral_heuristic_unvalidated'
    assert len(ready['channel_repair']['used_channels']) == channel_count
    assert set(ready['probabilities']) == {'W', 'N1', 'N2'}
    assert sum(ready['probabilities'].values()) == pytest.approx(1)
    ctx.cancelled.set()


def test_spectral_classifier_rejects_no_usable_channels():
    with pytest.raises(ValueError, match='no usable channels'):
        classify_window(np.full((8, 1500), np.nan), 250)
