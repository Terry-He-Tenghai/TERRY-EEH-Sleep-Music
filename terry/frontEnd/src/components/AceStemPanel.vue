<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { text as t } from '../i18n.js'
import { audioMessage } from '../audioMessages.js'

const props = defineProps({ trackId: String, disabled: Boolean })
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const track = ref('keyboard'), busy = ref(false), error = ref(''), audioUrl = ref('')
const options = [['keyboard', '钢琴 / 键盘'], ['vocals', '主唱'], ['backing_vocals', '和声'], ['drums', '鼓'], ['bass', '贝斯'], ['guitar', '吉他'], ['percussion', '打击乐'], ['strings', '弦乐'], ['synth', '合成器'], ['fx', '音效'], ['brass', '铜管'], ['woodwinds', '木管']]
let controller, timer, epoch = 0

function reset() {
  epoch++
  controller?.abort()
  clearTimeout(timer)
  busy.value = false
  audioUrl.value = ''
  error.value = ''
}

async function extract() {
  reset()
  const run = epoch
  controller = new AbortController()
  const signal = controller.signal
  busy.value = true
  const deadline = Date.now() + 30 * 60 * 1000
  try {
    const response = await fetch(`${api}/api/ace/extractions`, {
      method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reference_track_id: props.trackId, track: track.value }),
    })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '声部提取请求失败')
    async function poll() {
      try {
        const response = await fetch(`${api}/api/ace/generations/${encodeURIComponent(body.task_id)}`, { signal })
        const result = await response.json()
        if (run !== epoch) return
        if (!response.ok) throw new Error(result.detail || '声部提取查询失败')
        if (result.status === 'completed') {
          audioUrl.value = `${api}${result.audio_url}`
          busy.value = false
        } else if (result.status === 'failed') {
          throw new Error(result.error || '声部提取失败')
        } else if (Date.now() >= deadline) {
          throw new Error('声部提取等待超时')
        } else timer = setTimeout(poll, 3000)
      } catch (exc) {
        if (run === epoch && exc.name !== 'AbortError') {
          error.value = exc.message
          busy.value = false
        }
      }
    }
    if (run === epoch) await poll()
  } catch (exc) {
    if (run === epoch && exc.name !== 'AbortError') {
      error.value = exc.message
      busy.value = false
    }
  }
}
watch(() => props.trackId, reset)
onBeforeUnmount(reset)
</script>

<template>
  <div class="ace-stems">
    <label>{{ t('提取声部', 'Extract stem') }} <select v-model="track" :disabled="busy || disabled"><option v-for="[id, name] in options" :key="id" :value="id">{{ t(name, id.replaceAll('_', ' ')) }}</option></select></label>
    <button type="button" :disabled="!trackId || busy || disabled" @click="extract">{{ busy ? t('正在提取…', 'Extracting…') : t('提取声部', 'Extract stem') }}</button>
    <span v-if="busy" role="status">{{ t('ACE-Step base 处理中', 'ACE-Step base processing') }}</span>
    <span v-if="error" role="alert">{{ audioMessage(error) }}</span>
    <template v-if="audioUrl"><audio :src="audioUrl" controls @loadedmetadata="$event.target.volume = 0.12" /><a :href="audioUrl" download="extracted-stem.wav">{{ t('下载声部', 'Download stem') }}</a></template>
  </div>
</template>

<style scoped>
.ace-stems { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 0; }
label { display: flex; align-items: center; gap: 8px; }
audio { max-width: 100%; }
[role="alert"] { color: #b91c1c; }
</style>
