#!/bin/bash
# Finder does not necessarily inherit an interactive terminal's PATH.
export PATH="$HOME/Library/pnpm:$HOME/.local/share/pnpm:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")" || exit 1
pause_on_exit() { printf '\n按回车键关闭窗口...'; read -r unused; }
trap pause_on_exit EXIT
printf 'Terry EEG 前端启动（Vue + pnpm）\n'
if ! command -v node >/dev/null 2>&1 || ! command -v pnpm >/dev/null 2>&1; then
  # Support an existing nvm installation without installing anything globally.
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    . "$NVM_DIR/nvm.sh"
  fi
fi
command -v node >/dev/null 2>&1 || { printf '未找到 Node.js，请先安装 Node.js 20.19+ 或 22.12+。\n'; exit 1; }
command -v pnpm >/dev/null 2>&1 || { printf '未找到 pnpm，请先安装 pnpm 并确保其位于 PATH 中。\n'; exit 1; }
if /usr/sbin/lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  printf '端口5173已被占用。请关闭旧前端后重试；不会自动停止已有进程。\n'
  exit 1
fi
pnpm install --frozen-lockfile || exit 1
printf '\n正在启动前端，请查看 Vite 日志确认成功。\n页面：http://127.0.0.1:5173\n后端首次安装可能需要等待，暂时连接失败时请等后端启动后刷新。\n按 Ctrl+C 停止前端。\n'
pnpm dev --host 127.0.0.1 --port 5173 --strictPort --open
