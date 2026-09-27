# AISAASGO Suno 异步生成工具

接口依据：项目提供的示例，模型 `suno-v5.5`。2026-09-12 实测只读 `/v1/models` 返回 HTTP 200 且包含该模型。首次生成 POST 未取得任务 ID，原错误处理未保留具体状态；是否受理/计费未知，未自动重试。发现性查询 `/v1/tasks` 返回 404，不能用该路径列出历史任务。真实生成响应、下载和计费仍未验证。用户随后明确授权重提一次，第二次 POST 返回 HTTP 400，未取得任务 ID，未继续重试。具体参数拒绝原因未保留，需核查供应商后台。此工具与旧 `sunoapi.org` 回调客户端独立，不共享接口或密钥名。

## 参考客户端对齐（2026-09-12）

依据用户提供的 `aisaasgo_media.py` 的 Suno 分支更新；运行时不依赖 `__pycache__` 下的文件。

普通模式显式传 `custom_mode=false`、`instrumental=true`，固定模型 suno-v5.4 style/title，允许 negative_tags 和正整数 duration；具体时长范围仍由供应商决定，参考代码没有给出上限，不能保证输出严格等于请求时长。不传 Seed Audio 专用的 sample_rate/format 等字段。

自定义模式示例（执行会提交一项可能计费的任务）：

```bash
.venv/bin/python scripts/generate_suno.py submit \
  --prompt-file music/prompts/warm-pad-01.txt \
  --custom-mode --style "Minimal instrumental ambient, warm pads, beatless" \
  --title "Quiet Pad 01" \
  --negative-tags "vocals, speech, drums, sharp transients"
```

需要请求时长时可在自定义模式加 `--duration 180`；普通模式传入这些专属参数会在发请求前报错，避免静默忽略。鉴权仍读取 `.env`。

请求增加 Accept: application/json，读取超时改为120秒。错误仅提取 JSON error.message/error.code 或 message 并截断至500字符，清除当前密钥、常见 sk 密钥、Bearer 字段和 URL，不打印完整响应。非JSON正文不打印。脱敏不是对任意供应商回显的绝对保证，错误回执仍只保存在被忽略的本地目录。

保留固定API主机、下载域名限制、不跟随重定向、不自动重试POST、不覆盖候选与人工审核；未直接照搬参考脚本的任意地址下载/覆盖行为。新增字段是否解决历史 HTTP400 尚未实测。

## 密钥与费用

聊天中曾出现真实密钥，请在供应商后台轮换。工具只读取环境变量 `AISAASGO_API_KEY`，不把密钥写入源码、命令参数、任务文件或下载请求。工具优先使用当前进程的 `AISAASGO_API_KEY`，并自动从 `backEnd/.env` 补充未设置的变量；不会覆盖已导出的环境变量。请确保 `.env` 未提交 Git，避免在截图或日志中展示其内容。

生成可能计费。每次 `submit` 只发一次 POST，超时也不自动重试，因为供应商可能已经受理并计费。重复生成必须由操作者明确决定。查询用 `fetch`，不要用重复提交来查询进度。

## 使用（macOS 默认 zsh）

在一个终端进入 `terry/backEnd/`，先用隐藏输入设置轮换后的密钥，不要直接把密钥贴入命令历史：

```bash
read -rs 'AISAASGO_API_KEY?输入 API 密钥（隐藏）：'
export AISAASGO_API_KEY
printf '\n'
```

从 `docs/offline_music_suno_prompts.md` 选一条英文提示词及通用约束，保存到一个纯文本文件（例如 `/tmp/terry-prompt.txt`）。不要把整个 Markdown 文档或任何密钥作为提示词。

提交一项任务（会调用生成接口，可能产生费用）：

```bash
.venv/bin/python scripts/generate_suno.py submit --prompt-file /tmp/terry-prompt.txt
```

输出任务 ID，示例 `task-unified-...`。用真实返回值替换下面占位符：

```bash
.venv/bin/python scripts/generate_suno.py fetch TASK_ID --wait-seconds 600
```

`fetch` 默认只查一次；设置等待秒数后，每约 10 秒查询一次，最多允许等待 1800 秒。单次网络请求有独立超时，墙钟总时间可能略超过等待参数。等待结束仍未完成可以再次运行同一条 fetch，不会生成新任务。

用完清除当前 shell 的密钥变量：

```bash
unset AISAASGO_API_KEY
```

## 数据与审核

任务和结果保存在 `backEnd/music/candidates/<task-id>/`：

- `task.json`：必要任务字段与结果 URL，URL 可能带访问签名，按敏感本地记录管理。
- `prompt.txt`：提交提示词。
- `candidate-0.mp3` 等：下载的候选音频。

整个 `backEnd/music/` 已由 `.gitignore` 忽略。下载只允许 HTTPS `img.aisaasgo.org`，不携带 Authorization，不跟随重定向；每个文件上限 100 MiB，先写 `.part` 再替换，拒绝覆盖已有成品。仅接受已知音频扩展名，扩展名不等于有效音频，仍须人工验证编码和全曲听审。若供应商实际返回其他 CDN、扩展名或数据结构，需要先核查再适配，不能随意关闭限制。

部分下载成功后失败：已完成文件会保留；再次 fetch 遇到已有文件会停止以避免覆盖，需先人工核对并移走已保存结果再恢复。当前不支持断点续传、自动重试、批量提交、幂等键或自动任务列表恢复。若 POST 已受理但网络/磁盘失败导致无任务 ID，请在供应商后台查找任务后用 fetch 恢复。

下载不自动生成可播放清单，更不会自动批准。按 `offline_music_library.md` 将曲目以 pending 状态登记到 `backEnd/music/manifest.json`，file 可使用 `candidates/<task-id>/candidate-0.mp3`；人工验证授权、最终音频、审核人和日期后才批准。前端刷新素材库即可读取。

## 失败处理

HTTP 错误会提取有限的脱敏 JSON 错误信息，不输出完整响应或原始 URL；未知状态、任务 ID 不匹配、失败/取消、响应格式不符都会终止，不自动重新生成。状态文件记录最后一次合法任务响应，用同一任务 ID 排查恢复。

真实连通性、供应商条款、额度、输出音频有效性尚需使用轮换密钥进行一次受控验证。单元测试只用模拟响应，不消耗额度。
