<script setup>
import WaveformQuality from './WaveformQuality.vue'
import { computed, shallowRef, watch, onBeforeUnmount } from 'vue'
import { StemEngine } from '../audio/stemEngine.js'
const props = defineProps({ event: Object, track: Object })
const playback = shallowRef({ status: 'stopped', stems: [], volume: .18, strength: .85, bypass: false })
const engine = new StemEngine({ onUpdate: value => { playback.value = value } })
const roles = { piano: '钢琴', strings: '弦乐', bass: '低音', pad: '铺底' }
const labels = { stopped: '已停止', buffering: '加载中', waiting: '准备中', playing: '同步播放中', fading: '渐出中' }
const provenance = computed(() => props.event?.demo_scripted ? '预设演示 · 非模型预测' : props.event?.source === 'LIVE' ? 'LIVE · 实时脑电' : 'DEMO · 模型验证')
const stage = computed(() => {
  if (!playback.value.applied) return '—'
  if (props.event?.demo_scripted) return props.event.demo_stage || '—'
  if (playback.value.applied.mode === 'conservative') return '准备中'
  const p = props.event?.probabilities
  return p ? Object.keys(p).reduce((best, key) => p[key] > p[best] ? key : best, 'W') : '—'
})
const wave = computed(() => (playback.value.audio?.waveform || Array(128).fill(0)).map((v,i) => `${i/127*720},${72-Math.max(-1,Math.min(1,v*8))*58}`).join(' '))
const spectrum = computed(() => playback.value.audio?.spectrum || Array(32).fill(0))
const db = computed(() => playback.value.audio ? `${playback.value.audio.rmsDb.toFixed(1)} dBFS` : '—')
function arm() { return engine.arm(props.track) }
function stop(reason) { engine.stop(reason) }
function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(engine.exportLog(), null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = 'terry-stem-session.json'; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => props.event, event => engine.consume(event), { flush: 'sync' })
onBeforeUnmount(() => engine.dispose())
defineExpose({ arm, stop })
</script>

<template>
  <section class="panel stem-panel" aria-labelledby="stem-title">
    <header class="stem-header"><div><p class="eyebrow">EEG / AUDIO</p><h2 id="stem-title">音乐随状态变化</h2></div><span class="source-label">{{ provenance }}</span></header>
    <div class="stem-status"><strong>{{ labels[playback.status] }}</strong><span>{{ track?.id || '未选择曲目' }}</span><span>{{ Math.floor((playback.elapsed || 0)/60) }}:{{ String(Math.floor((playback.elapsed || 0)%60)).padStart(2,'0') }}</span><b>{{ stage }}</b></div>
    <p v-if="playback.status !== 'playing'" class="status-message" role="status">{{ playback.reason || '开始采集后启用音乐。' }}</p>
    <p v-else-if="playback.applied?.mode === 'conservative'" class="status-message">基线准备中 · 固定低增益混音</p>
    <WaveformQuality v-if="event?.source === 'LIVE'" :event="event" />
    <div class="audio-visual" aria-label="浏览器混音输出分析">
      <div class="visual-heading"><span>实时输出波形</span><strong>{{ db }}</strong></div>
      <svg viewBox="0 0 720 144" role="img" aria-label="浏览器输出波形，横轴最近约64毫秒，纵轴数字幅度，显示放大8倍">
        <line x1="0" x2="720" y1="72" y2="72" class="zero-line" />
        <polyline :points="wave" class="wave-line" />
      </svg>
      <div class="frequency-bars" role="img" aria-label="输出频谱，横轴0到8千赫兹，柱高表示负85到负15dBFS范围内的峰值"><i v-for="(v,i) in spectrum" :key="i" :style="{ height: `${Math.max(0,v)*100}%` }" /></div>
      <div class="axis-label"><span>0 Hz</span><span>4 kHz</span><span>8 kHz</span></div>
      <small>浏览器数字输出 · 波形显示×8，非声压测量</small>
    </div>
    <div class="stem-grid">
      <article v-for="stem in playback.stems" :key="stem.id">
        <div><strong>{{ roles[stem.role] }}</strong><small>{{ stem.id }}</small></div>
        <meter min="0" max="1" :value="stem.current" :aria-label="`${stem.id} 当前节点增益`" />
        <small>{{ Math.round(stem.current*100) }}% <span>→ {{ Math.round(stem.target*100) }}%</span></small>
      </article>
    </div>
    <div class="mix-toolbar">
      <div class="mode-switch" role="group" aria-label="混音对照">
        <button :aria-pressed="!playback.bypass" @click="engine.setComparison(false)">自适应增强</button>
        <button :aria-pressed="playback.bypass" @click="engine.setComparison(true)">固定分轨对照</button>
      </div>
      <label>变化强度 <strong>{{ Math.round(playback.strength * 100) }}%</strong><input aria-label="分轨变化强度" type="range" min="0" max="100" :value="playback.strength * 100" :disabled="playback.bypass" @input="engine.setStrength(Number($event.target.value)/100)" /></label>
      <label>音量 <strong>{{ Math.round(playback.volume * 100) }}%</strong><input aria-label="分轨输出音量" type="range" min="0" max="30" :value="playback.volume * 100" @input="engine.setVolume(Number($event.target.value)/100)" /></label>
    </div>
    <footer><small>{{ playback.bypass ? '对照为同一组四轨，非完整原曲' : '改变声部与音色，不靠整体加大音量' }}</small><button @click="stop('用户停止分轨声音')" :disabled="!playback.armed">停止分轨声音</button></footer>
    <details class="diagnostics"><summary>诊断与说明</summary>
      <p>{{ playback.reason }}</p><p>后端：{{ event?.status }} / {{ event?.reason }} {{ event?.inference_hold_reason }}</p>
      <p v-if="event?.demo_scripted">动态音乐演示 · 非机器学习预测。当前预设 {{ event.demo_stage }}；24秒一段。预设权重仅测试控制链路。</p>
      <p v-if="playback.applied">已应用序号 {{ playback.applied.sequence }} · 控制量 {{ playback.applied.control_level?.toFixed(2) ?? '固定混音' }} · 低通 {{ Math.round(playback.cutoff) }} Hz · {{ playback.applied.transition_seconds }}秒渐变。</p>
      <p>强度0保留原自适应映射，100扩大声部对比和550–7200Hz音色范围；准备期不增强。对照将四轨固定为0.3增益，不包含原曲所有声部，也未做等响度匹配。曲目本身的演奏变化也影响频谱，不能把所有图形变化归因于脑电。</p>
      <p>当前是分轨混音，不是MIDI音符编辑。模型模式仍需约300秒有效基线；演示为预设，不代表睡眠分类。断流、切后台或停止采集会停止声音。请先调低设备音量。</p>
      <button @click="download">导出分轨控制日志</button>
    </details>
  </section>
</template>

<style scoped>
.stem-panel { padding:clamp(18px,3vw,30px); margin:20px 0; color:#203b30; }
.stem-header,.stem-status,.visual-heading,footer { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
h2 { margin:4px 0 12px; font-size:24px; }.eyebrow { margin:0; font-size:11px; letter-spacing:.12em; color:#6e8275; }
.source-label { font-size:12px; padding:7px 11px; border-radius:20px; background:#edf2eb; }
.stem-status { justify-content:flex-start; font-size:13px; color:#66796c; }.stem-status b { margin-left:auto; font-size:20px; color:#315e45; }
.status-message { font-size:13px; overflow-wrap:anywhere; }
.audio-visual { background:#f5f8f3; border-radius:14px; padding:16px 20px; margin-top:20px; }.visual-heading { font-size:12px; }.audio-visual svg { display:block; width:100%; height:144px; }.zero-line { stroke:#d9e3d5; }.wave-line { stroke:#3c795a; stroke-width:1.7; fill:none; }
.frequency-bars { display:flex; height:54px; gap:4px; align-items:flex-end; }.frequency-bars i { flex:1; background:#80a48c; border-radius:2px 2px 0 0; }.axis-label { display:flex; justify-content:space-between; margin:6px 0; font-size:10px; color:#6e8275; }
small { font-size:11px; color:#728176; }.stem-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin:22px 0; }.stem-grid article div { display:flex; justify-content:space-between; font-size:13px; }.stem-grid meter { display:block; width:100%; height:10px; margin:10px 0; accent-color:#3c795a; }.stem-grid small span { color:#a0aba1; }
.mix-toolbar { display:flex; flex-wrap:wrap; gap:20px; align-items:center; border-top:1px solid #e5ebe2; padding-top:20px; }label { display:grid; grid-template-columns:1fr auto; gap:8px; font-size:12px; flex:1; min-width:140px; }input { grid-column:span 2; width:100%; accent-color:#3c795a; }.mode-switch { display:flex; background:#f0f3ed; padding:3px; border-radius:9px; }button { padding:9px 12px; border:1px solid #dfe5dc; border-radius:7px; background:white; color:inherit; cursor:pointer; font:inherit; font-size:12px; }button:disabled { opacity:.4; cursor:default; }.mode-switch button { border:none; background:transparent; }.mode-switch button[aria-pressed=true] { background:#254c39; color:white; }footer { margin-top:20px; }.diagnostics { border-top:1px solid #e5ebe2; margin-top:20px; padding-top:14px; font-size:12px; color:#647667; }.diagnostics summary { cursor:pointer; }.diagnostics p { line-height:1.7; overflow-wrap:anywhere; }
@media(max-width:600px) { .stem-grid { grid-template-columns:repeat(2,1fr); }.mode-switch { width:100%; }.mode-switch button { flex:1; }.audio-visual { padding:12px; } }
</style>
