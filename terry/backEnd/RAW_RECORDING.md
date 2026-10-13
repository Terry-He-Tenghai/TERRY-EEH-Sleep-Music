# Local Raw EEG Recording

The acquisition page enables raw saving by default. Set the checkbox before
starting a session; it is locked while acquisition is running. The API accepts
`save_raw_data: true` on `POST /api/acquisition/start` (API default: false).

Each enabled session creates a unique directory under `backEnd/recordings/`:

- `raw_eeg.csv`: one row per received sample, all 16 channels in acquisition
  order, unfiltered BrainFlow microvolt values (or explicitly labelled DEMO
  synthetic values). Nonfinite input remains `nan`/`inf`; no clipping, rounding,
  quality rejection, interpolation or display filtering is applied.
- `metadata.json`: source, sample rate, configured gain, channel names, music
  and experiment settings, report ID, start/end wall times, written count and
  completion/error status. The report ID links quality/classification events in
  `backEnd/session_reports/<report_id>.json`.

CSV columns: `sample_index`, `relative_time_s`, `hardware_timestamp_s`,
`package_id`, `received_at_s`, then `<channel>_uV` for every channel.
Relative time is the sample index divided by configured rate, not a hardware
clock. Receipt time is the host Unix time for the whole block; hardware times
and package counters are preserved separately. DEMO has empty hardware fields.
Indices describe received samples; use package IDs and hardware timestamps to
investigate transport gaps. Raw ADC bytes and measured impedance are not saved.

A bounded writer queue runs independently of inference and browser display.
Each written block is flushed, and normal acquisition termination drains the
queue and marks completion. Queue overflow/disk errors are shown as incomplete
recording errors while acquisition continues. Do not use an incomplete file as
evidence of uninterrupted acquisition. A killed process/power loss can leave
`complete: false`; flushing does not guarantee durability across power loss.

Recording folders are Git-ignored. Keep participant identifiers anonymous and
manage local EEG retention according to the study's consent/data policy.
