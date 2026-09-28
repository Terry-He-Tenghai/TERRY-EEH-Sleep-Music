# Optional pretrained sleep staging

The live path integrates YASA 0.7.0 EEG-only pretrained classifiers. Spectral
feedback remains available every six seconds independently of model readiness.

## Hardware confirmation (required before model activation)

Edit `config.pretrained.yaml`, then restart the backend. `enabled: true` alone
does not assert compatibility. Verify the physical CH0–CH15 wiring against
`channel_mapping.CAP_ORDER` and only then set `channel_map_confirmed: true`.
Set `reference` to the **actual common measurement reference**, not ground:

- `M1`: adapter uses measured C4 (C4-M1).
- `M2`: adapter uses measured C3 (C3-M2).
- `Fpz`: adapter uses measured C3 or C4 relative to Fpz.
- Unknown, average reference, or any other setting: spectral fallback only.

The adapter does not invent reference signals, relabel Fp1 as Fpz, or use
interpolated Fz/Cz. Hardware assertions are operator-provided, not inferred from
waveforms. Confirm the device's microvolt scaling too. Input microvolts are
converted to volts for MNE; YASA owns filtering and resampling.

The 8-channel selection now uses Fp1, Fp2, C3, C4, P7, P8, O1, O2. Acquisition
still reads all 16 physical channels. The pretrained adapter selects a matched,
quality-passing central electrode; other electrodes remain available for the
spectral fallback. This is not an eight-/sixteen-input trained network.

## Timing and outputs

The adapter collects 300 seconds of continuous clean data on the same electrode,
retains at most 600 seconds, and submits at most one job per adapter at a time,
every 30 seconds. Shared inference concurrency is one. Data gaps, channel changes
and quality loss invalidate its history. Old asynchronous results are rejected
by revision. Results older than 36 seconds of EEG time are not used.

This is an **experimental rolling latest-epoch adaptation**, not equivalent to
YASA's validated full-night use. Its centered context and recording-wide feature
normalization differ near a streaming endpoint. Do not claim clinical accuracy.

`pretrained.probabilities` preserves W/N1/N2/N3/REM. The existing `probabilities`
field remains the explicitly identified three-class spectral estimate. The UI
shows both separately and reports fallback reasons. For ACE only, a fresh YASA
result selects the requested music target: W → M1, N1/REM → M2, N2/N3 → M3. These
are music policy choices, **not relabeling of sleep stages**. Other audio paths
retain spectral control. `music_control_origin` identifies the active source.

Missing dependencies, incompatible configuration, no matched clean electrode,
warmup, prediction errors or expired predictions leave spectral/ACE operation
available. This does not remove the existing no-data and playback checks.

## Verification

Install project dependencies (YASA pinned to 0.7.0). Run:

    python -m pytest tests/test_pretrained_classifier.py tests/test_live_availability.py

A real pretrained-weight inference smoke test was run on synthetic data. This
checks execution and output schema only, not sleep classification accuracy.
The installed scikit-learn 1.9.1 reports a LabelEncoder serialization-version
warning for the bundled old model artifact (0.24.2); inference completed, but
this compatibility warning and target-device validation remain limitations.
No remote ACE service or physical cap test is implied by mocked integration tests.

Official documentation: https://yasa-sleep.org/generated/yasa.SleepStaging.html
