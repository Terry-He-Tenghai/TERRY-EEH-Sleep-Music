# Local experiment analysis

Open Administration > Experiments. Session JSON and final digital mix WAV remain
in `backEnd/session_reports/`, excluded from Git. Keep a separate local backup;
the application does not provide cloud backup or user accounts. Serve on loopback
only: this research administration screen is not an authenticated public portal.

After a session, assign an anonymous participant ID, actual treatment condition,
trial number and protocol/deviation notes. Optional blinded 1-7 comfort and
musicality ratings are subjective, not objective audio measurements. Do not enter
names, identifying information or consent forms here.

Labels do NOT execute fixed/sham/closed-loop treatment assignment. Verify the
actual playback protocol before labeling, randomize condition order and use the
same source material. Demo records are excluded by default. Running sessions are
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
