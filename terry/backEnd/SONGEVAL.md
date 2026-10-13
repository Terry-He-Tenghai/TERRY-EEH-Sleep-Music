# SongEval session-level aesthetics

## Deployment

- Upstream: https://github.com/ASLP-lab/SongEval
- Source revision: `848fb2ff3a2a9d64dcb20d46f07238c28abd7add`.
- Server checkout: `/root/autodl-tmp/SongEval`.
- Isolated environment on the new 3090: `/root/autodl-tmp/songeval-venv`, Python 3.12.
- CPU PyTorch / torchaudio 2.7.0, torchvision 0.22.0; MuQ 0.1.0,
  librosa 0.11.0, hydra-core 1.3.2, transformers 4.50.3.
- Encoder: `OpenMuQ/MuQ-large-msd-iter`, pinned revision
  `0562a57814f6f8bbd9fdea0a25921a2fce1a841a`.
- Model/cache downloads: `/root/autodl-tmp/hf-cache`, HF mirror enabled.
- Service: private `127.0.0.1:8002`, CPU with four Torch threads;
  ACE-Step remains on port 8001, using its existing environment and GPU.

Start on the server (check that port 8002 is not already listening first):

```bash
nohup bash /root/autodl-tmp/SongEval/start_songeval.sh \
  > /root/autodl-tmp/SongEval/service.log 2>&1 < /dev/null &
curl http://127.0.0.1:8002/health
```

Local SSH forwarding, separate from ACE-Step's 8001 tunnel:

```bash
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 -L 8002:127.0.0.1:8002 \
  -p 20389 root@connect.nmb2.seetacloud.com
```

Backend default `SONGEVAL_API_URL=http://127.0.0.1:8002`. The service has no
public authentication layer and must remain loopback-bound. Use one backend
worker because evaluation admission and in-progress tracking are process-local.
The service also serializes inference. Startup loads the model before readiness.
Restarting the AutoDL instance requires starting the service and tunnel again.

## Administration workflow

Automatic SongEval is enabled by default for this user-requested deployment;
the acquisition checkbox can disable audio transfer. The browser remembers the preference and records it in each new
session's metadata as `auto_songeval`. When both session termination and final-mix
upload are complete, the backend queues evaluation on a serial background worker.
Silent recordings are left unavailable with a reason, not assigned music scores.
Administration refreshes every five seconds and after evidence upload. Existing
recordings remain manually evaluable; no historical consent is inferred.

Finish a session and save its final-mix WAV, then use Administration / Experiments.
Explicitly authorize sending final-mix audio to the designated server, and request
SongEval for the chosen session. The job runs in the background; administration
refreshes every five seconds while a job is running. Failed or interrupted jobs
may be requested again. Replacing a recording invalidates its previous scores.
Only WAV bytes are transmitted, without participant ID, EEG or questionnaires.
Remote request audio is stored in a temporary directory and deleted after scoring.
The response is retained locally in the session JSON under `songeval`.

Native 1-5 dimensions, preserved independently from subjective 1-7 ratings and
the legacy AI rubric:

| Upstream | Stored score | Interpretation |
| --- | --- | --- |
| Coherence | coherence | Overall coherence |
| Musicality | musicality | Overall musicality |
| Memorability | memorability | Memorability |
| Clarity | structure_clarity | Clarity of song structure |
| Naturalness | vocal_naturalness | Naturalness of vocal breathing and phrasing |

Session detail shows these separately. Engineering descriptive tables and CSV
provide each score, evaluation status, source version, method, coverage and
analyzed duration. Missing/failed scores remain null, never zero. Condition
tables can be filtered by participant and fixed/sham/closed-loop labels. These
are exploratory engineering summaries, not protocol primary outcomes.

## Coverage and interpretation

Audio is converted to mono and resampled to 24 kHz, with MuQ hidden state 6
feeding the pinned SongEval regression checkpoint. CPU evaluation is bounded:

- At most 30 seconds: one complete segment.
- 30-90 seconds: non-overlapping segments up to 30 seconds covering all audio.
- More than 90 seconds: first, middle and last 30 seconds only.

The session score is a duration-weighted mean of segment scores. Segment
boundaries, component scores, checkpoint SHA256, encoder revision, source
revision and timing are saved. **This aggregation is not upstream's full-song
inference.** Scores describe the uploaded recording or sampled excerpts, not
necessarily the whole intervention. Sampling can miss transitions or other
events. Do not combine analyses with different model versions/coverage methods.

SongEval was trained for songs containing vocals and accompaniment. Instrumental
sleep music is outside its validated scope. Vocal naturalness is not transition
naturalness, and scores do not measure relaxation, sleep latency, clinical
benefit, calibrated safety, loudness or human comfort.

## Licensing

At the pinned upstream revision, README advertises CC BY-NC-SA 4.0 whereas
the repository LICENSE contains Apache 2.0. This discrepancy has not been
resolved with the authors; do not assume commercial permission for the weights
or dataset from the code license. Keep this deployment for noncommercial
research pending clarification, and retain upstream attribution. The MuQ
encoder has its own upstream terms that must also be checked before distribution.
