# Session evidence implementation

Each new acquisition creates a UUID report in `backEnd/session_reports/`.
Existing sessions cannot be reconstructed retrospectively. Manual stop,
acquisition/inference error and two distinct quality-qualified LIVE N2 windows
end the report. Scripted demonstration N2 never establishes sleep or ends it.
This changes the previous N2 behavior from music-only pause to acquisition end.

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
- successful waveform classification processing time (including spectral summary);
- playback/control logs with sequences and Web Audio times; ACE download/decode;
- final recording and one-second RMS dBFS, sample peak, overload count,
  spectral centroid, high-frequency power ratio and RMS-rise candidates;
- sequence association for stem/adaptive controls and nearby measured audio.

Limits are explicit, never filled with guessed numbers:

- Overlapping evaluated-window ratio is not valid sample-duration coverage.
- Packet-ID loss totals have not been aggregated.
- ACE generation-trigger sequence is not yet exposed, so its trace is incomplete.
- Scheduled ramps are commands, not measurements of every AudioParam trajectory.
- No validated onset, BPM, tonality/chord, LUFS or oversampled true-peak estimator.
- No remote queue/inference timing, calibrated fallback/failure rate, automatic
  control-bound/rate violation assessment, hardware latency or ear SPL.
- One-second block-boundary steps are screens, not exhaustive transition detection.
- No automatic conclusion about musical quality, comfort or clinical sleep.
- No matched fixed/sham/closed-loop experiment comparison statistics yet.

Backend JSON and final WAV can be inspected/downloaded from the session-report
section. Full clinical/experimental use still requires completing the above
instrumentation and independent validation.
