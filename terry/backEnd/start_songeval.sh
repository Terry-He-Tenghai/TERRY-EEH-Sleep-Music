#!/usr/bin/env bash
set -euo pipefail
cd /root/autodl-tmp/SongEval
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/root/autodl-tmp/hf-cache
export HF_HUB_DISABLE_XET=1
export OMP_NUM_THREADS=4
exec "${SONGEVAL_PYTHON:-/root/autodl-tmp/songeval-venv/bin/python}" -m uvicorn songeval_server:app --host 127.0.0.1 --port 8002
