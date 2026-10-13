<script setup>
import { audioMessage } from './audioMessages.js'
import WaveformQuality from './components/WaveformQuality.vue'
import { CAP_CHANNELS, MODEL_OPTIONS, plotChannelIndices, qualityChannels } from './audio/modelChannels.js'
import AdaptiveMusicPanel from './components/AdaptiveMusicPanel.vue'
import MusicWorkbench from './components/MusicWorkbench.vue'
import AceMusicPanel from './components/AceMusicPanel.vue'
import HarmonyControls from './components/HarmonyControls.vue'
import GenreControl from './components/GenreControl.vue'
import AutomaticAcePanel from './components/AutomaticAcePanel.vue'
import AceStemPanel from './components/AceStemPanel.vue'
import SessionReportPanel from './components/SessionReportPanel.vue'
import ExperimentAdmin from './components/ExperimentAdmin.vue'
import AceServerPanel from './components/AceServerPanel.vue'
import { text as t, language, setLanguage } from './i18n.js'
const page = ref('acquisition')
import { beginEvidence, bindEvidence, finishEvidence, logEvidence } from './audio/sessionEvidence.js'
const telemetryLog = logEvidence
import { liveClassification as classifyLive, waveformStatus, waveformCollection } from './audio/liveClassification.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const CHANNELS = ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2']
const displayChannels = computed(() => mode.value === 'brainflow' ? CAP_CHANNELS : CHANNELS)
const COLORS = ['#27708b', '#a35b25', '#867017', '#7954a3', '#387448', '#376b9f', '#a94264', '#586a7a', '#9d631c', '#247866', '#a94747', '#8159a0', '#507c32', '#a64c78', '#7055a0', '#267b84']
const sampleRate = ref(250), activeSampleRate = ref(250)
const verticalScale = ref(200)
const saveRawData = ref(true), rawRecording = ref(null)
function songPreference() {
  try { return localStorage.getItem('terry-auto-songeval') !== 'false' } catch { return true }
}
const autoSongEval = ref(songPreference())
function saveSongPreference() {
  try { localStorage.setItem('terry-auto-songeval', String(autoSongEval.value)) } catch { /* Storage may be unavailable. */ }
}
const canvas = ref(null), mode = ref('demo'), ipAddress = ref('192.168.4.1'), gain = ref(24)
const demoProfile = ref('showcase')
const classificationChannels = ref(16)
const experimentParticipant = ref(''), experimentCondition = ref('closed_loop'), experimentVisit = ref(1)
const participantDialog = ref(null), participantDraft = ref(''), knownParticipants = ref([])
const isFixed = computed(() => experimentCondition.value === 'fixed')
const isSham = computed(() => experimentCondition.value === 'sham')
const measurementEvent = ref(null)
const eegEvent = computed(() => isSham.value ? measurementEvent.value : adaptiveEvent.value)
async function editParticipant() {
  participantDraft.value = experimentParticipant.value
  participantDialog.value.showModal()
  try {
    const response = await fetch(`${apiBase}/api/session-reports/experiments/summary`)
    if (response.ok) knownParticipants.value = [...new Set((await response.json()).rows.map(r => r.participant).filter(Boolean))]
  } catch { /* Existing name remains editable offline. */ }
}
function saveParticipant() {
  experimentParticipant.value = participantDraft.value.trim().normalize('NFC')
  participantDialog.value.close()
}
const showAllChannels = ref(false)
const plotIndices = computed(() => plotChannelIndices(displayChannels.value, classificationChannels.value, showAllChannels.value, mode.value === 'brainflow'))
const plottedChannels = computed(() => plotIndices.value.map(index => ({
  name: mode.value === 'brainflow' && [2, 4, 6].includes(Number(classificationChannels.value)) && index === 2
    ? 'Fp2 (CH3)' : displayChannels.value[index], index,
})))
const running = ref(false), connected = ref(false), paused = ref(false), displaySeconds = ref(5), error = ref('')
const waveformError = ref('')
const samplesEmitted = ref(0), lastTimestamp = ref(0), channelEnabled = ref(CHANNELS.map(() => true))
const musicSource = ref('ace'), aceStyle = ref('ambient'), uploadedTrack = ref(null), uploading = ref(false), musicChoiceError = ref('')
const aceUseReference = ref(false)
const aceHarmonyMode = ref('major'), aceChordProgression = ref('gentle')
const aceGenre = ref('')
async function uploadMusic(event) {
  const file = event.target.files?.[0]
  if (!file || running.value || startingAcquisition.value) return
  musicChoiceError.value = ''; uploadedTrack.value = null
  if (!file.name.toLowerCase().endsWith('.wav')) { musicChoiceError.value = '请选择WAV文件'; return }
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
  if (packet.measurement) measurementEvent.value = packet.measurement
  const previous = adaptiveEvent.value
  if (previous && String(previous.session_id) === String(packet.session_id) && previous.sequence >= packet.sequence) return
  adaptiveConnectionError.value = ''
  if (packet.report_id) bindEvidence(packet.report_id)
  telemetryLog('eeg-window', { sequence: packet.sequence, eeg_timestamp_s: packet.timestamp_s,
    server_emitted_at_s: packet.emitted_at_s, classification_confirmed: packet.classification_confirmed })
  if (['stopped', 'error'].includes(packet.status)) finishEvidence(packet.reason || packet.status)
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
const statusText = computed(() => error.value ? t('错误', 'Error') : running.value && mode.value === 'brainflow' ? (connected.value ? t('设备采集中', 'Device recording') : t('正在连接设备', 'Connecting')) : running.value ? t('演示采集中', 'Demo recording') : t('未开始', 'Not started'))
const enabledCount = computed(() => plotIndices.value.filter(index => channelEnabled.value[index]).length)
watch([classificationChannels, showAllChannels], draw)
const classificationClock = ref(Date.now())
let classificationTimer = null
const liveClassification = computed(() => classifyLive(eegEvent.value, running.value, classificationClock.value))
const liveModelStatus = computed(() => waveformStatus(eegEvent.value, classificationClock.value))

function appendSamples(packet) {
  rawRecording.value = packet.recording || null
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
  rawRecording.value = packet.recording || null
  if (packet.report_id) bindEvidence(packet.report_id)
  if (packet.streaming && packet.experiment) {
    experimentParticipant.value = packet.experiment.participant
    experimentCondition.value = packet.experiment.condition
    experimentVisit.value = packet.experiment.visit || 1
    mode.value = packet.mode
  }
  if (running.value && !packet.streaming && !startingAcquisition.value) finishEvidence(packet.error ? 'acquisition_error' : 'backend_ended')
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
      if (packet.type === 'eeg_measurement') measurementEvent.value = packet
      if (packet.type === 'samples' && !paused.value) appendSamples(packet)
      if (packet.type === 'status') {
        applyStatus(packet)
        if (!packet.streaming && !startingAcquisition.value) adaptivePanel.value?.stop('acquisition-stopped')
      }
    } catch { error.value = '后端消息格式无效'; adaptivePanel.value?.stop('invalid-stream-message') }
  }
  socket.onerror = () => { error.value = '无法连接后端 WebSocket'; telemetryLog('transport-error'); if (mode.value !== 'brainflow') { finishEvidence('websocket_error'); adaptivePanel.value?.stop('websocket-error') } }
  socket.onclose = () => { ws.value = null; connected.value = false; error.value = 'WebSocket 已断开，波形不再更新，请重新连接'; telemetryLog('transport-disconnected'); if (mode.value !== 'brainflow') { finishEvidence('websocket_disconnected'); adaptivePanel.value?.stop('websocket-disconnected') } }
}
async function startAcquisition() {
  if (startingAcquisition.value || uploading.value) return
  if (!experimentParticipant.value.trim()) { error.value = t('请先输入受试者姓名或编号', 'Enter a participant name or ID first'); editParticipant(); return }
  if (!isFixed.value && (musicSource.value === 'upload' || (musicSource.value === 'ace' && aceUseReference.value)) && !uploadedTrack.value) { musicChoiceError.value = '请先上传音频，再开始采集'; return }
  if (!isFixed.value && !isSham.value && mode.value === 'demo' && demoProfile.value === 'showcase' && sampleRate.value !== 250) { error.value = '动态音乐演示请选择250Hz'; return }
  startingAcquisition.value = true
  acquisitionRequestedAt = Date.now()
  beginEvidence({ mode: mode.value, demo_profile: demoProfile.value, music_source: isFixed.value ? 'external' : musicSource.value, condition: experimentCondition.value })
  adaptiveEvent.value = null
  measurementEvent.value = null
  error.value = ''
  try {
    if (saveRawData.value) {
      const check = await fetch(`${apiBase}/api/acquisition/recording-info`, { cache: 'no-store' })
      if (!check.ok || (await check.json()).raw_recording_version !== 1) throw new Error(t('当前后端尚未加载原始数据保存功能，请结束采集后重启后端', 'Backend raw recording update not loaded; restart after acquisition ends'))
    }
    if (experimentParticipant.value) {
      const check = await fetch(`${apiBase}/api/session-reports/experiments/summary`, {cache:'no-store'})
      if (!check.ok || (await check.json()).experiment_execution_version !== 1) throw new Error(t('当前后端尚未加载三模式执行功能，请结束采集后重启后端', 'Backend experiment execution update not loaded; restart after acquisition ends'))
    }
    // Start-click user activation authorizes local audio; no additional MIDI edits.
    if (!isFixed.value) adaptivePanel.value?.arm()
    connectSocket(); await nextTick()
    const response = await fetch(`${apiBase}/api/acquisition/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auto_songeval: !isFixed.value && autoSongEval.value, save_raw_data: true, experiment: {participant:experimentParticipant.value,condition:experimentCondition.value,visit:experimentVisit.value}, experiment_duration_s:2700, mode: mode.value, demo_profile: mode.value === 'demo' && !isFixed.value && !isSham.value ? demoProfile.value : 'model', classification_channels: classificationChannels.value, ip_address: ipAddress.value, gain: Number(gain.value), sample_rate_hz: Number(sampleRate.value), music_source: isFixed.value ? 'external' : musicSource.value, music_style: musicSource.value === 'ace' ? aceStyle.value : 'all', music_genre: musicSource.value === 'ace' ? aceGenre.value || null : null, harmony_mode: aceHarmonyMode.value, chord_progression: aceChordProgression.value, uploaded_track_id: !isFixed.value && musicSource.value === 'upload' ? uploadedTrack.value.id : null, reference_track_id: !isFixed.value && musicSource.value === 'ace' && aceUseReference.value ? uploadedTrack.value.id : null }) })
    const body = await response.json(); if (!response.ok) throw new Error(body.detail || '启动采集失败')
    applyStatus(body); signal.value = displayChannels.value.map(() => []); channelEnabled.value = displayChannels.value.map(() => true); lastTimestamp.value = 0; paused.value = false
    if (!body.streaming) adaptivePanel.value?.stop('acquisition-not-started')
  } catch (err) { error.value = err.message; await finishEvidence('acquisition_start_failed'); adaptivePanel.value?.stop('acquisition-start-failed') }
  finally { startingAcquisition.value = false }
}
async function stopAcquisition() {
  const saving = finishEvidence('manual_stop')
  adaptivePanel.value?.stop('user-stopped-acquisition')
  try {
    const response = await fetch(`${apiBase}/api/acquisition/stop`, { method: 'POST' })
    if (!response.ok) throw new Error('停止采集失败，请检查后端')
    applyStatus(await response.json())
    window.dispatchEvent(new CustomEvent('session-report-ready'))
    await saving
  } catch (err) { error.value = err.message }
}
function togglePause() { paused.value = !paused.value }
function clearWaveform() { signal.value = displayChannels.value.map(() => []); samplesEmitted.value = 0; lastTimestamp.value = 0; draw() }
function toggleAll(event) { for (const index of plotIndices.value) channelEnabled.value[index] = event.target.checked }
function setDisplaySeconds() { const maxSamples = Math.round(activeSampleRate.value * displaySeconds.value); signal.value = signal.value.map((channel) => channel.slice(-maxSamples)); draw() }
function draw() {
  const element = canvas.value; if (!element) return
  const rect = element.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return
  const ratio = window.devicePixelRatio || 1, width = Math.max(280, rect.width), height = Math.max(450, rect.height)
  if (element.width !== width * ratio || element.height !== height * ratio) { element.width = width * ratio; element.height = height * ratio }
  const context = element.getContext('2d'); context.setTransform(ratio, 0, 0, ratio, 0, 0); context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height)
  const left = 58, right = 20, top = 22, bottom = 30, plotWidth = width - left - right, plotHeight = height - top - bottom, rowHeight = plotHeight / Math.max(1, plotIndices.value.length)
  context.font = '11px Inter, system-ui, sans-serif'; context.lineWidth = 1
  for (const [row, i] of plotIndices.value.entries()) { const y = top + rowHeight * row + rowHeight / 2; context.strokeStyle = '#e5eae2'; context.beginPath(); context.moveTo(left, y); context.lineTo(width - right, y); context.stroke(); context.fillStyle = channelEnabled.value[i] ? COLORS[i] : '#526277'; context.fillText(plottedChannels.value[row].name, 12, y + 4) }
  for (let i = 0; i <= 5; i += 1) { const x = left + (plotWidth * i) / 5; context.strokeStyle = '#edf0eb'; context.beginPath(); context.moveTo(x, top); context.lineTo(x, height - bottom); context.stroke(); context.fillStyle = '#71839a'; context.fillText(`${(-displaySeconds.value + displaySeconds.value * i / 5).toFixed(1)}s`, x - 14, height - 8) }
  const centered = signal.value.map(values => { const baseline = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0; return values.map(value => value - baseline) })
  const amplitude = Number(verticalScale.value)
  for (const [row, i] of plotIndices.value.entries()) { if (!channelEnabled.value[i] || !signal.value[i].length) continue; const values = centered[i], yCenter = top + rowHeight * row + rowHeight / 2; context.strokeStyle = COLORS[i]; context.lineWidth = 1.2; context.beginPath(); values.forEach((value, index) => { const x = left + ((Math.max(0, Math.round(activeSampleRate.value * displaySeconds.value) - values.length) + index) / Math.max(1, Math.round(activeSampleRate.value * displaySeconds.value) - 1)) * plotWidth; const y = yCenter - Math.max(-rowHeight * .42, Math.min(rowHeight * .42, (value / amplitude) * rowHeight * .38)); if (index === 0) context.moveTo(x, y); else context.lineTo(x, y) }); context.stroke() }
}
function resize() { draw() }
onMounted(() => { refreshAdaptiveStatus(); adaptivePoll = setInterval(refreshAdaptiveStatus, 3000); classificationTimer = setInterval(() => { classificationClock.value = Date.now() }, 1000); connectSocket(); window.addEventListener('resize', resize); draw(); animationFrame.value = requestAnimationFrame(function loop() { draw(); animationFrame.value = requestAnimationFrame(loop) }) })
onBeforeUnmount(() => { disposed = true; clearInterval(adaptivePoll); clearInterval(classificationTimer); adaptiveRequest?.abort(); window.removeEventListener('resize', resize); if (animationFrame.value) cancelAnimationFrame(animationFrame.value); ws.value?.close() })
</script>

<template>
  <div class="site-shell">
  <main id="waveform" class="app-shell">
    <header class="topbar"><div><p class="eyebrow">TERRY / EEG × MUSIC</p><h1>{{ t('脑电音乐', 'EEG Music') }}</h1></div><div class="header-tools"><div class="status-pill" :class="{ live: running, danger: error }" role="status"><span class="status-dot" />{{ statusText }}</div><select :value="language" aria-label="Language / 语言" @change="setLanguage($event.target.value)"><option value="zh">中文</option><option value="en">English</option></select></div></header>
    <nav class="page-tabs" aria-label="Workspace">
      <button :aria-pressed="page === 'acquisition'" @click="page='acquisition'; nextTick(draw)">{{ t('采集与音乐', 'Acquisition & Music') }}</button>
      <button :aria-pressed="page === 'admin'" @click="page='admin'">{{ t('后台管理 · 实验分析', 'Administration · Experiments') }}</button>
      <button :aria-pressed="page === 'server'" @click="page='server'">{{ t('服务器启动', 'Server') }}</button>
    </nav>
    <section v-show="page === 'admin'"><ExperimentAdmin v-if="page === 'admin'" /><SessionReportPanel /></section>
    <section v-show="page === 'server'"><AceServerPanel v-if="page === 'server'" /></section>
    <div v-show="page === 'acquisition'">
    <fieldset :disabled="running || startingAcquisition" class="experiment-identity"><legend>{{ t('实验记录身份', 'Experiment Record Identity') }}</legend>
      <button type="button" class="participant-button" @click="editParticipant">{{ experimentParticipant || t('输入受试者姓名', 'Enter participant name') }}</button>
      <div class="experiment-modes" role="group" :aria-label="t('实验模式', 'Experiment mode')">
        <label v-for="[key,zh,en] in [['fixed','A · 固定音乐','A · Fixed music'],['sham','B · 伪闭环','B · Sham loop'],['closed_loop','C · 真闭环','C · Closed loop']]" :key="key" :class="{active:experimentCondition===key}"><input v-model="experimentCondition" type="radio" name="experiment-condition" :value="key" />{{ t(zh,en) }}</label>
      </div>
      <label>{{ t('访问序号', 'Visit') }} <select v-model.number="experimentVisit"><option v-for="i in 3" :key="i" :value="i">{{ i }}</option></select></label>
      <span class="experiment-duration">45 {{ t('分钟', 'minutes') }}</span>
    </fieldset>
    <dialog ref="participantDialog" class="participant-dialog"><form @submit.prevent="saveParticipant"><h2>{{ t('受试者', 'Participant') }}</h2><label>{{ t('姓名或编号', 'Name or ID') }}<input v-model="participantDraft" list="participant-names" maxlength="64" required autofocus /><datalist id="participant-names"><option v-for="name in knownParticipants" :key="name" :value="name" /></datalist></label><div><button type="submit">{{ t('确认', 'Confirm') }}</button><button type="button" @click="participantDialog.close()">{{ t('取消', 'Cancel') }}</button></div></form></dialog>
    <p v-if="isFixed" class="condition-status" role="status">{{ t('A · 外部设备播放音乐 · 本机仅记录 EEG', 'A · External music playback · EEG recording only') }}</p>
    <p v-if="isSham" class="condition-status" role="status">{{ t('B · 预设演示信号控制音乐 · EEG 独立记录', 'B · Scripted music control · EEG recorded independently') }}</p>
    <section v-if="!isFixed" class="panel music-setup" aria-labelledby="music-setup-title">
      <header class="music-setup__header">
        <div><h2 id="music-setup-title">{{ t('选择音乐', 'Music Selection') }}</h2></div>
        <span class="music-setup__badge">{{ running || startingAcquisition ? t('采集中 · 选择已锁定', 'Recording · selection locked') : t('采集前可更换', 'Change before recording') }}</span>
      </header>
      <fieldset class="music-setup__fields" :disabled="running || startingAcquisition || uploading" :aria-busy="uploading">
        <legend class="music-setup__sr-only">{{ t('音乐来源与背景设置', 'Music source and background settings') }}</legend>
        <div class="music-setup__field">
          <label for="music-source">{{ t('音频来源', 'Audio Source') }}</label>
          <select id="music-source" v-model="musicSource" aria-describedby="music-source-help"><option value="ace">{{ t('AI · 脑电分类生成', 'AI · EEG-driven generation') }}</option><option value="upload">{{ t('上传我的音频', 'Upload audio') }}</option></select>
          <p id="music-source-help" class="music-setup__help">{{ musicSource === 'ace' ? (mode === 'brainflow' ? t('先收集40秒原始波形，每6秒推理；首个质量合格且分数达标的分类即可触发生成。', 'Collect 40 seconds, infer every 6 seconds; the first qualified classification triggers generation.') : demoProfile === 'showcase' ? t('演示启动后按预设阶段自动生成；上传音频改写可用作生成素材，无需真实设备。', 'Preset demo stages trigger generation or uploaded-audio rewriting without a real device.') : t('模型验证需等待模拟信号达到分类要求。', 'Model validation requires qualified simulated-signal classification.')) : t('使用上传音频作为固定背景。', 'Uploaded audio provides the fixed background.') }}</p>
        </div>
        <div v-if="musicSource === 'ace'" class="music-setup__field"><label for="ace-style">{{ t('预设音乐风格', 'Music Style') }}</label><select id="ace-style" v-model="aceStyle"><option value="ambient">{{ t('氛围', 'Ambient') }}</option><option value="piano">{{ t('钢琴', 'Piano') }}</option><option value="nature">{{ t('自然', 'Nature') }}</option><option value="strings">{{ t('弦乐', 'Strings') }}</option><option value="electronic">{{ t('电子', 'Electronic') }}</option></select></div>
        <HarmonyControls v-if="musicSource === 'ace' && !aceUseReference" v-model:mode="aceHarmonyMode" v-model:progression="aceChordProgression" :disabled="running || startingAcquisition" />
        <GenreControl v-if="musicSource === 'ace'" v-model="aceGenre" :disabled="running || startingAcquisition" />
        <div v-if="musicSource === 'ace'" class="music-setup__field">
          <label for="ace-use-reference"><input id="ace-use-reference" v-model="aceUseReference" type="checkbox" /> {{ t('伴奏分离后改写', 'Separate accompaniment and rewrite') }}</label>
          <p class="music-setup__help">{{ t('将原音频交给 ACE-Step 改写为所选助眠风格，而非直接播放原曲。', 'ACE-Step rewrites the original audio in the selected style.') }}</p>
        </div>
        <div v-if="musicSource === 'upload' || (musicSource === 'ace' && aceUseReference)" class="music-setup__field">
          <label for="music-upload">{{ musicSource === 'ace' ? t('改写原音频', 'Source Audio for Rewriting') : t('上传音频', 'Upload Audio') }}</label>
          <input id="music-upload" type="file" accept=".wav,audio/wav" aria-describedby="music-upload-help" @change="uploadMusic" />
          <p id="music-upload-help" class="music-setup__help">WAV · {{ musicSource === 'ace' ? t('改写 10–600 秒', 'Rewrite 10–600 s') : t('最长 900 秒', 'Up to 900 s') }}</p>
        </div>
      </fieldset>
      <div v-if="uploading || ((musicSource === 'upload' || (musicSource === 'ace' && aceUseReference)) && uploadedTrack)" class="music-setup__upload-status" role="status" aria-live="polite">
        <template v-if="uploading"><strong>{{ t('正在上传并校验音频…', 'Uploading and validating…') }}</strong><span>{{ t('请等待完成后再开始采集。', 'Wait for completion before recording.') }}</span></template>
        <template v-else><strong>{{ t('已选择', 'Selected') }}: {{ uploadedTrack.displayName }}</strong><span>{{ musicSource === 'ace' ? t('完整音频发送至远端分离伴奏，再由 ACE-Step 按原始长度改写。', 'Full audio is sent to the remote separator and rewritten at its original length.') : t('本次采集保持此背景，MIDI 声部自动变化。', 'Background stays fixed while MIDI parts adapt.') }}</span></template>
      </div>
      <AceStemPanel v-if="musicSource === 'ace' && aceUseReference && uploadedTrack" :track-id="uploadedTrack.id" :disabled="running" />
      <footer class="music-setup__footer">
        <details><summary>{{ t('音乐使用说明', 'Music Notes') }}</summary><ul><li>{{ t('采集中不可更换风格，请先停止采集。', 'Stop recording before changing style.') }}</li><li>{{ t('动态演示按预设阶段触发 AI 生成，不代表脑电分类；真实设备仍需有效模型分类。远端处理期间保持等待，断流后暂停分类驱动更新，已开始的音乐继续播放。', 'Scripted stages trigger demo generation, not EEG classification. Live input requires valid model results. Existing music continues during remote processing or data loss, without classification-driven updates.') }}</li><li>{{ t('固定背景音频保存在本机；开启 AI 音频改写后，会将完整原音频发送至远端分离伴奏，再由 ACE-Step 按原始长度改写，支持10–600秒。请确认拥有使用权。', 'Fixed background audio stays local. AI rewriting sends the full audio to a remote separator, then ACE-Step rewrites its original duration (10–600 seconds). Confirm you have permission to use it.') }}</li></ul></details>
      </footer>
      <p v-if="musicChoiceError" class="error-message" role="alert">{{ audioMessage(musicChoiceError) }}</p>
    </section>
    <details v-if="!isFixed" class="workspace-details panel"><summary>{{ t('高级工具 · AI 生成调试', 'Advanced · AI Generation') }}</summary><AceMusicPanel /></details>
    <section v-if="mode === 'demo' && !isFixed && !isSham" class="panel demo-setup">
      <label for="demo-profile">{{ t('演示方式', 'Demo Mode') }}</label>
      <select id="demo-profile" v-model="demoProfile" :disabled="running || startingAcquisition">
        <option value="showcase">{{ t('动态音乐演示', 'Dynamic music demo') }}</option>
        <option value="model">{{ t('模型验证', 'Model validation') }}</option>
      </select>
      <strong v-if="demoProfile === 'showcase'" class="demo-label">{{ t('预设演示 · 非模型预测', 'Scripted demo · not model predictions') }}</strong>
      <span v-else class="music-setup__help">{{ t('模拟波形 · 真实分类器', 'Simulated waveform · real classifier') }}</span>
      <details class="demo-notes"><summary>{{ t('演示说明', 'Demo Notes') }}</summary>
        <p v-if="demoProfile === 'showcase'">{{ t('清醒→N1→N2→清醒，每段24秒、96秒循环。约3秒触发首次 AI 生成或音频改写。此为预设阶段，仅检验音乐控制，不验证分类准确率。', 'W→N1→N2→W: 24-second stages, 96-second loop. Generation starts after about 3 seconds. Preset stages test music control, not classification accuracy.') }}</p>
        <p v-else>{{ t('保留真实模型与基线流程。恒定模拟信号不保证类别变化，不会篡改预测结果。', 'Uses the real model and baseline. Constant simulated signals may not change class; predictions are not modified.') }}</p>
      </details>
    </section>
    <section class="control-card panel">
      <div class="control-group"><label for="acquisition-mode">{{ t('数据源', 'Data Source') }}</label><select id="acquisition-mode" v-model="mode" :disabled="running || startingAcquisition"><option value="demo">{{ t('演示信号', 'Demo signal') }}</option><option value="brainflow">LK-Mini-EEG16 / BrainFlow</option></select></div>
      <div v-if="mode === 'brainflow'" class="control-group"><label for="device-ip">{{ t('设备 IP', 'Device IP') }}</label><input id="device-ip" v-model="ipAddress" :disabled="running || startingAcquisition" /></div>
      <div class="control-group"><label for="sample-rate">{{ t('采样率', 'Sample Rate') }}</label><select id="sample-rate" v-model="sampleRate" :disabled="running || startingAcquisition"><option v-for="rate in [250,500,1000]" :key="rate" :value="rate">{{ rate }} Hz</option></select></div>
      <div v-if="mode === 'brainflow'" class="control-group"><label for="hardware-gain">{{ t('硬件增益', 'Hardware Gain') }}</label><select id="hardware-gain" v-model="gain" :disabled="running || startingAcquisition"><option v-for="item in [1,2,4,6,8,12,24]" :key="item" :value="item">×{{ item }}</option></select></div>
      <div v-if="mode === 'brainflow'" class="control-group"><label for="classification-channels">{{ t('分类通道', 'Classification Channels') }}</label><select id="classification-channels" v-model="classificationChannels" :disabled="running || startingAcquisition"><option v-for="option in MODEL_OPTIONS" :key="option.count" :value="option.count">{{ option.count }} {{ t('通道', 'channels') }} · {{ option.channels.join(' ') }}</option></select></div>
      <div class="actions"><button v-if="!running" class="primary" :disabled="startingAcquisition" @click="startAcquisition">{{ startingAcquisition ? t('正在启动…', 'Starting…') : t('开始采集', 'Start Recording') }}</button><button v-else class="stop" @click="stopAcquisition">{{ t('停止采集', 'Stop Recording') }}</button></div>
      <label class="select-all"><input v-model="saveRawData" type="checkbox" disabled /> {{ t('保存原始脑电到本地', 'Save raw EEG locally') }}</label>
      <label v-if="!isFixed" class="select-all"><input v-model="autoSongEval" type="checkbox" :disabled="running || startingAcquisition" @change="saveSongPreference" /> {{ t('采集后自动 SongEval 评价（允许将混音 WAV 发送至指定服务器）', 'Automatic SongEval after recording (allow sending mix WAV to the designated server)') }}</label>
    </section>
    <p v-if="rawRecording" class="notice recording-status" role="status">{{ rawRecording.error ? t('保存异常', 'Saving failed') : rawRecording.complete ? t('保存完成', 'Saved') : t('正在保存', 'Saving') }} · {{ rawRecording.samples_written.toLocaleString() }} {{ t('样本 / 通道', 'samples / channel') }} · {{ rawRecording.path }}</p>
    <p v-if="rawRecording?.error" class="error-message" role="alert">{{ rawRecording.error }}</p>
    <p v-if="!isFixed" class="notice compact-notice">{{ t('开始采集将启用声音，请先调低设备音量。', 'Recording enables sound. Lower your device volume first.') }}</p>
    <p v-if="sampleRate !== 250" class="error-message" role="status">{{ t('自动推理与预设演示需要 250 Hz；请停止采集后切换采样率。', 'Inference and scripted demos require 250 Hz. Stop recording before switching sample rate.') }}</p>
    <p v-if="mode === 'brainflow'" class="notice" role="status">{{ t('真实设备始终采集全部 16 路；当前分类模型：', 'Live acquisition always captures all 16 channels. Selected classifier: ') }}cap{{ classificationChannels }}. {{ t('默认绘制所选电极，可切换查看全部 16 路。质量检查范围：', 'Selected electrodes are plotted by default; all 16 can be shown. Quality checks: ') }}{{ qualityChannels(classificationChannels).join(', ') }}. {{ t('不替换或插值电极。训练权重仅供研究，未经本设备验证。', 'No electrode replacement or interpolation. Research-only weights; not validated on this device.') }}</p>
    <section v-if="mode === 'brainflow' && running" class="panel demo-setup" :aria-label="t('实时分类反馈', 'Live classification feedback')">
      <p role="status">{{ eegEvent?.waveform_model?.model || `cap${classificationChannels}` }} · {{ eegEvent?.classification_channels || classificationChannels }} {{ t('通道分类', 'classification channels') }} · {{ liveClassification ? `${liveClassification[0]} ${t('模型分数', 'model score')} ${(liveClassification[1] * 100).toFixed(1)}%` : t('等待有效脑电窗口', 'Waiting for a valid EEG window') }}</p>
      <p role="status">{{ liveModelStatus }} · {{ t('窗口收集', 'Window collection') }} {{ waveformCollection(eegEvent) }}</p>
      <p v-if="liveClassification">{{ t('W（清醒）', 'W (Awake)') }} {{ (eegEvent.probabilities.W * 100).toFixed(1) }}% · {{ t('N1（睡眠阶段1）', 'N1 (Sleep stage 1)') }} {{ (eegEvent.probabilities.N1 * 100).toFixed(1) }}% · {{ t('N2（睡眠阶段2）', 'N2 (Sleep stage 2)') }} {{ (eegEvent.probabilities.N2 * 100).toFixed(1) }}%</p>
      <WaveformQuality :event="eegEvent" :count="classificationChannels" />
      <p>{{ t('原始波形卷积神经网络（CNN）：每 6 秒处理最近 40 秒，预测代表最近 30 秒。模型分数不是校准置信度；仅供研究，未经本设备验证，不用于临床睡眠判断。无需个体基线。', 'Raw-waveform CNN: processes the latest 40 seconds every 6 seconds; predictions describe the latest 30 seconds. Scores are not calibrated confidence. Research only, not validated on this device or for clinical sleep assessment. No personal baseline required.') }}</p>
    </section>
    <p v-if="error" class="error-message" role="alert">{{ audioMessage(error) }}</p>
    <p v-if="waveformError" class="error-message" role="alert">{{ audioMessage(waveformError) }}</p>
    <p v-if="adaptiveConnectionError" class="error-message" role="alert">{{ audioMessage(adaptiveConnectionError) }}</p>
    <AutomaticAcePanel v-if="!isFixed && musicSource === 'ace'" ref="adaptivePanel" :event="adaptiveEvent" />
    <AdaptiveMusicPanel v-else-if="!isFixed" ref="adaptivePanel" :event="adaptiveEvent" />
    <details class="workspace-details panel" @toggle="draw">
      <summary>{{ t('脑电波形与采集指标', 'EEG Waveform & Metrics') }} <span>{{ t('采集', 'Recorded') }} {{ displayChannels.length }} {{ t('路', 'channels') }} · {{ t('分类', 'Classified') }} {{ mode === 'brainflow' ? classificationChannels : displayChannels.length }} {{ t('路', 'channels') }} · {{ t('可见', 'Visible') }} {{ enabledCount }} {{ t('路', 'channels') }} · {{ activeSampleRate }} Hz</span></summary>
      <section class="metrics"><div><span>{{ t('连接', 'Connection') }}</span><strong>{{ connected ? t('已连接', 'Connected') : t('未连接', 'Disconnected') }}</strong></div><div><span>{{ t('采样率', 'Sample Rate') }}</span><strong>{{ activeSampleRate }} Hz</strong></div><div><span>{{ t('采集通道', 'Recorded Channels') }}</span><strong>{{ displayChannels.length }}</strong></div><div><span>{{ t('分类通道', 'Classification Channels') }}</span><strong>{{ mode === 'brainflow' ? classificationChannels : displayChannels.length }}</strong></div><div><span>{{ t('可见通道', 'Visible Channels') }}</span><strong>{{ enabledCount }} / {{ plotIndices.length }}</strong></div><div><span>{{ t('累计样本', 'Total Samples') }}</span><strong>{{ samplesEmitted.toLocaleString() }}</strong></div><div><span>{{ t('时间', 'Time') }}</span><strong>{{ lastTimestamp.toFixed(1) }} s</strong></div></section>
      <div class="control-card waveform-controls">
        <div class="control-group"><label for="display-seconds">{{ t('显示窗口', 'Display Window') }}</label><select id="display-seconds" v-model="displaySeconds" @change="setDisplaySeconds"><option :value="3">3 {{ t('秒', 'seconds') }}</option><option :value="5">5 {{ t('秒', 'seconds') }}</option><option :value="10">10 {{ t('秒', 'seconds') }}</option></select></div>
        <div class="control-group"><label for="vertical-scale">{{ t('幅度范围（±μV）', 'Amplitude Range (±μV)') }}</label><select id="vertical-scale" v-model="verticalScale"><option v-for="scale in [50,100,200,500,1000]" :key="scale" :value="scale">±{{ scale }} μV</option></select></div>
        <div class="actions"><button class="secondary" @click="togglePause">{{ paused ? t('继续显示', 'Resume Display') : t('暂停显示', 'Pause Display') }}</button><button class="secondary" @click="clearWaveform">{{ t('清空', 'Clear') }}</button></div>
      </div>
      <section class="visual-panel"><div class="panel-heading"><div><h2>{{ plotIndices.length }} {{ t('通道波形', 'channel waveforms') }}</h2></div><label v-if="mode === 'brainflow'" class="select-all"><input v-model="showAllChannels" type="checkbox" /> {{ t('查看全部 16 路', 'Show all 16 channels') }}</label><label class="select-all"><input type="checkbox" :checked="enabledCount === plotIndices.length" @change="toggleAll" /> {{ t('全选显示通道', 'Select all visible channels') }}</label></div><div class="canvas-wrap"><canvas ref="canvas" /></div><div class="channel-list"><label v-for="{ name, index } in plottedChannels" :key="name" class="channel-toggle" :style="{ '--channel-color': COLORS[index] }"><input v-model="channelEnabled[index]" type="checkbox" /><span>{{ index + 1 }} {{ name }}</span></label></div></section>
      <p class="notice">{{ t('显示波形经过 5–50 Hz 级联及 50 Hz 陷波；显示幅度有限制，不代表信号质量合格。', 'Displayed waveforms use cascaded 5–50 Hz filters and a 50 Hz notch. Display amplitude is limited and does not establish signal quality.') }}</p>
    </details>
    <details class="workspace-details panel"><summary>{{ t('采集与播放说明', 'Recording & Playback Notes') }}</summary><p>{{ t('固定音乐由外部设备播放，本机不输出音频。伪闭环由独立预设信号控制音乐，真实 EEG 单独归档。真闭环沿用当前 EEG 驱动流程；质量异常或分类过期时不启动新音乐，已有音乐继续播放。实验默认45分钟，可手动结束；N2音乐暂停不再提前结束实验采集。演示信号不代表真实睡眠状态。', 'Fixed music plays on an external device; this app produces no audio. Sham music follows an independent script while measured EEG is archived separately. Closed loop retains the EEG-driven workflow; poor quality or stale classification blocks new music while current music continues. Trials default to 45 minutes and can be stopped manually; N2 music pauses no longer end acquisition early. Demo signals do not represent real sleep states.') }}</p><p>{{ t('原始波形支持250/500/1000 Hz，当前模型仅接收250 Hz。真实模式请独占设备连接。研究原型，未验证助眠效果。', 'Raw waveforms support 250/500/1000 Hz; the current model only accepts 250 Hz. Reserve exclusive device access for live mode. Research prototype; sleep benefit has not been validated.') }}</p></details>
    <details v-if="!isFixed" class="workspace-details panel manual-tools"><summary>{{ t('高级工具 · MIDI实验台', 'Advanced · MIDI Workbench') }}</summary><MusicWorkbench /></details>
    </div>
  </main>
  </div>
</template>

<style scoped>
.experiment-identity { display:flex; flex-wrap:wrap; gap:16px; margin:16px 0; padding:14px 0; border:0; border-bottom:1px solid #d5dfda; min-width:0; }
.experiment-identity legend { font-size:14px; font-weight:600; }
.experiment-identity label { font-size:13px; max-width:100%; }
.experiment-identity input,.experiment-identity select { max-width:100%; }
.experiment-identity { align-items:center; }
.participant-button,.participant-dialog button { padding:9px 14px; border:1px solid #8daba0; background:#f4f8f6; border-radius:6px; color:#254d40; max-width:100%; overflow-wrap:anywhere; }
.experiment-modes { display:flex; flex-wrap:wrap; gap:4px; }
.experiment-modes label { padding:10px 12px; border:1px solid #cad5d1; border-radius:4px; display:flex; align-items:center; gap:7px; cursor:pointer; white-space:nowrap; min-height:42px; }
.experiment-modes input[type="radio"] { width:14px; height:14px; padding:0; margin:0; flex:0 0 14px; }
.experiment-modes label.active { border-color:#347969; background:#e7f3ef; }
.experiment-duration { color:#52665c; font-size:13px; }
.condition-status { padding:12px 0; color:#325b68; border-bottom:1px solid #d7e1e4; font-size:14px; }
.participant-dialog { width:min(400px,calc(100% - 32px)); border:1px solid #c3d2ca; border-radius:8px; padding:24px; }
.participant-dialog::backdrop { background:#142b2455; }
.participant-dialog h2 { font-size:20px; margin:0 0 16px; }
.participant-dialog input { width:100%; margin:8px 0 20px; }
.participant-dialog form>div { display:flex; gap:12px; }
.app-shell { max-width: 1120px; padding-top: 24px; }
.topbar { margin-bottom: 20px; }
.topbar h1 { font-size: 30px; }
.header-tools { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.page-tabs { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; border-bottom:1px solid #ccd7d0; padding-bottom:12px; }
.page-tabs button { border:1px solid transparent; background:transparent; padding:10px 12px; border-radius:6px; color:#375745; }
.page-tabs button[aria-pressed="true"] { background:#e5eee8; border-color:#4e7966; }
.header-tools select { width:auto; min-width:110px; border-radius:6px; }
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
