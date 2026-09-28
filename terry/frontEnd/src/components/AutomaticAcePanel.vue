<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({ event: { type: Object, default: null } })
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const status = ref('等待有效脑电分类'), error = ref('')
const playing = ref(null)
const holdReasons = {
  configured_channel_order_mismatch: '16 路电极位置与现有模型不一致，需匹配帽位并重新训练验证',
  live_inference_requires_8_or_16_channels: '分类需要 8 或 16 路脑电信号',
  physical_channel_map_unconfirmed_set_TERRY_EEG_CHANNEL_MAP_CONFIRMED_after_verification: '请先核实设备 CH0–CH15 的实际电极位置',
  configured_realtime_models_missing: '缺少与帽位匹配的分类模型',
  experimental_channel_mapping_contract_mismatch: '实验性电极映射与设备或模型的通道顺序不匹配',
}
let context, gain, current, timer, disposed = false, generation = 0, loading = false
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
  silence(); playing.value = null
  context?.close(); context = null; gain = null
  status.value = '已停止'; error.value = ''
}
function silence() {
  for (const source of sources) {
    source.stop(); source.disconnect(); source.fadeGain?.disconnect()
  }
  sources.clear(); current = null
}
async function refresh() {
  if (!context || loading || disposed || !props.event?.session_id) return
  const token = generation
  loading = true
  try {
    const response = await fetch(`${api}/api/ace/automatic/status`, { cache: 'no-store' })
    if (!response.ok) throw new Error('自动生成状态不可用')
    const result = await response.json()
    if (token !== generation || !props.event?.session_id || String(result.session_id) !== String(props.event.session_id)) return
    if (['blocked', 'frozen', 'error', 'stopped'].includes(props.event.status)) return
    if (result.status === 'paused' || result.status === 'stopped') {
      requestController?.abort()
      silence(); playing.value = null
      status.value = props.event?.inference_hold_reason === 'confirming_state_classification'
        ? '等待连续稳定分类'
        : props.event?.state?.status === 'ok' ? '等待完整分类窗口' : '信号不合格，播放暂停'
      return
    }
    status.value = { waiting: '等待有效脑电分类', generating: '根据分类生成中',
      cooldown: '等待下一次状态生成', ready: '自动播放中', error: '生成失败' }[result.status] || result.status
    if (result.error) error.value = result.error
    if (result.status !== 'ready' || !result.audio_url || result.audio_url === playing.value) return
    const controller = new AbortController()
    requestController = controller
    const audioResponse = await fetch(`${api}${result.audio_url}`, { signal: controller.signal })
    if (!audioResponse.ok) throw new Error(`音频下载失败（HTTP ${audioResponse.status}）`)
    const buffer = await context.decodeAudioData(await audioResponse.arrayBuffer())
    if (token !== generation || controller.signal.aborted || props.event?.status !== 'ready' ||
        String(result.session_id) !== String(props.event?.session_id)) return
    const next = context.createBufferSource()
    const fadeGain = context.createGain()
    next.fadeGain = fadeGain
    next.buffer = buffer; next.loop = true; next.connect(fadeGain); fadeGain.connect(gain)
    const now = context.currentTime
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
    current = next; playing.value = result.audio_url; error.value = ''
  } catch (cause) { if (token === generation && cause.name !== 'AbortError') { error.value = cause.message; status.value = '播放失败' } }
  finally { requestController = null; loading = false }
}
watch(() => props.event?.status, value => {
  if (['blocked', 'frozen', 'error', 'stopped'].includes(value)) {
    requestController?.abort()
    silence(); playing.value = null
    if (value === 'blocked') status.value = '分类未启动，音乐不会播放'
    else if (value === 'stopped') status.value = '已停止'
    else status.value = '分类已暂停，音乐不会播放'
    error.value = ''
  }
})
onBeforeUnmount(() => { disposed = true; stop() })
defineExpose({ arm, stop })
</script>

<template>
  <section class="ace-auto" aria-labelledby="ace-auto-title">
    <h2 id="ace-auto-title">脑电驱动音乐</h2>
    <p role="status">{{ status }} <span v-if="playing">· {{ event?.current_music_state }}</span></p>
    <p v-if="error" role="alert" class="error-message">{{ error }}</p>
    <p v-if="event?.status === 'blocked'" role="alert">{{ holdReasons[event.reason] || `分类阻断：${event.reason || '未知原因'}` }}</p>
    <p v-if="event?.inference_mode === 'cap_mapping_experimental'" role="status">实验性映射：14 路实测，Fz/Cz 插值；分类未经此帽位验证。</p>
    <p v-if="event?.demo_scripted">预设演示不触发 AI 生成。请使用模型验证或真实设备。</p>
    <p v-else-if="event?.inference_mode === 'spectral_heuristic'">分类来源：频谱启发式估计（未经验证） · {{ event?.classification_channels }} 路选项 / 实际使用 {{ event?.channel_repair?.used_channels?.length ?? 0 }} 路 · 无需个体基线</p>
    <p v-else>分类状态：{{ event?.classification_confirmed && event?.playback_mode === 'adaptive' ? '已确认' : '等待有效稳定分类' }} · 个体基线：{{ event?.state?.baseline_ready ? '就绪' : '后台收集中' }}</p>
  </section>
</template>

<style scoped>
.ace-auto { margin: 16px 0; padding: 18px 20px; border-top: 1px solid #d5ded6; border-bottom: 1px solid #d5ded6; }
h2 { font-size: 18px; margin: 0 0 10px; }
p { margin: 6px 0; font-size: 13px; }
</style>
