<script setup>
import AdaptiveMusicPanel from './components/AdaptiveMusicPanel.vue'
import StemMusicPanel from './components/StemMusicPanel.vue'
import MusicWorkbench from './components/MusicWorkbench.vue'
import AceMusicPanel from './components/AceMusicPanel.vue'
import AutomaticAcePanel from './components/AutomaticAcePanel.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const CHANNELS = ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2']
const CAP_CHANNELS = ['Fp1', 'Fp2', 'C3', 'C4', 'P7', 'P8', 'O1', 'O2', 'F7', 'F8', 'F3', 'F4', 'T7', 'T8', 'P3', 'P4']
const displayChannels = computed(() => mode.value === 'brainflow' ? CAP_CHANNELS : CHANNELS)
const COLORS = ['#27708b', '#a35b25', '#867017', '#7954a3', '#387448', '#376b9f', '#a94264', '#586a7a', '#9d631c', '#247866', '#a94747', '#8159a0', '#507c32', '#a64c78', '#7055a0', '#267b84']
const sampleRate = ref(250), activeSampleRate = ref(250)
const verticalScale = ref(200)
const canvas = ref(null), mode = ref('demo'), ipAddress = ref('192.168.4.1'), gain = ref(24)
const demoProfile = ref('model')
const running = ref(false), connected = ref(false), paused = ref(false), displaySeconds = ref(5), error = ref('')
const waveformError = ref('')
const samplesEmitted = ref(0), lastTimestamp = ref(0), channelEnabled = ref(CHANNELS.map(() => true))
const musicSource = ref('ace'), aceStyle = ref('ambient'), uploadedTrack = ref(null), uploading = ref(false), musicChoiceError = ref('')
const stemTracks = ref([]), stemTrackId = ref('Track00008')
const selectedStemTrack = computed(() => stemTracks.value.find(t => t.id === stemTrackId.value))
async function loadStemChoices() {
  try {
    const response = await fetch(`${apiBase}/api/stem-music`, { cache: 'no-store' })
    if (!response.ok) throw new Error('分轨接口不可用，请重启更新后的后端')
    stemTracks.value = (await response.json()).tracks
  } catch (err) { musicChoiceError.value = err.message }
}
async function uploadMusic(event) {
  const file = event.target.files?.[0]
  if (!file || running.value || startingAcquisition.value) return
  musicChoiceError.value = ''; uploadedTrack.value = null
  if (!file.name.toLowerCase().endsWith('.wav') || file.size > 80000000) { musicChoiceError.value = '请选择不超过80MB的PCM WAV文件'; return }
  uploading.value = true
  try {
    const response = await fetch(`${apiBase}/api/music/uploads`, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: file })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '上传失败')
    uploadedTrack.value = { ...body, displayName: file.name }
  } catch (err) { musicChoiceError.value = err.message }
  finally { uploading.value = false; event.target.value = '' }
}
const startingAcquisition = ref(false)
const adaptivePanel = ref(null), adaptiveEvent = ref(null), adaptiveConnectionError = ref('')
let adaptivePoll = null, adaptiveRequest = null, disposed = false, acquisitionRequestedAt = 0
function acceptAdaptive(packet) {
  if (packet.type !== 'adaptive_music' || (startingAcquisition.value && packet.status === 'stopped')) return
  if (acquisitionRequestedAt && packet.emitted_at_s * 1000 < acquisitionRequestedAt) return
  const previous = adaptiveEvent.value
  if (previous && String(previous.session_id) === String(packet.session_id) && previous.sequence >= packet.sequence) return
  adaptiveConnectionError.value = ''
  adaptiveEvent.value = { ...packet, session_id: String(packet.session_id), eeg_timestamp_s: packet.timestamp_s,
    timestamp_s: packet.emitted_at_s, waveform_parameters: packet.waveform, waveform: 'sine',
    music_state: packet.current_music_state ?? packet.music_state,
    motif_variation: packet.variation ?? packet.motif_variation,
    track: packet.selected_track ? { ...packet.selected_track, audio_url: packet.selected_track.url } : null }
}
async function refreshAdaptiveStatus() {
  if (adaptiveRequest || disposed) return
  const request = new AbortController(); adaptiveRequest = request
  const timeout = setTimeout(() => request.abort(), 5000)
  try {
    const response = await fetch(`${apiBase}/api/adaptive/status`, { signal: request.signal, cache: 'no-store' })
    if (response.status === 404) throw new Error('后端尚未加载自动推理接口（404）。请先停止采集，关闭旧后端，再重新运行 start_backend.command；刷新网页后重新开始采集。')
    if (!response.ok) throw new Error(`无法读取自动推理状态（HTTP ${response.status}）`)
    const packet = await response.json()
    if (packet.type !== 'adaptive_music') throw new Error('自动推理接口格式不匹配，请检查后端版本。')
    if (!disposed) { adaptiveConnectionError.value = ''; acceptAdaptive(packet) }
  } catch (error) {
    if (!disposed) adaptiveConnectionError.value = error.name === 'AbortError' ? '自动推理状态接口超时，请检查后端连接。' : error.message
  } finally { clearTimeout(timeout); if (adaptiveRequest === request) adaptiveRequest = null }
}
const signal = ref(CHANNELS.map(() => [])), ws = ref(null), animationFrame = ref(null)
watch(mode, () => { signal.value = displayChannels.value.map(() => []); channelEnabled.value = displayChannels.value.map(() => true); samplesEmitted.value = 0; lastTimestamp.value = 0; waveformError.value = ''; draw() })
const apiBase = import.meta.env.VITE_API_BASE || ''
const wsBase = import.meta.env.VITE_WS_BASE || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`
const statusText = computed(() => error.value ? '错误' : running.value && mode.value === 'brainflow' ? (connected.value ? '设备采集中' : '正在连接设备') : running.value ? '演示采集中' : '未开始')
const enabledCount = computed(() => channelEnabled.value.filter(Boolean).length)

function appendSamples(packet) {
  if (!channelsMatch(packet.channels) || !Array.isArray(packet.samples_uv) || packet.samples_uv.length !== displayChannels.value.length) {
    waveformError.value = channelMismatchMessage(packet.channels)
    return
  }
  waveformError.value = ''
  activeSampleRate.value = packet.sample_rate_hz
  const maxSamples = Math.round(packet.sample_rate_hz * displaySeconds.value)
  signal.value = signal.value.map((channel, index) => [...channel, ...(packet.samples_uv[index] || [])].slice(-maxSamples))
  samplesEmitted.value += packet.samples_uv[0]?.length || 0
  lastTimestamp.value = packet.timestamp_s + (packet.samples_uv[0]?.length || 0) / packet.sample_rate_hz
  draw()
}
function channelsMatch(channels) { return Array.isArray(channels) && channels.length === displayChannels.value.length && channels.every((name, index) => name === displayChannels.value[index]) }
function channelMismatchMessage(channels) { return `波形通道与当前页面不匹配（后端：${Array.isArray(channels) ? channels.join(', ') : '未知'}；页面：${displayChannels.value.join(', ')}）。请停止采集并重启后端，再刷新页面。` }
function applyStatus(packet) {
  activeSampleRate.value = packet.sample_rate_hz; running.value = packet.streaming; connected.value = packet.connected; error.value = packet.error || ''
  if (typeof packet.samples_emitted === 'number') samplesEmitted.value = packet.samples_emitted
  if (packet.streaming && !channelsMatch(packet.channels)) waveformError.value = channelMismatchMessage(packet.channels)
  else if (!packet.streaming || channelsMatch(packet.channels)) waveformError.value = ''
}
function connectSocket() {
  if (ws.value && ws.value.readyState <= WebSocket.OPEN) return
  const socket = new WebSocket(`${wsBase}/ws/waveform`); ws.value = socket
  socket.onmessage = (event) => {
    try {
      const packet = JSON.parse(event.data)
      if (packet.type === 'adaptive_music') acceptAdaptive(packet)
      if (packet.type === 'samples' && !paused.value) appendSamples(packet)
      if (packet.type === 'status') {
        applyStatus(packet)
        if (!packet.streaming && !startingAcquisition.value) adaptivePanel.value?.stop('acquisition-stopped')
      }
    } catch { error.value = '后端消息格式无效'; adaptivePanel.value?.stop('invalid-stream-message') }
  }
  socket.onerror = () => { error.value = '无法连接后端 WebSocket'; adaptivePanel.value?.stop('websocket-error') }
  socket.onclose = () => { ws.value = null; connected.value = false; error.value = 'WebSocket 已断开，波形不再更新，请重新连接'; adaptivePanel.value?.stop('websocket-disconnected') }
}
async function startAcquisition() {
  if (startingAcquisition.value || uploading.value) return
  if (musicSource.value === 'upload' && !uploadedTrack.value) { musicChoiceError.value = '请先上传音频，再开始采集'; return }
  if (musicSource.value === 'stems' && !selectedStemTrack.value) { musicChoiceError.value = '请先选择可用分轨素材'; return }
  if (mode.value === 'demo' && demoProfile.value === 'showcase' && sampleRate.value !== 250) { error.value = '动态音乐演示请选择250Hz'; return }
  startingAcquisition.value = true
  acquisitionRequestedAt = Date.now()
  adaptiveEvent.value = null
  error.value = ''
  try {
    // Start-click user activation authorizes local audio; no additional MIDI edits.
    adaptivePanel.value?.arm()
    connectSocket(); await nextTick()
    const response = await fetch(`${apiBase}/api/acquisition/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: mode.value, demo_profile: mode.value === 'demo' ? demoProfile.value : 'model', ip_address: ipAddress.value, gain: Number(gain.value), sample_rate_hz: Number(sampleRate.value), music_source: musicSource.value, stem_track_id: musicSource.value === 'stems' ? stemTrackId.value : null, music_style: musicSource.value === 'ace' ? aceStyle.value : 'all', uploaded_track_id: musicSource.value === 'upload' ? uploadedTrack.value.id : null }) })
    const body = await response.json(); if (!response.ok) throw new Error(body.detail || '启动采集失败')
    applyStatus(body); signal.value = displayChannels.value.map(() => []); channelEnabled.value = displayChannels.value.map(() => true); lastTimestamp.value = 0; paused.value = false
    if (!body.streaming) adaptivePanel.value?.stop('acquisition-not-started')
  } catch (err) { error.value = err.message; adaptivePanel.value?.stop('acquisition-start-failed') }
  finally { startingAcquisition.value = false }
}
async function stopAcquisition() {
  adaptivePanel.value?.stop('user-stopped-acquisition')
  try {
    const response = await fetch(`${apiBase}/api/acquisition/stop`, { method: 'POST' })
    if (!response.ok) throw new Error('停止采集失败，请检查后端')
    applyStatus(await response.json())
  } catch (err) { error.value = err.message }
}
function togglePause() { paused.value = !paused.value }
function clearWaveform() { signal.value = displayChannels.value.map(() => []); samplesEmitted.value = 0; lastTimestamp.value = 0; draw() }
function toggleAll(event) { channelEnabled.value = displayChannels.value.map(() => event.target.checked) }
function setDisplaySeconds() { const maxSamples = Math.round(activeSampleRate.value * displaySeconds.value); signal.value = signal.value.map((channel) => channel.slice(-maxSamples)); draw() }
function draw() {
  const element = canvas.value; if (!element) return
  const rect = element.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return
  const ratio = window.devicePixelRatio || 1, width = Math.max(280, rect.width), height = Math.max(450, rect.height)
  if (element.width !== width * ratio || element.height !== height * ratio) { element.width = width * ratio; element.height = height * ratio }
  const context = element.getContext('2d'); context.setTransform(ratio, 0, 0, ratio, 0, 0); context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height)
  const left = 58, right = 20, top = 22, bottom = 30, plotWidth = width - left - right, plotHeight = height - top - bottom, rowHeight = plotHeight / displayChannels.value.length
  context.font = '11px Inter, system-ui, sans-serif'; context.lineWidth = 1
  for (let i = 0; i < displayChannels.value.length; i += 1) { const y = top + rowHeight * i + rowHeight / 2; context.strokeStyle = '#e5eae2'; context.beginPath(); context.moveTo(left, y); context.lineTo(width - right, y); context.stroke(); context.fillStyle = channelEnabled.value[i] ? COLORS[i] : '#526277'; context.fillText(displayChannels.value[i], 12, y + 4) }
  for (let i = 0; i <= 5; i += 1) { const x = left + (plotWidth * i) / 5; context.strokeStyle = '#edf0eb'; context.beginPath(); context.moveTo(x, top); context.lineTo(x, height - bottom); context.stroke(); context.fillStyle = '#71839a'; context.fillText(`${(-displaySeconds.value + displaySeconds.value * i / 5).toFixed(1)}s`, x - 14, height - 8) }
  const centered = signal.value.map(values => { const baseline = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0; return values.map(value => value - baseline) })
  const amplitude = Number(verticalScale.value)
  for (let i = 0; i < displayChannels.value.length; i += 1) { if (!channelEnabled.value[i] || !signal.value[i].length) continue; const values = centered[i], yCenter = top + rowHeight * i + rowHeight / 2; context.strokeStyle = COLORS[i]; context.lineWidth = 1.2; context.beginPath(); values.forEach((value, index) => { const x = left + ((Math.max(0, Math.round(activeSampleRate.value * displaySeconds.value) - values.length) + index) / Math.max(1, Math.round(activeSampleRate.value * displaySeconds.value) - 1)) * plotWidth; const y = yCenter - Math.max(-rowHeight * .42, Math.min(rowHeight * .42, (value / amplitude) * rowHeight * .38)); if (index === 0) context.moveTo(x, y); else context.lineTo(x, y) }); context.stroke() }
}
function resize() { draw() }
onMounted(() => { loadStemChoices(); refreshAdaptiveStatus(); adaptivePoll = setInterval(refreshAdaptiveStatus, 3000); connectSocket(); window.addEventListener('resize', resize); draw(); animationFrame.value = requestAnimationFrame(function loop() { draw(); animationFrame.value = requestAnimationFrame(loop) }) })
onBeforeUnmount(() => { disposed = true; clearInterval(adaptivePoll); adaptiveRequest?.abort(); window.removeEventListener('resize', resize); if (animationFrame.value) cancelAnimationFrame(animationFrame.value); ws.value?.close() })
</script>

<template>
  <div class="site-shell">
  <main id="waveform" class="app-shell">
    <header class="topbar"><div><p class="eyebrow">TERRY / EEG × MUSIC</p><h1>脑电音乐</h1></div><div class="status-pill" :class="{ live: running, danger: error }" role="status"><span class="status-dot" />{{ statusText }}</div></header>
    <section class="panel music-setup" aria-labelledby="music-setup-title">
      <header class="music-setup__header">
        <div><h2 id="music-setup-title">选择音乐</h2></div>
        <span class="music-setup__badge">{{ running || startingAcquisition ? '采集中 · 选择已锁定' : '采集前可更换' }}</span>
      </header>
      <fieldset class="music-setup__fields" :disabled="running || startingAcquisition || uploading" :aria-busy="uploading">
        <legend class="music-setup__sr-only">音乐来源与背景设置</legend>
        <div class="music-setup__field">
          <label for="music-source">音频来源</label>
          <select id="music-source" v-model="musicSource" aria-describedby="music-source-help"><option value="ace">AI · 脑电分类生成</option><option value="upload">上传我的音频</option><option value="stems">BabySlakh 原曲分轨 · 脑电混音</option></select>
          <p id="music-source-help" class="music-setup__help">{{ musicSource === 'ace' ? '有效模型分类与基线就绪后，按状态自动生成并播放。' : musicSource === 'stems' ? '20首原曲分轨混音，不叠加 MIDI。' : '使用上传音频作为固定背景。' }}</p>
        </div>
        <div v-if="musicSource === 'ace'" class="music-setup__field"><label for="ace-style">预设音乐风格</label><select id="ace-style" v-model="aceStyle"><option value="ambient">氛围</option><option value="piano">钢琴</option><option value="nature">自然</option><option value="strings">弦乐</option><option value="electronic">电子</option></select></div>
        <div v-if="musicSource === 'stems'" class="music-setup__field">
          <label for="stem-track">同步分轨曲目</label>
          <select id="stem-track" v-model="stemTrackId"><option v-for="track in stemTracks" :key="track.id" :value="track.id">{{ track.title || track.id }}</option></select>
          <p class="music-setup__help">四声部同步播放 · 未验证助眠效果</p>
        </div>
        <div v-else-if="musicSource === 'upload'" class="music-setup__field">
          <label for="music-upload">上传音频</label>
          <input id="music-upload" type="file" accept=".wav,audio/wav" aria-describedby="music-upload-help" @change="uploadMusic" />
          <p id="music-upload-help" class="music-setup__help">PCM WAV · 8–900 秒 · 单 / 双声道 · 最大 80 MB</p>
        </div>
      </fieldset>
      <div v-if="uploading || (musicSource === 'upload' && uploadedTrack)" class="music-setup__upload-status" role="status" aria-live="polite">
        <template v-if="uploading"><strong>正在上传并校验音频…</strong><span>请等待完成后再开始采集。</span></template>
        <template v-else><strong>已选择：{{ uploadedTrack.displayName }}</strong><span>本次采集保持此背景，MIDI 声部自动变化。</span></template>
      </div>
      <footer class="music-setup__footer">
        <details><summary>音乐使用说明</summary><ul><li>采集中不可更换风格，请先停止采集。</li><li>AI 生成需要有效分类和基线；预设演示不触发生成。远端处理期间保持等待，断流后暂停播放。</li><li>上传音频仅保存在本机，请确认拥有使用权。</li><li>BabySlakh分轨提供20首原曲的四声部同步混音，仅调整声部比例与亮度，不叠加 MIDI，不修改下载素材。</li></ul></details>
      </footer>
      <p v-if="musicChoiceError" class="error-message" role="alert">{{ musicChoiceError }}</p>
    </section>
    <details class="workspace-details panel"><summary>高级工具 · AI 生成调试</summary><AceMusicPanel /></details>
    <section v-if="mode === 'demo'" class="panel demo-setup">
      <label for="demo-profile">演示方式</label>
      <select id="demo-profile" v-model="demoProfile" :disabled="running || startingAcquisition">
        <option value="showcase">动态音乐演示</option>
        <option value="model">模型验证</option>
      </select>
      <strong v-if="demoProfile === 'showcase'" class="demo-label">预设演示 · 非模型预测</strong>
      <span v-else class="music-setup__help">模拟波形 · 真实分类器</span>
      <details class="demo-notes"><summary>演示说明</summary>
        <p v-if="demoProfile === 'showcase'">清醒→N1→N2→清醒，每段24秒、96秒循环。约3秒产生首个计划，无需300秒基线；分轨约3秒渐变，MIDI在16秒乐句边界应用。仅检验音乐控制，不验证分类准确率。</p>
        <p v-else>保留真实模型与基线流程。恒定模拟信号不保证类别变化，不会篡改预测结果。</p>
      </details>
    </section>
    <section class="control-card panel">
      <div class="control-group"><label for="acquisition-mode">数据源</label><select id="acquisition-mode" v-model="mode" :disabled="running"><option value="demo">演示信号</option><option value="brainflow">LK-Mini-EEG16 / BrainFlow</option></select></div>
      <div v-if="mode === 'brainflow'" class="control-group"><label for="device-ip">设备 IP</label><input id="device-ip" v-model="ipAddress" :disabled="running" /></div>
      <div class="control-group"><label for="sample-rate">采样率</label><select id="sample-rate" v-model="sampleRate" :disabled="running"><option v-for="rate in [250,500,1000]" :key="rate" :value="rate">{{ rate }} Hz</option></select></div>
      <div v-if="mode === 'brainflow'" class="control-group"><label for="hardware-gain">硬件增益</label><select id="hardware-gain" v-model="gain" :disabled="running"><option v-for="item in [1,2,4,6,8,12,24]" :key="item" :value="item">×{{ item }}</option></select></div>
      <div class="actions"><button v-if="!running" class="primary" :disabled="startingAcquisition" @click="startAcquisition">{{ startingAcquisition ? '正在启动…' : '开始采集' }}</button><button v-else class="stop" @click="stopAcquisition">停止采集</button></div>
    </section>
    <p class="notice compact-notice">开始采集将启用声音，请先调低设备音量。</p>
    <p v-if="sampleRate !== 250" class="error-message" role="status">自动推理与预设演示需要 250 Hz；请停止采集后切换采样率。</p>
    <p v-if="mode === 'brainflow'" class="notice" role="status">真实设备采集全部 16 路。可由后端显式启用实验性映射（14 路同名、Fz/Cz 插值）进行分类驱动音乐联调；结果未经此帽位验证，不用于睡眠研究结论。</p>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <p v-if="waveformError" class="error-message" role="alert">{{ waveformError }}</p>
    <p v-if="adaptiveConnectionError" class="error-message" role="alert">{{ adaptiveConnectionError }}</p>
    <StemMusicPanel v-if="musicSource === 'stems'" ref="adaptivePanel" :event="adaptiveEvent" :track="selectedStemTrack" />
    <AutomaticAcePanel v-else-if="musicSource === 'ace'" ref="adaptivePanel" :event="adaptiveEvent" />
    <AdaptiveMusicPanel v-else ref="adaptivePanel" :event="adaptiveEvent" />
    <details class="workspace-details panel" @toggle="draw">
      <summary>脑电波形与采集指标 <span>{{ enabledCount }} 通道 · {{ activeSampleRate }} Hz</span></summary>
      <section class="metrics"><div><span>连接</span><strong>{{ connected ? '已连接' : '未连接' }}</strong></div><div><span>采样率</span><strong>{{ activeSampleRate }} Hz</strong></div><div><span>通道</span><strong>{{ enabledCount }} / {{ displayChannels.length }}</strong></div><div><span>累计样本</span><strong>{{ samplesEmitted.toLocaleString() }}</strong></div><div><span>时间</span><strong>{{ lastTimestamp.toFixed(1) }} s</strong></div></section>
      <div class="control-card waveform-controls">
        <div class="control-group"><label for="display-seconds">显示窗口</label><select id="display-seconds" v-model="displaySeconds" @change="setDisplaySeconds"><option :value="3">3 秒</option><option :value="5">5 秒</option><option :value="10">10 秒</option></select></div>
        <div class="control-group"><label for="vertical-scale">幅度范围（±μV）</label><select id="vertical-scale" v-model="verticalScale"><option v-for="scale in [50,100,200,500,1000]" :key="scale" :value="scale">±{{ scale }} μV</option></select></div>
        <div class="actions"><button class="secondary" @click="togglePause">{{ paused ? '继续显示' : '暂停显示' }}</button><button class="secondary" @click="clearWaveform">清空</button></div>
      </div>
      <section class="visual-panel"><div class="panel-heading"><div><h2>{{ displayChannels.length }} 通道波形</h2></div><label class="select-all"><input type="checkbox" :checked="enabledCount === displayChannels.length" @change="toggleAll" /> 全选通道</label></div><div class="canvas-wrap"><canvas ref="canvas" /></div><div class="channel-list"><label v-for="(channel, index) in displayChannels" :key="channel" class="channel-toggle" :style="{ '--channel-color': COLORS[index] }"><input v-model="channelEnabled[index]" type="checkbox" /><span>{{ index + 1 }} {{ channel }}</span></label></div></section>
      <p class="notice">显示波形经过 5–50 Hz 级联及 50 Hz 陷波；显示幅度有限制，不代表信号质量合格。</p>
    </details>
    <details class="workspace-details panel"><summary>采集与播放说明</summary><p>开始采集同时启用音乐计划与本地播放，停止采集同时停止自动音乐。常规自适应模式需满足模型、基线、通道和质量条件；仍有有效电极但条件不足时，可提供明确标记的保守音乐。演示信号不代表真实睡眠状态。</p><p>原始波形支持250/500/1000 Hz，当前模型仅接收250 Hz。真实模式请独占设备连接。研究原型，未验证助眠效果。</p></details>
    <details class="workspace-details panel manual-tools"><summary>高级工具 · MIDI实验台</summary><MusicWorkbench /></details>
  </main>
  </div>
</template>

<style scoped>
.app-shell { max-width: 1120px; padding-top: 24px; }
.topbar { margin-bottom: 20px; }
.topbar h1 { font-size: clamp(24px, 4vw, 32px); }
.music-setup { padding: 20px; }
.music-setup__header { margin-bottom: 16px; }
.music-setup__header h2 { font-size: 20px; }
.music-setup__footer { margin-top: 14px; padding-top: 12px; }
.demo-setup { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 16px 20px; margin: 14px 0; font-size: 13px; }
.demo-label { padding: 6px 10px; border-radius: 6px; background: #fff0ca; color: #755315; font-size: 12px; }
.demo-notes { flex-basis: 100%; }
.demo-notes p, .workspace-details > p { color: #546659; font-size: 13px; line-height: 1.8; }
.control-card { gap: 14px; }
.compact-notice { margin: 12px 0; }
.workspace-details { padding: 16px 20px; margin: 14px 0; }
summary { cursor: pointer; font-size: 13px; color: #375745; }
summary:focus-visible { outline: 2px solid #648967; outline-offset: 5px; }
.workspace-details > summary { font-weight: 600; }
.workspace-details > summary > span { margin-left: 12px; font-weight: 400; color: #70816f; font-size: 12px; }
.workspace-details[open] > summary { margin-bottom: 18px; }
.waveform-controls { padding: 12px 0; }
@media (max-width: 640px) { .workspace-details, .music-setup { padding: 16px; }.workspace-details > summary > span { display: block; margin: 6px 0 0; } }
</style>
