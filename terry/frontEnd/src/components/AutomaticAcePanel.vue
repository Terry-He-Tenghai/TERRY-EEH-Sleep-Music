<script setup>
import { text as t } from '../i18n.js'
import { audioMessage } from '../audioMessages.js'
import WaveformQuality from './WaveformQuality.vue'
import { recordOutput, logEvidence } from '../audio/sessionEvidence.js'
import { analyzeUpload } from '../audio/uploadLoudness.js'
const telemetryLog = logEvidence
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { canPlayAutomatic, canContinueAutomatic, liveClassification, musicStateLabels, waveformCollection, waveformHoldReasons, waveformStatus } from '../audio/liveClassification.js'

const props = defineProps({ event: { type: Object, default: null } })
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const crossfadeSeconds = 8
const sleepFadeSeconds = 30
const status = ref('等待有效脑电分类'), error = ref('')
const playing = ref(null), clock = ref(Date.now()), playingMusicState = ref(null)
const wantedMusicState = ref(null)
const lastClassification = ref(null)
watch(() => props.event, () => { clock.value = Date.now() }, { flush: 'sync' })
const stageNames = computed(() => ({ W: t('W（清醒）', 'W (Awake)'), N1: t('N1（睡眠阶段1）', 'N1 (Sleep stage 1)'), N2: t('N2（睡眠阶段2）', 'N2 (Sleep stage 2)') }))
const classifiedStage = computed(() => {
  const result = liveClassification(props.event, true, clock.value)
  return result ? stageNames.value[result[0]] : t('当前不可用（等待质量合格的脑电）', 'Unavailable (waiting for acceptable EEG quality)')
})
const hasCurrentClassification = computed(() => !!liveClassification(props.event, true, clock.value))
const playingLabel = computed(() => musicStateLabels[playingMusicState.value] || t('已有音乐', 'Existing music'))
let playingSession = null
const modelStatus = computed(() => waveformStatus(props.event, clock.value))
const holdReasons = {
  configured_channel_order_mismatch: '16 路电极位置与现有模型不一致，需匹配帽位并重新训练验证',
  live_inference_requires_8_or_16_channels: '所选分类模型与脑电输入通道不匹配',
  physical_channel_map_unconfirmed_set_TERRY_EEG_CHANNEL_MAP_CONFIRMED_after_verification: '请先核实设备 CH0–CH15 的实际电极位置',
  configured_realtime_models_missing: '缺少与帽位匹配的分类模型',
  experimental_channel_mapping_contract_mismatch: '实验性电极映射与设备或模型的通道顺序不匹配',
  ...waveformHoldReasons,
}
const statusLabelsEn = {
  '等待有效脑电分类': 'Waiting for valid EEG classification',
  '已停止': 'Stopped',
  '分类暂不可用，继续播放已有音乐；暂停分类驱动更新': 'Classification unavailable; continuing current music without classification-driven updates',
  '连续三次有效 N2，音乐在 30 秒内渐弱至静音': 'Three consecutive valid N2 results; fading music to silence over 30 seconds',
  '等待有效脑电分类，播放暂停': 'Waiting for valid EEG classification; playback paused',
  '根据分类生成中': 'Generating from classification',
  '等待下一次状态生成': 'Waiting for the next state',
  '自动播放中': 'Playing automatically',
  '生成失败': 'Generation failed',
  '播放失败': 'Playback failed',
}
let context, gain, current, timer, disposed = false, generation = 0
const sources = new Set()
let requestController = null
let sleepFading = false

function rampDown(source, seconds) {
  const now = context.currentTime, parameter = source.fadeGain.gain
  if (parameter.cancelAndHoldAtTime) parameter.cancelAndHoldAtTime(now)
  else {
    parameter.cancelScheduledValues(now)
    parameter.setValueAtTime(parameter.value, now)
  }
  parameter.linearRampToValueAtTime(0, now + seconds)
  source.stop(now + seconds)
}
function pauseForSleep() {
  if (!sleepFading) {
    sleepFading = true
    for (const source of sources) rampDown(source, sleepFadeSeconds)
    telemetryLog('sleep-fade', { engine: 'ace', consecutive_n2: 3, fade_s: sleepFadeSeconds })
    current = null
  }
  playing.value = null; playingMusicState.value = null; wantedMusicState.value = null
  status.value = '连续三次有效 N2，音乐在 30 秒内渐弱至静音'
}

function arm() {
  stop()
  const Context = window.AudioContext || window.webkitAudioContext
  if (!Context) { error.value = '浏览器不支持自动播放'; return Promise.resolve(false) }
  context = new Context()
  gain = context.createGain(); gain.gain.value = .12; gain.connect(context.destination)
  recordOutput(context, gain, 'ace')
  context.resume().catch(cause => { error.value = cause.message })
  status.value = '等待有效脑电分类'
  timer = setInterval(refresh, 3000)
  refresh()
  return Promise.resolve(true)
}
function stop() {
  if (context) telemetryLog('stop', { engine: 'ace', audio_time_s: context.currentTime })
  ++generation
  clearInterval(timer); timer = null
  requestController?.abort(); requestController = null
  silence(); playing.value = null; playingSession = null; playingMusicState.value = null; wantedMusicState.value = null
  context?.close(); context = null; gain = null
  status.value = '已停止'; error.value = ''
}
function silence() {
  for (const source of sources) {
    source.stop(); source.disconnect(); source.fadeGain?.disconnect()
  }
  sources.clear(); current = null
  sleepFading = false
}
function hold({ preserve = false } = {}) {
  ++generation
  requestController?.abort(); requestController = null
  if (preserve) {
    status.value = '分类暂不可用，继续播放已有音乐；暂停分类驱动更新'
  } else {
    silence(); playing.value = null; playingSession = null; playingMusicState.value = null; wantedMusicState.value = null
    status.value = props.event?.source === 'LIVE' ? (props.event.inference_hold_reason || props.event.reason || '等待有效脑电分类') : '等待有效脑电分类'
  }
  error.value = ''
}
function guard() {
  clock.value = Date.now()
  if (props.event?.ace_sleep_paused) {
    if (requestController) {
      ++generation
      requestController.abort(); requestController = null
    }
    pauseForSleep()
    return false
  }
  if (!canPlayAutomatic(props.event, clock.value)) {
    hold({ preserve: !!current && canContinueAutomatic(props.event, playingSession, clock.value) })
    return false
  }
  return true
}
async function refresh() {
  // Stale events cannot authorize a new request or playback. An already
  // started buffer may continue, with its last accepted music plan frozen.
  if (!context || disposed || !guard() || requestController) return
  const token = generation, audioContext = context
  const controller = new AbortController()
  requestController = controller
  const timeout = setTimeout(() => controller.abort(), 15000)
  const stillValid = () => token === generation && !controller.signal.aborted && context === audioContext && guard()
  try {
    const response = await fetch(`${api}/api/ace/automatic/status`, { cache: 'no-store', signal: controller.signal })
    if (!response.ok) throw new Error('自动生成状态不可用')
    const result = await response.json()
    if (!stillValid()) return
    if (String(result.session_id) !== String(props.event.session_id)) { hold(); return }
    wantedMusicState.value = result.wanted_music_state || null
    if (result.status === 'sleep_paused') {
      pauseForSleep()
      error.value = ''
      return
    }
    if (result.status === 'paused' && current) {
      status.value = '分类暂不可用，继续播放已有音乐；暂停分类驱动更新'
      return
    }
    if (['paused', 'stopped', 'error'].includes(result.status)) {
      silence(); playing.value = null; wantedMusicState.value = null
      status.value = result.status === 'error' ? '生成失败' : '等待有效脑电分类，播放暂停'
      error.value = result.error || ''
      return
    }
    status.value = { waiting: '等待有效脑电分类', generating: '根据分类生成中',
      cooldown: '等待下一次状态生成', ready: '自动播放中', error: '生成失败' }[result.status] || result.status
    if (result.error) error.value = result.error
    if (result.status !== 'ready' || !result.audio_url || result.audio_url === playing.value) return
    const downloadStarted = performance.now()
    const audioResponse = await fetch(`${api}${result.audio_url}`, { signal: controller.signal })
    if (!audioResponse.ok) throw new Error(`音频下载失败（HTTP ${audioResponse.status}）`)
    const data = await audioResponse.arrayBuffer()
    telemetryLog('download', { engine: 'ace', duration_ms: performance.now()-downloadStarted, audio_url: result.audio_url })
    if (!stillValid()) return
    const decodeStarted = performance.now()
    const buffer = await audioContext.decodeAudioData(data)
    telemetryLog('decode', { engine: 'ace', duration_ms: performance.now()-decodeStarted, audio_url: result.audio_url })
    if (!stillValid() || String(result.session_id) !== String(props.event?.session_id)) return
    const loudness = await analyzeUpload(buffer, stillValid)
    if (!stillValid() || !loudness) return
    const level = Math.min(1, loudness.gain)
    telemetryLog('loudness-protection', { engine: 'ace', rms: loudness.rms, peak: loudness.peak, gain: level })
    const next = audioContext.createBufferSource()
    const fadeGain = audioContext.createGain()
    next.fadeGain = fadeGain
    next.buffer = buffer; next.loop = true; next.connect(fadeGain); fadeGain.connect(gain)
    const now = audioContext.currentTime
    fadeGain.gain.setValueAtTime(0, now)
    fadeGain.gain.linearRampToValueAtTime(level, now + crossfadeSeconds)
    sources.add(next)
    next.onended = () => { sources.delete(next); next.disconnect(); fadeGain.disconnect() }
    next.start()
    telemetryLog('playback-started', { engine: 'ace', session_id: props.event.session_id,
      sequence: props.event.sequence, audio_time_s: now, audio_url: result.audio_url,
      music_state: result.music_state, gain: .12, crossfade_s: crossfadeSeconds,
      provenance_scope: 'latest event at playback; generation trigger window not yet exposed by ACE API' })
    for (const source of sources) if (source !== next) rampDown(source, crossfadeSeconds)
    sleepFading = false
    current = next; playing.value = result.audio_url; playingSession = props.event.session_id
    playingMusicState.value = result.music_state || props.event.current_music_state
    error.value = ''
  } catch (cause) {
    if (cause.name !== 'AbortError') telemetryLog('playback-error', { engine: 'ace', error: cause.message })
    if (token === generation && cause.name !== 'AbortError') { error.value = cause.message; status.value = '播放失败' }
  } finally {
    clearTimeout(timeout)
    if (requestController === controller) requestController = null
  }
}
watch(() => props.event, (event, previous) => {
  if (String(event?.session_id) !== String(previous?.session_id)) { lastClassification.value = null; hold() }
  const result = liveClassification(event, true, Date.now())
  if (result) lastClassification.value = { stage: result[0], emitted_at_s: event.emitted_at_s }
  if (context) guard()
}, { deep: true, flush: 'sync', immediate: true })
onBeforeUnmount(() => { disposed = true; stop() })
defineExpose({ arm, stop })
</script>

<template>
  <section class="ace-auto" aria-labelledby="ace-auto-title">
    <h2 id="ace-auto-title">{{ t('脑电驱动音乐', 'EEG-Driven Music') }}</h2>
    <p role="status">{{ waveformHoldReasons[status] || t(status, statusLabelsEn[status] || status) }} <span v-if="playing">· {{ t('正在播放：', 'Playing: ') }}{{ playingLabel }}</span><span v-if="wantedMusicState && wantedMusicState !== playingMusicState"> · {{ t('待切换：', 'Next: ') }}{{ musicStateLabels[wantedMusicState] }}</span></p>
    <p v-if="error" role="alert" class="error-message">{{ audioMessage(error) }}</p>
    <p v-if="event?.status === 'blocked'" role="alert">{{ t(holdReasons[event.reason] || `分类阻断：${event.reason || '未知原因'}`, waveformHoldReasons[event.reason] || `Classification blocked: ${event.reason || 'unknown reason'}`) }}</p>
    <template v-if="event?.source === 'LIVE'">
      <p role="status">{{ modelStatus }} · {{ event?.waveform_model?.model || t('等待波形模型', 'Waiting for waveform model') }} · {{ event?.classification_channels || '—' }} {{ t('路分类 · 窗口收集', 'classification channels · Window collection') }} {{ waveformCollection(event) }}</p>
      <p>{{ t('原始波形卷积神经网络（CNN）· 无需个体基线。', 'Raw-waveform CNN · No personal baseline required.') }}</p>
      <WaveformQuality :event="event" />
      <p role="status">{{ t('当前脑电推理类别：', 'Current EEG classification: ') }}<strong>{{ classifiedStage }}</strong><span v-if="hasCurrentClassification"> · {{ event.classification_confirmed ? t('质量合格，可生成', 'Quality accepted; generation enabled') : t('分数低于生成门槛', 'Score below generation threshold') }}</span></p>
      <p v-if="lastClassification && !hasCurrentClassification">{{ t('上次有效推理类别：', 'Last valid classification: ') }}{{ stageNames[lastClassification.stage] }} {{ t('（历史记录，不代表当前状态）', '(historical, not current state)') }}</p>
      <p>{{ t('W / N1 / N2 是模型估计类别；有效分类分别选择 M1 / M2 / M3 音乐方案。连续三次有效 N2 后音乐用 30 秒渐弱至静音，脑电记录继续；不代表临床确认入睡。', 'W / N1 / N2 are model estimates selecting M1 / M2 / M3 music. After three consecutive valid N2 results, music fades to silence over 30 seconds while EEG recording continues. This is not clinical confirmation of sleep.') }}</p>
      <p>{{ t('模型仅供研究，未经本设备验证；W / N1 / N2 分数不是校准置信度。实时事件超过 15 秒未更新或脑电质量不合格时继续播放已有音乐，暂不按无效或过期分类生成或切换音乐。手动停止或停止采集仍会停止播放。', 'Research only; not validated on this device. W / N1 / N2 scores are not calibrated confidence. Existing music continues when EEG is stale beyond 15 seconds or quality is rejected, without classification-driven updates. Manual stop or acquisition stop still stops playback.') }}</p>
    </template>
    <p v-else-if="event?.demo_scripted">{{ t('预设阶段驱动 AI 生成或上传音频改写；非真实脑电分类。', 'Preset stages drive AI generation or uploaded-audio rewriting; not real EEG classification.') }}</p>
    <p v-else>{{ t('分类状态：', 'Classification: ') }}{{ event?.classification_confirmed && event?.playback_mode === 'adaptive' ? t('已确认', 'Confirmed') : t('等待有效稳定分类', 'Waiting for stable valid classification') }} · {{ t('个体基线：', 'Personal baseline: ') }}{{ event?.state?.baseline_ready ? t('就绪', 'Ready') : t('后台收集中', 'Collecting in background') }}</p>
  </section>
</template>

<style scoped>
.ace-auto { margin: 16px 0; padding: 18px 20px; border-top: 1px solid #d5ded6; border-bottom: 1px solid #d5ded6; }
h2 { font-size: 18px; margin: 0 0 10px; }
p { margin: 6px 0; font-size: 13px; }
</style>
