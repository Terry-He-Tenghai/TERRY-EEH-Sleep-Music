"""Stateful LK-Mini EEG display cascade; never feed its output to inference.

Coefficients and order match LK-Mini-EEG16-Python/eeg_filter.py for the three
sample rates accepted by the Terry web acquisition endpoint.
"""

import numpy as np
from scipy.signal import sosfilt, tf2sos


COEFFICIENTS = {
    250: (
        ([.848475295524359, -3.39390118209744, 5.09085177314616, -3.39390118209744, .848475295524359],
         [1, -3.67172908916194, 5.06799838673419, -3.11596692520175, .719910327291872]),
        ([.010312874762664404, .06187724857598642, .15469312143996605, .20625749525328807,
          .15469312143996605, .06187724857598642, .010312874762664404],
         [1, -1.1876006801756145, 1.3052133492885498, -.6743275252979981,
          .2634693482801379, -.05175303387964128, .00502252659508814]),
        ([.936813880017972, -.578982818983773, .936813880017972],
         [1, -.578982818983773, .873627760035944]),
    ),
    500: (
        ([.921170993499942, -3.68468397399977, 5.52702596099965, -3.68468397399977, .921170993499942],
         [1, -3.83582554064735, 5.52081913662223, -3.53353521946301, .848555999266477]),
        ([.0003405376527201276, .0020432259163207654, .005108064790801914,
          .006810753054402552, .005108064790801914, .0020432259163207654, .0003405376527201276],
         [1, -3.5794347983311923, 5.658667165933625, -4.96541522877857,
          2.529494905841447, -.7052741145099005, .08375647961867892]),
        ([.967437388703836, -1.56534657691025, .967437388703836],
         [1, -1.56534657691025, .934874777407671]),
    ),
    1000: (
        ([.959782230087239, -3.83912892034895, 5.75869338052343, -3.83912892034895, .959782230087239],
         [1, -3.91790786539199, 5.75707637911807, -3.76034950769453, .921181929191236]),
        ([8.576557073259404e-06, 5.145934243955643e-05, .00012864835609889108,
          .00017153114146518808, .00012864835609889108, 5.145934243955643e-05, 8.576557073259404e-06],
         [1, -4.787135498852133, 9.649517728721909, -10.46907889254386,
          6.441111881008067, -2.1290387500304497, .295172431349155]),
        ([.983457100401067, -1.87064656766634, .983457100401067],
         [1, -1.87064656766634, .966914200802133]),
    ),
}


class DisplayFilter:
    def __init__(self, sample_rate_hz: int, channels: int = 16):
        if sample_rate_hz not in COEFFICIENTS:
            raise ValueError(f"Unsupported LK-Mini display rate: {sample_rate_hz}")
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.stages = [tf2sos(b, a) for b, a in COEFFICIENTS[sample_rate_hz]]
        self.states = [np.zeros((len(sos), channels, 2)) for sos in self.stages]

    def process(self, samples_uv: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples_uv, dtype=float)
        if samples.ndim != 2 or samples.shape[0] != self.channels:
            raise ValueError("Display EEG channel count mismatch")
        if samples.shape[1] == 0:
            return samples.copy()
        output = np.empty_like(samples)
        for channel in range(self.channels):
            values = samples[channel]
            if not np.isfinite(values).all():
                for state in self.states:
                    state[:, channel, :] = 0
                # Suppress this invalid display block instead of leaking raw noise.
                # The untouched raw block still reaches inference quality checks.
                output[channel] = 0
                continue
            for sos, state in zip(self.stages, self.states, strict=True):
                values, state[:, channel, :] = sosfilt(sos, values, zi=state[:, channel, :])
            output[channel] = values
        return output
