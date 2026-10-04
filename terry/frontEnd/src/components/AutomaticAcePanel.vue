<script setup>
import WaveformQuality from './WaveformQuality.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { canPlayAutomatic, canContinueAutomatic, liveClassification, musicStateLabels, waveformCollection, waveformHoldReasons, waveformStatus } from '../audio/liveClassification.js'

const props = defineProps({ event: { type: Object, default: null } })
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const status = ref('等待有效脑电分类'), error = ref('')
const playing = ref(null), clock = ref(Date.now()), playingMusicState = ref(null)
const lastClassification = ref(null)
const stageNames = { W: 'W（清醒）', N1: 'N1（睡眠阶段1）', N2: 'N2（睡眠阶段2）' }
const classifiedStage = computed(() => {
  const result = liveClassification(props.event, true, clock.value)
  return result ? stageNames[result[0]] : '当前不可用（等待质量合格的脑电）'
})
const hasCurrentClassification = computed(() => !!liveClassification(props.event, true, clock.value))
const playingLabel = computed(() => musicStateLabels[playingMusicState.value] || '已有音乐')
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
let context, gain, current, timer, disposed = false, generation = 0
const sources = new Set()
let requestController = null

function arm() {
  stop()
  const Context = window.AudioContext || window.webkitAudioContext
  if (!Context) { error.value = '浏览器不支持自动播放'; return Promise.resolve(false) }
  context = new Context()
  gain = context.createGain(); gain.gain.value = .12; gain.connect(context.destination)
  context.resume().catch(cause => { error.value = cause.message })
  status.value = '等待有效脑电分类'
  timer = setInterval(refresh, 3000)
  refresh()
  return Promise.resolve(true)
}
function stop() {
  ++generation
  clearInterval(timer); timer = null
  requestController?.abort(); requestController = null
  silence(); playing.value = null; playingSession = null; playingMusicState.value = null
  context?.close(); context = null; gain = null
  status.value = '已停止'; error.value = ''
}
function silence() {
  for (const source of sources) {
    source.stop(); source.disconnect(); source.fadeGain?.disconnect()
  }
  sources.clear(); current = null
}
function hold({ preserve = false } = {}) {
  ++generation
  requestController?.abort(); requestController = null
  if (preserve) {
    status.value = '分类暂不可用，继续播放已有音乐；暂停分类驱动更新'
  } else {
    silence(); playing.value = null; playingSession = null; playingMusicState.value = null
    status.value = props.event?.source === 'LIVE' ? waveformStatus(props.event) : '等待有效脑电分类'
  }
  error.value = ''
}
function guard() {
  clock.value = Date.now()
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
    if (['paused', 'stopped', 'error'].includes(result.status)) {
      silence(); playing.value = null
      status.value = result.status === 'error' ? '生成失败' : '等待有效稳定分类，播放暂停'
      error.value = result.error || ''
      return
    }
    status.value = { waiting: '等待有效脑电分类', generating: '根据分类生成中',
      cooldown: '等待下一次状态生成', ready: '自动播放中', error: '生成失败' }[result.status] || result.status
    if (result.error) error.value = result.error
    if (result.status !== 'ready' || !result.audio_url || result.audio_url === playing.value) return
    const audioResponse = await fetch(`${api}${result.audio_url}`, { signal: controller.signal })
    if (!audioResponse.ok) throw new Error(`音频下载失败（HTTP ${audioResponse.status}）`)
    const data = await audioResponse.arrayBuffer()
    if (!stillValid()) return
    const buffer = await audioContext.decodeAudioData(data)
    if (!stillValid() || String(result.session_id) !== String(props.event?.session_id)) return
    const next = audioContext.createBufferSource()
    const fadeGain = audioContext.createGain()
    next.fadeGain = fadeGain
    next.buffer = buffer; next.loop = true; next.connect(fadeGain); fadeGain.connect(gain)
    const now = audioContext.currentTime
    fadeGain.gain.setValueAtTime(0, now)
    fadeGain.gain.linearRampToValueAtTime(1, now + 1.5)
    sources.add(next)
    next.onended = () => { sources.delete(next); next.disconnect(); fadeGain.disconnect() }
    next.start()
    if (current) {
      current.fadeGain.gain.cancelScheduledValues(now)
      current.fadeGain.gain.setValueAtTime(current.fadeGain.gain.value, now)
      current.fadeGain.gain.linearRampToValueAtTime(0, now + 1.5)
      current.stop(now + 1.5)
    }
    current = next; playing.value = result.audio_url; playingSession = props.event.session_id
    playingMusicState.value = result.music_state || props.event.current_music_state
    error.value = ''
  } catch (cause) {
    if (token === generation && cause.name !== 'AbortError') { error.value = cause.message; status.value = '播放失败' }
  } finally {
    clearTimeout(timeout)
    if (requestController === controller) requestController = null
  }
}
watch(() => props.event, (event, previous) => {
  if (String(event?.session_id) !== String(previous?.session_id)) { lastClassification.value = null; hold() }
  const result = liveClassification(event, true, Date.now())
  if (result) lastClassification.value = { stage: stageNames[result[0]], emitted_at_s: event.emitted_at_s }
  if (context) guard()
}, { deep: true, flush: 'sync', immediate: true })
onBeforeUnmount(() => { disposed = true; stop() })
defineExpose({ arm, stop })
</script>

<template>
  <section class="ace-auto" aria-labelledby="ace-auto-title">
    <h2 id="ace-auto-title">脑电驱动音乐</h2>
    <p role="status">{{ status }} <span v-if="playing">· 音乐方案：{{ playingLabel }}</span></p>
    <p v-if="error" role="alert" class="error-message">{{ error }}</p>
    <p v-if="event?.status === 'blocked'" role="alert">{{ holdReasons[event.reason] || `分类阻断：${event.reason || '未知原因'}` }}</p>
    <template v-if="event?.source === 'LIVE'">
      <p role="status">{{ modelStatus }} · {{ event?.waveform_model?.model || '等待波形模型' }} · {{ event?.classification_channels || '—' }} 路分类 · 窗口收集 {{ waveformCollection(event) }}</p>
      <p>原始波形卷积神经网络（CNN）· 无需个体基线。</p>
      <WaveformQuality :event="event" />
      <p role="status">当前脑电推理类别：<strong>{{ classifiedStage }}</strong><span v-if="hasCurrentClassification"> · {{ event.classification_confirmed ? '已连续确认' : '等待连续确认' }}</span></p>
      <p v-if="lastClassification && !hasCurrentClassification">上次有效推理类别：{{ lastClassification.stage }}（历史记录，不代表当前状态）</p>
      <p>W / N1 / N2 是睡眠类别；M1 / M2 / M3 是音乐方案，经过平滑与切换等待后选择，不是模型分类标签。</p>
      <p>模型仅供研究，未经本设备验证；W / N1 / N2 分数不是校准置信度。实时事件超过 15 秒未更新或脑电质量不合格时继续播放已有音乐，暂不按无效或过期分类生成或切换音乐。手动停止或停止采集仍会停止播放。</p>
    </template>
    <p v-else-if="event?.demo_scripted">预设演示不触发 AI 生成。请使用模型验证或真实设备。</p>
    <p v-else>分类状态：{{ event?.classification_confirmed && event?.playback_mode === 'adaptive' ? '已确认' : '等待有效稳定分类' }} · 个体基线：{{ event?.state?.baseline_ready ? '就绪' : '后台收集中' }}</p>
  </section>
</template>

<style scoped>
.ace-auto { margin: 16px 0; padding: 18px 20px; border-top: 1px solid #d5ded6; border-bottom: 1px solid #d5ded6; }
h2 { font-size: 18px; margin: 0 0 10px; }
p { margin: 6px 0; font-size: 13px; }
</style>
