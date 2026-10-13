# Session evidence implementation

Each new acquisition creates a UUID report in `backEnd/session_reports/`.
Existing sessions cannot be reconstructed retrospectively. Assigned A/B/C trials
end at their configured duration (45 minutes by default), manual stop, or an
acquisition/inference error. N2 may pause music but does not end these trials.
Three distinct consecutive quality-qualified LIVE N2 results initiate a
30-second music fade, including unassigned API sessions; EEG recording continues.
Scripted demonstration N2 never triggers this real-signal pause or establishes sleep.

Each assigned trial requires a participant name or ID, automatically increments
the participant-condition trial number and saves raw EEG locally. Fixed A uses
external-device audio only. Sham B records measured EEG in `windows` separately
from its independent scripted music trajectory in `control_windows`. Closed-loop
C retains the current EEG-driven music workflow. The executed condition is
immutable in the report editor; legacy labels do not prove actual execution.

Three acquisition players tap their final master node, after all their mixing
and effects. An AudioWorklet captures stereo Float32 WAV without quantizing or
clipping overloads. This is NOT a microphone or hardware loopback recording;
other applications and the separate manual workbench are outside its scope.
Capturing starts asynchronously after arming; its start time is recorded.
At 360 MiB (approximately 16 minutes at 48 kHz stereo Float32) capture becomes
explicitly partial to bound browser memory. Audio must be uploaded at normal
session finish. Browser termination/crash can lose audio, though backend EEG
evidence remains. If upload fails, the page offers a recovery WAV download.

Reports currently provide:

- timestamps, reason, received sample duration and evaluated-window quality ratio;
- window model scores, quality/channel details and confirmed LIVE raw-window
  Welch alpha/theta/beta absolute power in uV^2;
- alpha 8-12 Hz and theta 4-8 Hz relative power with a 1-30 Hz denominator,
  alongside the legacy alpha 8-13 Hz value;
- successful waveform classification processing time (including spectral summary);
- playback/control logs with sequences and Web Audio times; ACE download/decode;
- final recording and one-second RMS dBFS, sample peak, overload count,
  spectral centroid, high-frequency power ratio and RMS-rise candidates;
- sequence association for stem/adaptive controls and nearby measured audio.
- backend mean process CPU and process-lifetime peak RSS (not browser or remote
  generation resources);
- subject/condition search, record selection, questionnaire scoring, selected
  record comparisons and exploratory participant-paired statistics, preserving
  musicality and SongEval metrics. Heart-rate fields are not shown in the UI.

Limits are explicit, never filled with guessed numbers:

- Overlapping evaluated-window ratio is not valid sample-duration coverage.
- Packet-ID loss totals have not been aggregated.
- ACE generation-trigger sequence is not yet exposed, so its trace is incomplete.
- Scheduled ramps are commands, not measurements of every AudioParam trajectory.
- No validated onset, BPM, tonality/chord, LUFS or oversampled true-peak estimator.
- No remote queue/inference timing, calibrated full-session failure rate, automatic
  control-bound/rate violation assessment, hardware latency or ear SPL.
- One-second block-boundary steps are screens, not exhaustive transition detection.
- No automatic conclusion about musical quality, comfort or clinical sleep.
- Observed control fallback proportions exclude gaps and require annotated
  intervention bounds; they are not total lost-EEG coverage.
- Formal comparisons include only reviewed, completed, condition-verified
  hardware sessions; repeated records are first averaged per participant/condition.
- Fixed external audio is not captured, so its audio metrics remain unavailable.
- Baseline/intervention boundaries must describe actual recorded phases; there
  is no automatically scheduled silent baseline. See `EXPERIMENT_ANALYSIS.md`.

Backend JSON and final WAV can be inspected/downloaded from the session-report
section. Full clinical/experimental use still requires completing the above
instrumentation and independent validation.
