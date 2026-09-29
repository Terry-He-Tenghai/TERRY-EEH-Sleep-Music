#!/bin/bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")" || exit 1
pause_on_exit() { printf '\n按回车键关闭窗口...'; read -r unused; }
trap pause_on_exit EXIT
printf 'Terry EEG 后端启动\n'
UV=(uv)
command -v uv >/dev/null 2>&1 || UV=(python3 -m uv)
# Finder/Conda may select a different Python from the one that installed uv.
"${UV[@]}" --version >/dev/null 2>&1 || UV=(/usr/bin/python3 -m uv)
"${UV[@]}" --version >/dev/null 2>&1 || { printf '未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/\n'; exit 1; }
"${UV[@]}" sync --python 3.12 --extra web --extra hardware --extra waveform || exit 1
printf '\n正在启动服务，成功与否请查看下方 Uvicorn 日志。\n健康检查：http://127.0.0.1:8000/api/health\n按 Ctrl+C 停止。\n'
"${UV[@]}" run --extra web --extra hardware --extra waveform uvicorn app:app --host 127.0.0.1 --port 8000
