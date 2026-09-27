#!/bin/bash
# Double-click in macOS Finder. Each service owns a separate Terminal session.
ROOT="$(cd "$(dirname "$0")" && pwd)" || exit 1
fail() { printf '\n%s\n按回车键关闭窗口...' "$1"; read -r unused; exit 1; }
[ "$(uname -s)" = Darwin ] || fail '此双击启动脚本仅适用于macOS。'
[ -f "$ROOT/backEnd/start_backend.command" ] || fail '缺少后端启动脚本。请保持项目目录完整。'
[ -f "$ROOT/frontEnd/start_frontend.command" ] || fail '缺少前端启动脚本。请保持项目目录完整。'
for port in 8000 5173; do
  if /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "端口 $port 已被占用。请先在旧服务窗口按 Ctrl+C 停止，再双击本脚本。不会自动终止已有服务。"
  fi
done
printf '正在分别打开后端和前端终端窗口...\n'
/usr/bin/osascript - "$ROOT/backEnd/start_backend.command" "$ROOT/frontEnd/start_frontend.command" <<'APPLESCRIPT'
on run argv
    tell application "Terminal"
        activate
        do script ("/bin/bash " & quoted form of (item 1 of argv))
        do script ("/bin/bash " & quoted form of (item 2 of argv))
    end tell
end run
APPLESCRIPT
[ "$?" -eq 0 ] || fail '无法打开服务终端。若macOS询问自动化权限，请允许 Terminal 控制 Terminal，然后重试。若已打开部分服务窗口，请先停止它们。'
printf '\n已发送启动命令，是否启动成功请以两个服务窗口日志为准。\n前端启动后会打开浏览器：http://127.0.0.1:5173\n停止整个系统：分别在前端、后端窗口按 Ctrl+C。\n本窗口可以关闭；关闭本窗口不会停止服务。\n'
