# Local experiment analysis

Protocol-specific participant charts, questionnaires, aligned physiology import,
and exploratory crossover analysis are documented in
[`../docs/EXPERIMENT_ANALYSIS_PARAMETERS.md`](../docs/EXPERIMENT_ANALYSIS_PARAMETERS.md).
The new three-condition panel uses only completed, verified hardware sessions and
averages repeated sessions within each participant/condition. It includes
Friedman and paired Wilcoxon tests with Holm-adjusted paired p values. The legacy
engineering tables below remain descriptive session-level diagnostics.

Open Administration > Experiments. Session JSON and final digital mix WAV remain
in `backEnd/session_reports/`, excluded from Git. Keep a separate local backup;
the application does not provide cloud backup or user accounts. Serve on loopback
only: this research administration screen is not an authenticated public portal.

Before recording, enter a participant name or preferably a de-identified ID and
select a condition. Each participant/condition gets independent UUID records and
automatically incremented trial numbers. Names are sensitive local data present
in reports, raw-recording metadata and CSV exports. Do not store consent forms here.
Optional blinded 1-7 comfort and musicality ratings remain subjective measurements.

Execution-versioned sessions now implement fixed/sham/closed-loop assignment:
fixed uses an external player with no local audio; sham uses an independent
scripted demo controller while recording real EEG separately; closed loop uses
the existing current-EEG music path. Executed conditions cannot be relabeled.
Legacy labels still do not prove execution. Sessions run for 2700 seconds or until
manual stop/error; N2 music pause does not terminate assigned EEG recordings.
The sham script is not a historical yoked trajectory, and online generation is
still available; freeze the intended protocol before formal studies.
Demo records are excluded by default. Running sessions are
excluded from summaries. CSV exports all records, including demo/unassigned ones;
filter by mode, ended and condition before statistical use.

Group tables show per-session means and sample SD with available-value counts.
Repeated trials are not independent participants. No significance or causal
superiority is inferred. Participant filtering supports inspecting within-person
conditions. The paired-difference table averages repeated trials within each
participant/condition, then summarizes participant-level closed-loop minus
fixed/sham differences with available-pair counts. It is not a significance test.
Missing values remain
blank in CSV, not zero.

Search by participant name/ID, filter condition and select one or more records.
Detailed metrics and charts share that selection (all filtered records if none
selected). New metrics include standard ten-item SUS scoring, separate transition
naturalness VAS, alpha 8-12 Hz and theta 4-8 Hz relative power over 1-30 Hz,
backend process CPU and process-lifetime peak RSS. The original alpha 8-13 Hz
metric and musicality/SongEval scores remain available. Heart-rate work is
external; no HR/RMSSD outcome is exposed in the current analysis UI.

Available: duration, overlapping qualified-window ratio, mean classification
time, quality-qualified 40-second Welch alpha/theta/beta power averaged across
recorded channels, final-mix recording duration/status, spectral centroid,
>=8kHz energy ratio, sample peak, overload sample count, RMS rise candidates,
browser control/error counts and observed download/decode times.

Audio spectral values are means of recorded blocks, not perceptual quality
scores; recordings may be partial. Use comparable sample rates, channels and
protocols. No validated BPM/chord/key, LUFS/true-peak, packet-loss aggregate,
hardware output latency or SPL is implemented. No automatic sleep-benefit or
comfort conclusions. Existing session reports retain detailed window and control
traces and the final-mix WAV, where recorded.
