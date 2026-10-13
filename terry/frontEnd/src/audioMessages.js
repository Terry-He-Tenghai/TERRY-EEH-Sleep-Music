import { text } from './i18n.js'

// Translate legacy engine messages at render time so a language switch also
// updates errors and statuses already received. Preserve unknown server text.
const messages = {
  '启动 EEG 采集时授权声音；无需手动编辑 MIDI': 'Audio is enabled when EEG acquisition starts; no manual MIDI editing required',
  '声音已授权，等待采集后的新 ready 事件；尚未播放': 'Audio enabled; waiting for a new ready event after acquisition starts',
  '等待新的实时脑电数据；保持已播放音乐与上次参数，暂停新乐句和切换': 'Waiting for fresh EEG; holding existing music and parameters without new phrases or transitions',
  '等待新的实时脑电数据；尚未播放': 'Waiting for fresh EEG; playback has not started',
  '底轨已解码，等待 16 秒乐句边界': 'Background decoded; waiting for a 16-second phrase boundary',
  '用户停止自动声音': 'Automatic audio stopped by user', '用户停止': 'Stopped by user',
  '采集功能已禁用': 'Acquisition disabled', '组件卸载': 'Component unmounted',
  '重新启动采集': 'Restarting acquisition', '页面隐藏': 'Page hidden',
  '页面隐藏，自动播放已停止': 'Page hidden; automatic playback stopped',
  '页面隐藏，无法启用声音': 'Page hidden; audio cannot be enabled',
  '音频上下文中断': 'Audio context interrupted',
  '浏览器不支持 Web Audio': 'Browser does not support Web Audio',
  '浏览器不支持自动播放': 'Browser does not support automatic playback',
  '浏览器未授权声音，请重新启动采集': 'Browser audio permission unavailable; restart acquisition',
  '等待后端许可；已静音': 'Waiting for backend authorization; silent',
  '电极暂时失效：仅保留背景，最多30秒；恢复前不推断新睡眠状态': 'Electrodes temporarily invalid; background only for up to 30 seconds, with no new sleep-state inference',
  '电极持续失效，8秒渐出停止': 'Electrodes remain invalid; fading out over 8 seconds',
  '超过15秒无新计划，8秒渐出停止': 'No new plan for 15 seconds; fading out over 8 seconds',
  '音频调度延迟，已安全停止': 'Audio scheduling delayed; playback stopped',
  'sleep_paused_after_three_n2': 'Three consecutive valid N2 results; 30-second fade to silence',
  '无效的自适应事件类型': 'Invalid adaptive event type', '缺少 LIVE / DEMO 来源': 'Missing LIVE / DEMO source',
  '缺少有效会话标识或序号': 'Missing valid session ID or sequence', '无效事件状态': 'Invalid event status',
  '事件时间戳过期或时钟不同步（需要服务端 Unix 秒时间）': 'Event timestamp stale or clocks unsynchronized (server Unix seconds required)',
  '当前播放器仅支持 60 BPM / 16 拍计划': 'Player requires 60 BPM / 16-beat plans',
  '无效音乐状态': 'Invalid music state', '睡眠状态概率无效': 'Invalid sleep-state probabilities',
  '波形模型分类未确认或质量不合格': 'Waveform classification unconfirmed or quality rejected',
  '保守播放仍需有效电极和新数据': 'Conservative playback still requires valid electrodes and fresh data',
  '保守播放计划超过低增益或稀疏音符限制': 'Conservative plan exceeds gain or note-density limits',
  '降级脑电分类状态无效': 'Invalid fallback EEG classification state',
  '有效电极或信号质量不足，已禁止声音': 'Insufficient valid electrodes or signal quality; audio disabled',
  '没有可用本地底轨；禁止单独启动振荡器': 'No local background available; standalone oscillators disabled',
  'MIDI 计划缺失或过大': 'MIDI plan missing or too large', 'MIDI 音符参数无效': 'Invalid MIDI note parameters',
  'MIDI音符参数无效': 'Invalid MIDI note parameters', '不支持的振荡器音色': 'Unsupported oscillator timbre',
  '无效波形参数': 'Invalid waveform parameters', '无效音色参数': 'Invalid timbre parameters',
  '无效增益配置': 'Invalid gain configuration', '增益必须在 0–1 之间': 'Gain must be between 0 and 1',
  '采集会话已改变，请重新启动采集': 'Acquisition session changed; restart acquisition',
  '忽略启动前的旧事件，请重新启动采集': 'Ignoring an event from before startup; restart acquisition',
  '底轨超过 80 MB 限制': 'Background exceeds the 80 MB limit',
  '浏览器不支持受限音频下载': 'Browser does not support bounded audio downloads',
  '底轨需为 8–900 秒的单声道或双声道音频': 'Background must be mono or stereo, 8–900 seconds long',
  '上传音频含无效采样值': 'Audio contains non-finite samples',
  '编排数据不完整': 'Incomplete arrangement data', '未知音乐状态': 'Unknown music state',
  '本地音频无法读取，请刷新音乐库或检查后端': 'Cannot read local audio; refresh the library or check the backend',
  '预览仅支持80MB以内的音频': 'Preview supports audio up to 80 MB',
  '请先停止当前会话': 'Stop the current session first', '请检查素材和音色参数': 'Check assets and timbre parameters',
  '浏览器不支持录音，请关闭录音选项后重试': 'Recording unsupported; disable recording and retry',
  '浏览器没有可用的录音编码，请关闭录音选项': 'No recording codec available; disable recording',
  '浏览器调度延迟，已停止以避免音符堆积。请保持页面前台后重新开始。': 'Scheduling delayed; stopped to prevent accumulated notes. Keep the page in the foreground and restart.',
  '音乐库读取失败': 'Music library unavailable', '自动生成状态不可用': 'Automatic generation status unavailable',
  '请选择WAV文件': 'Select a WAV file', '上传失败': 'Upload failed',
  '后端尚未加载自动推理接口（404）。请先停止采集，关闭旧后端，再重新运行 start_backend.command；刷新网页后重新开始采集。': 'Inference API unavailable (404). Stop acquisition, restart the backend with start_backend.command, then reload.',
  '自动推理接口格式不匹配，请检查后端版本。': 'Inference API format mismatch; check the backend version',
  '自动推理状态接口超时，请检查后端连接。': 'Inference status request timed out; check the backend connection',
  '后端消息格式无效': 'Invalid backend message format', '无法连接后端 WebSocket': 'Cannot connect to backend WebSocket',
  'WebSocket 已断开，波形不再更新，请重新连接': 'WebSocket disconnected; waveform updates stopped. Reconnect.',
  '请先上传音频，再开始采集': 'Upload audio before starting acquisition',
  '动态音乐演示请选择250Hz': 'Select 250 Hz for the dynamic music demo',
  '启动采集失败': 'Failed to start acquisition', '停止采集失败，请检查后端': 'Failed to stop acquisition; check the backend',
  '会话报告接口不可用': 'Session report API unavailable',
  '提交失败': 'Submission failed', '查询失败': 'Status query failed', '生成失败': 'Generation failed',
  '声部提取请求失败': 'Stem extraction request failed', '声部提取查询失败': 'Stem extraction status query failed',
  '声部提取失败': 'Stem extraction failed', '声部提取等待超时': 'Stem extraction timed out',
}
export function audioMessage(value) {
  if (typeof value !== 'string') return value
  let english = messages[value]
  if (!english) {
    const http = value.match(/^(无法读取自动推理状态|音频下载失败)（HTTP (\d+)）$/)
    const download = value.match(/^本地底轨下载失败 \((\d+)\)$/)
    const plan = value.match(/^编排接口失败（(\d+)），请确认后端已加载音乐实验台接口$/)
    const media = value.match(/^音频播放失败（媒体错误 (.+)），请检查后端音频接口与 SSH 隧道$/)
    const channels = value.match(/^波形通道与当前页面不匹配（后端：(.+)；页面：(.+)）。请停止采集并重启后端，再刷新页面。$/)
    if (http) english = `${http[1] === '音频下载失败' ? 'Audio download failed' : 'Cannot read inference status'} (HTTP ${http[2]})`
    else if (download) english = `Background download failed (${download[1]})`
    else if (plan) english = `Arrangement API failed (${plan[1]}); check backend workbench support`
    else if (media) english = `Audio playback failed (media error ${media[1] === '未知' ? 'unknown' : media[1]}); check the audio API and SSH tunnel`
    else if (channels) english = `Waveform channels do not match this page (backend: ${channels[1] === '未知' ? 'unknown' : channels[1]}; page: ${channels[2]}). Stop acquisition, restart the backend, and reload.`
  }
  return text(value, english ?? value)
}
