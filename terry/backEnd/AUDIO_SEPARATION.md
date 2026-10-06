# Uploaded Audio Accompaniment Rewrite

The upload-reference path sends the complete original PCM WAV (10–600 seconds) to
the CPU-only Demucs service, then submits the returned accompaniment to the
ACE-Step `cover` task. Text-only generation and fixed-upload playback are
unchanged. Separation errors stop submission; original vocals are never used
as a fallback. Source separation may leave vocal artifacts. Automatic reference
rewrite requests use the original source duration in both demo and live mode.
The installed official cover implementation locks output duration to source
audio: shorter uploads yield shorter covers, not automatic extension. The
multipart submission and separation timeouts are 1800 seconds for the SSH path.

## Official ACE-Step Stem Extraction

`POST /api/ace/extractions` accepts `reference_track_id` and `track`. It submits
the complete uploaded audio (10 to 600 seconds) to the official `acestep-v15-base` model
with `task_type=extract`, 32 inference steps and a track-specific instruction.
Poll and download using the existing `/api/ace/generations/{task_id}` routes.
The upload area provides a stem selector, preview and download.

Official documented tracks are vocals, backing_vocals, drums, bass, guitar,
keyboard, percussion, strings, synth, fx, brass and woodwinds. There is no
documented all-instruments-minus-vocals track. This extraction is a separate
operation, not the accompaniment used by automatic cover. Full accompaniment
still uses Demucs; extracting a vocal stem and subtracting it is not assumed
to produce phase-aligned, faithful accompaniment.

Download the official base model on the server:

```bash
HF_ENDPOINT=https://hf-mirror.com HF_HOME=/root/autodl-tmp/hf-cache .venv/bin/hf download ACE-Step/acestep-v15-base --local-dir /root/autodl-tmp/ACE-Step-1.5/checkpoints/acestep-v15-base
```

Configure `ACESTEP_CONFIG_PATH2=acestep-v15-base` when starting the API so
`model=acestep-v15-base` routes to its handler. Keep turbo as the primary model
for covers; enable CPU offload and serialize inference on limited VRAM.

## Remote Deployment

Copy `remote_audio_separator.py` into `/root/autodl-tmp/ACE-Step-1.5`.
Use the existing ACE-Step virtual environment; Demucs is pinned to 4.0.1:

```bash
cd /root/autodl-tmp/ACE-Step-1.5
UV_CACHE_DIR=/root/autodl-tmp/uv-cache uv pip install --python .venv/bin/python demucs==4.0.1
TORCH_HOME=/root/autodl-tmp/torch-cache .venv/bin/python -c "from demucs.pretrained import get_model; get_model('htdemucs')"
nohup .venv/bin/python -u -m uvicorn remote_audio_separator:app --host 127.0.0.1 --port 8002 --workers 1 > /root/autodl-tmp/separator.log 2>&1 < /dev/null &
```

Check for an existing listener before starting another service. The separator
uses six CPU threads and serializes inference. Its model and accompaniment
cache live in `/root/autodl-tmp/torch-cache` and
`/root/autodl-tmp/accompaniment-cache`. Cache reuse is keyed by model policy and
the exact clipped audio bytes. Cache WAV files persist until manually removed;
they contain user audio, so apply the deployment's retention policy.

Start ACE-Step separately with CPU offload enabled for uploaded-audio workloads:

```bash
ACESTEP_NO_INIT=false ACESTEP_INIT_LLM=true ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B ACESTEP_LM_BACKEND=pt ACESTEP_OFFLOAD_TO_CPU=true ACESTEP_OFFLOAD_DIT_TO_CPU=true ACESTEP_LM_OFFLOAD_TO_CPU=true nohup .venv/bin/python -u -m uvicorn acestep.api_server:app --host 127.0.0.1 --port 8001 --workers 1 >> server-20261005.log 2>&1 < /dev/null &
```

## Local Tunnel

Both services bind remote loopback only. For a new tunnel after restarting,
ensure local ports are free, then forward both ports:

```bash
ssh -f -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8001:127.0.0.1:8001 -L 127.0.0.1:8002:127.0.0.1:8002 -N -p 36212 root@connect.nmb2.seetacloud.com
```

The current deployment has separate background tunnels for these ports.
Local backend defaults are `ACE_STEP_URL=http://127.0.0.1:8001` and
`AUDIO_SEPARATOR_URL=http://127.0.0.1:8002`. Restart the local backend after code
changes. Check `/health` on each port and `/api/ace/health` on backend port 8000.
The separator first request loads its cached model; the local proxy allows
1800 seconds for separation. Automatic acquisition performs this work on its
music worker, outside the EEG acquisition thread.
