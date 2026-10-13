# Session music evaluation

Final-mix uploads automatically produce blockwise digital audio metrics and a
separate `ai_music_evaluation` report. AI results are exploratory, not participant
ratings. Missing audio and unavailable models produce null scores, not zeros.
Legacy reports are not rewritten; CSV/UI show their evaluation as unavailable.

No audio listening model is bundled. To enable an installed, trusted local model,
set `MUSIC_AUDIO_EVALUATOR_COMMAND` before starting the backend, e.g.
`/absolute/path/to/evaluator --output-json`. The backend executes this without a
shell, appending the uploaded WAV path. The adapter must actually analyze that
audio and emit only a JSON object on stdout:

```json
{
  "audio_analyzed": true,
  "model": "your-audio-model",
  "model_version": "pinned-version",
  "method": "fixed listening rubric, sampling policy and aggregation version",
  "scores": {
    "pleasantness": 4,
    "coherence": 4,
    "transition_naturalness": 4
  }
}
```

Numbers above illustrate the schema, not computed results. Each score must be
finite and between 1 and 7. Set a reproducible rubric and validate estimates
against blinded human ratings before scientific interpretation. The adapter has
a 120-second timeout; invalid results and execution failures are saved as failed
evaluations with null scores. Do not send recordings to an external service
without appropriate participant consent and authorization.

RMS is not LUFS; centroid is a signal descriptor, not an artistic-quality score.
Recording/session duration ratio does not establish temporal coverage. Existing
browser memory limits still apply; only uploaded audio is evaluated. Playback
error logs do not reliably distinguish intentional silence from dropout.
