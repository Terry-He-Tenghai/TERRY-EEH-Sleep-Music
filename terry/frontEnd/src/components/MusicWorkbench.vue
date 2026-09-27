<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ManualEngine, PRESETS } from '../audio/manualEngine.js'
import { editPlans, midiBytes } from '../audio/midiEditing.js'
const tracks = ref([]), padId = ref(''), textureId = ref(''), seed = ref(42), transpose = ref(0), variation = ref('auto'), timbre = ref('sine')
const motif = ref(''), durationScale = ref(1), record = ref(false), recording = ref(null), savingRecording = ref(false)
const running = ref(false), loading = ref(false), error = ref(''), volume = ref(15), chosen = ref('M1'), plans = ref(null), status = ref({ elapsed: 0, active: 'M1', target: 'M1', phrase: 1, progress: 0 })
const trims = ref({ pad: 100, melody: 100, bass: 100, texture: 100 })
const hasLog = ref(false), acknowledged = ref(false)
const available = computed(() => tracks.value.filter(t => t.available))
const locked = computed(() => running.value || loading.value || savingRecording.value)
const targetPreset = computed(() => PRESETS[status.value.active || chosen.value])
const notes = computed(() => plans.value?.[chosen.value]?.notes.filter(n => n.voice === 'melody') || [])
let request, disposed = false, generation = 0
const engine = new ManualEngine({ onUpdate(update) { running.value = update.running; status.value = { ...status.value, ...update }; if (update.reason) { hasLog.value = true; if (record.value) savingRecording.value = true; if (update.reason === 'scheduler-underrun') error.value = '浏览器调度延迟，已停止以避免音符堆积。请保持页面前台后重新开始。' } }, onRecording(blob) { recording.value = blob; savingRecording.value = false } })
async function refresh() {
  if (locked.value) return
  request?.abort(); request = new AbortController()
  try {
    const response = await fetch('/api/music', { signal: request.signal, cache: 'no-store' })
    if (!response.ok) throw new Error('音乐库读取失败')
    const body = await response.json(); if (disposed) return
    tracks.value = body.tracks || []
    if (!available.value.some(t => t.id === padId.value)) padId.value = ''
    if (!available.value.some(t => t.id === textureId.value)) textureId.value = ''
  } catch (e) { if (e.name !== 'AbortError') error.value = e.message }
}
async function buildPlans() {
  if (locked.value) return
  const token = ++generation; loading.value = true; error.value = ''; plans.value = null
  request?.abort(); request = new AbortController()
  try {
    const entries = await Promise.all(['M1', 'M2', 'M3'].map(async state => {
      const query = new URLSearchParams({ state, seed: seed.value, bars: 4, transpose: transpose.value, variation: variation.value })
      const response = await fetch(`/api/music-workbench/plan?${query}`, { signal: request.signal })
      if (!response.ok) throw new Error(`编排接口失败（${response.status}），请确认后端已加载音乐实验台接口`)
      return [state, await response.json()]
    }))
    if (disposed || token !== generation) return
    plans.value = editPlans(Object.fromEntries(entries), { motif: motif.value, transpose: Number(transpose.value), durationScale: Number(durationScale.value), variation: variation.value })
  } catch (e) { if (e.name !== 'AbortError') error.value = e.message }
  finally { if (token === generation) loading.value = false }
}
function invalidate() { plans.value = null }
async function start() {
  if (locked.value || !plans.value || !padId.value || !acknowledged.value) return
  window.dispatchEvent(new CustomEvent('terry-audio-owner', { detail: 'workbench' }))
  loading.value = true; error.value = ''; recording.value = null; hasLog.value = false; volume.value = 15; trims.value = { pad: 100, melody: 100, bass: 100, texture: 100 }
  try { await engine.start({ padId: padId.value, textureId: textureId.value, plans: plans.value, seed: Number(seed.value), transpose: Number(transpose.value), variation: variation.value, timbre: timbre.value, record: record.value, initialState: chosen.value }); if (engine.metadata) engine.metadata.editing = { motif: motif.value, duration_scale: Number(durationScale.value) } }
  catch (e) { error.value = e.message; savingRecording.value = false }
  finally { loading.value = false }
}
function stop(reason = 'user-stop') { generation++; request?.abort(); loading.value = false; const wasRecording = Boolean(engine.recorder); engine.stop(reason); if (!wasRecording) savingRecording.value = false }
function choose(state) { chosen.value = state; if (running.value) engine.requestState(state); else status.value = { ...status.value, active: state, target: state } }
function download(blob, name) { const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
function exportMidi() { if (plans.value) download(new Blob([midiBytes(plans.value[chosen.value], timbre.value)], { type: 'audio/midi' }), `terry-${chosen.value}-edited.mid`) }
function exportLog() { download(new Blob([JSON.stringify(engine.exportLog(), null, 2)], { type: 'application/json' }), 'terry-manual-session.json') }
function exportRecording() { const blob = recording.value; if (blob) download(blob, `terry-manual-mix.${blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm'}`) }
function visibility() { if (document.hidden && (running.value || loading.value)) stop('page-hidden') }
function ownership(event) { if (event.detail !== 'workbench' && (running.value || loading.value)) stop('other-player-started') }
onMounted(() => { refresh(); document.addEventListener('visibilitychange', visibility); window.addEventListener('terry-audio-owner', ownership) })
onBeforeUnmount(() => { disposed = true; generation++; request?.abort(); stop('unmount'); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('terry-audio-owner', ownership) })
</script>

<template>
  <section id="music-workbench" class="workbench panel" aria-labelledby="workbench-title">
    <header><div><p class="eyebrow">MANUAL / MIDI + LOCAL AUDIO</p><h2 id="workbench-title">手动音乐编排实验台</h2><p>同一背景持续播放，旋律在乐句边界变化。当前为手动输入，尚未连接 EEG 状态。</p></div><span class="mode-badge">{{ running ? 'MANUAL · 播放中' : loading ? '加载中' : 'MANUAL · 已停止' }}</span></header>
    <p class="notice">Suno 铺底 + MIDI 旋律 + MIDI 低音 + 可选本地纹理。合成音色是正弦/三角波试听，不是专业采样乐器；不会自动识别背景调性或节拍。请选择兼容 C 大调/A 小调、60 BPM 或无明显节拍的素材；八度移动不能修正调性不匹配。</p>
    <div class="edit-grid">
      <label>基础背景 / Pad<select v-model="padId" :disabled="locked"><option value="">请选择本地背景</option><option v-for="track in available" :key="track.id" :value="track.id">{{ track.title }} · {{ track.id.slice(-6) }}</option></select></label>
      <label>环境纹理 / Texture<select v-model="textureId" :disabled="locked"><option value="">不叠加纹理</option><option v-for="track in available" :key="track.id" :value="track.id">{{ track.title }} · {{ track.id.slice(-6) }}</option></select></label>
      <label>种子<input v-model.number="seed" type="number" min="0" max="2147483647" :disabled="locked" @input="invalidate" /></label>
      <label>变奏<select v-model="variation" :disabled="locked" @change="invalidate"><option value="auto">跟随 M1/M2/M3</option><option value="complete">完整</option><option value="reduced">减少音符</option><option value="extended">延长变奏</option><option value="octave">八度变奏</option></select></label>
      <label>整体八度<select v-model.number="transpose" :disabled="locked" @change="invalidate"><option :value="-12">低八度</option><option :value="0">原八度</option><option :value="12">高八度</option></select></label>
      <label>旋律音色<select v-model="timbre" :disabled="locked"><option value="sine">柔和正弦波</option><option value="triangle">三角波</option></select></label>
      <label class="wide">自编旋律动机（可留空使用内置动机）<input v-model="motif" placeholder="72 74 76 74 72 76（4–8个音高）" :disabled="locked" @input="invalidate" /></label>
      <label>旋律音长<select v-model.number="durationScale" :disabled="locked" @change="invalidate"><option :value=".5">×0.5</option><option :value="1">×1</option><option :value="2">×2 · 延长</option></select></label>
    </div>
    <p class="notice">MIDI 音高示例：60=C4，62=D4，64=E4，72=C5。允许48–96内的白键音高。每个编排乐句16拍、60 BPM；修改旋律或音色前先停止。选用固定变奏时 M2 不一定减少音符，“跟随状态”才采用默认减音规则。</p>
    <div class="actions"><button :disabled="locked" @click="refresh">刷新素材</button><button class="primary" :disabled="locked" @click="buildPlans">生成 / 更新 MIDI 编排</button><button :disabled="!plans" @click="exportMidi">导出 {{ chosen }} MIDI</button></div>
    <div class="state-buttons" role="group" aria-label="音乐状态"><button v-for="(label, state) in { M1: '丰富', M2: '过渡', M3: '极简' }" :key="state" :aria-pressed="chosen === state" :class="{ selected: chosen === state }" :disabled="loading" @click="choose(state)">{{ state }} · {{ label }}</button></div>
    <div class="state-info" aria-live="polite"><span>当前 {{ status.active }} → 目标 {{ running ? engine.target : chosen }}</span><span>乐句 {{ status.phrase }} · {{ (status.elapsed || 0).toFixed(1) }} s</span><span>参数渐变 {{ Math.round((status.progress || 0) * 100) }}%</span></div>
    <p class="notice">切换状态只改变下一可调度乐句，约提前0.15秒安排音频事件；已安排的乐句不会被截断。参数渐变5秒，已有音符保留释放尾音。背景不换曲、不循环，背景结束时会话停止；纹理较短则先自然结束。</p>
    <div class="layer-grid"><article v-for="(label, layer) in { pad: 'L1 · 背景', melody: 'L2 · 旋律', bass: 'L3 · 低音', texture: 'L4 · 纹理' }" :key="layer"><strong>{{ label }}</strong><meter min="0" max="1" :value="layer === 'texture' && !textureId ? 0 : targetPreset.gains[layer]" /><span>{{ layer === 'texture' && !textureId ? '未选择素材' : `目标增益 ${targetPreset.gains[layer].toFixed(2)}` }}</span><label>层音量 {{ trims[layer] }}%<input style="width:100%" v-model.number="trims[layer]" type="range" min="0" max="100" :aria-label="`${label}层音量`" :disabled="!running || (layer === 'texture' && !textureId)" @input="engine.setLayerLevel(layer, trims[layer] / 100)" /></label></article></div>
    <p class="notice">亮度 {{ targetPreset.brightness }} · 短延迟混响发送 {{ targetPreset.reverb }} · 声部声像展开 {{ targetPreset.width }}。这些是状态目标参数，不是实测响度或 EEG 推断结果。层音量在状态增益之上相乘，拉到0可让该层渐退（约1.5秒）；可将其他层拉到0单独试听一层。</p>
    <div v-if="plans" class="piano-preview" aria-label="旋律音符时间线"><div v-for="(note, i) in notes" :key="i" class="note" :style="{ left: `${note.start_beat / 16 * 100}%`, top: `${(i % 4) * 23 + 4}px`, width: `${Math.min(note.duration_beats, 16 - note.start_beat) / 16 * 100}%` }" :title="`音高${note.midi_note} · 起点${note.start_beat}拍 · 时长${note.duration_beats}拍`">{{ note.midi_note }}</div><p v-if="!notes.length">M3 不生成旋律/低音音符，保留背景与可选纹理。</p></div>
    <label class="check-label"><input v-model="acknowledged" type="checkbox" :disabled="locked" /> 已调低设备音量，并确认背景与旋律需要人工试听匹配；这不是疗效或听力安全保证。</label>
    <label class="check-label"><input v-model="record" type="checkbox" :disabled="locked" /> 录制本次实际浏览器混音（可选，停止后下载；不使用麦克风）</label>
    <div class="actions"><button class="primary" :disabled="locked || !plans || !padId || !acknowledged" @click="start">{{ loading ? '准备中…' : '开始同步混音' }}</button><button :disabled="!running && !loading" @click="stop()">立即停止</button><button :disabled="!hasLog || running || loading" @click="exportLog">导出会话日志</button><button :disabled="!recording" @click="exportRecording">下载混音录音</button></div>
    <label class="volume">输出音量 {{ volume }}%<input v-model.number="volume" type="range" min="0" max="40" :disabled="!running" @input="engine.setVolume(volume)" /></label>
    <p class="notice">默认15%，上限40%；压缩器不是声压限制器。隐藏页面、浏览器音频挂起、调度严重延迟或另一播放器启动时停止本会话。MIDI文件包含编辑后的旋律与低音，不包含Suno音频；其他软件播放的音色可能不同。</p>
    <p v-if="savingRecording" role="status">正在完成录音编码…</p><p v-if="error" class="error-message" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.workbench { padding:24px; margin-top:28px; }header { display:flex; flex-wrap:wrap; gap:20px; justify-content:space-between; }header p { margin-bottom:8px; color:#647260; font-size:14px; }.mode-badge { align-self:flex-start; border:1px solid #dde4d8; border-radius:24px; padding:8px 12px; font-size:12px; }.edit-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin:24px 0 12px; }.edit-grid label { display:flex; flex-direction:column; gap:8px; font-size:13px; }.wide { grid-column:span 2; }.actions { margin-top:20px; }.state-buttons { display:flex; flex-wrap:wrap; gap:12px; margin:24px 0 16px; }.state-buttons button { padding:12px 24px; background:white; border:1px solid #dfe5dc; border-radius:30px; }.state-buttons .selected { background:#1c2e1e; color:white; }.state-info { display:flex; flex-wrap:wrap; gap:24px; font-size:14px; }.layer-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:20px; }.layer-grid article { display:flex; flex-direction:column; gap:10px; border:1px solid #dfe5dc; padding:16px; border-radius:12px; }.layer-grid meter { width:100%; }.layer-grid span { font-size:12px; color:#647260; }.piano-preview { position:relative; height:104px; margin-top:20px; background:repeating-linear-gradient(90deg,#f0f3ed 0,#f0f3ed calc(6.25% - 1px),#d9e1d4 calc(6.25% - 1px),#d9e1d4 6.25%); border-radius:8px; overflow:hidden; }.piano-preview p { padding:20px; font-size:13px; }.note { position:absolute; background:#4d6d47; color:white; border-radius:3px; height:18px; font-size:10px; min-width:3px; overflow:hidden; }.check-label { display:flex; gap:10px; align-items:flex-start; margin-top:18px; font-size:13px; }.check-label input { width:auto; accent-color:#4d6d47; }.volume { display:flex; gap:14px; flex-wrap:wrap; margin-top:20px; font-size:14px; }.volume input { width:min(100%,400px); accent-color:#4d6d47; }@media(max-width:800px) { .edit-grid,.layer-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }@media(max-width:500px) { .workbench { padding:16px; }.edit-grid { grid-template-columns:1fr; }.wide { grid-column:auto; }.layer-grid { grid-template-columns:1fr; } }
</style>
