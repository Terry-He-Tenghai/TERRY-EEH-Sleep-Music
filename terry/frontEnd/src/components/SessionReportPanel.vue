<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const reports = ref([]), selected = ref(null), error = ref(''), busy = ref(false), recovery = ref(null)
const reason = { manual_stop: '手动停止', two_valid_n2: '连续两次有效 N2', acquisition_error: '采集异常', unexpected_end: '意外结束' }
async function refresh() {
  busy.value = true
  try {
    const response = await fetch(`${api}/api/session-reports`, { cache: 'no-store' })
    if (!response.ok) throw new Error('会话报告接口不可用')
    reports.value = await response.json()
    if (selected.value) selected.value = reports.value.find(r => r.id === selected.value.id) || selected.value
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(selected.value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = `${selected.value.id}-report.json`; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function ready(event) {
  error.value = event.detail.error || ''
  recovery.value = event.detail.error ? event.detail : null
  await refresh()
  selected.value = reports.value.find(r => r.id === event.detail.id) || selected.value
}
function recoverAudio() {
  if (!recovery.value?.audio) return
  const url = URL.createObjectURL(recovery.value.audio)
  const link = document.createElement('a'); link.href = url; link.download = 'unsaved-final-mix.wav'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const number = (value, unit = '') => typeof value === 'number' ? `${value.toFixed(2)}${unit}` : '未测量'
onMounted(() => { refresh(); window.addEventListener('session-report-ready', ready) })
onBeforeUnmount(() => window.removeEventListener('session-report-ready', ready))
</script>
<template>
  <section class="session-reports" aria-labelledby="report-title">
    <header><h2 id="report-title">会话报告</h2><button :disabled="busy" @click="refresh">刷新报告</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="recovery?.audio" @click="recoverAudio">下载未保存的最终录音</button>
    <p v-if="!reports.length">暂无会话记录</p>
    <select v-else :value="selected?.id || ''" aria-label="选择会话报告" @change="selected = reports.find(r => r.id === $event.target.value)">
      <option value="">选择会话</option>
      <option v-for="report in reports" :key="report.id" :value="report.id">{{ new Date(report.started_at_s * 1000).toLocaleString() }} · {{ report.metadata.mode === 'demo' ? '演示' : '真实设备' }} · {{ reason[report.end_reason] || (report.ended_at_s ? report.end_reason : '进行中') }}</option>
    </select>
    <template v-if="selected">
      <h3>EEG 与会话</h3>
      <p>结束原因：{{ reason[selected.end_reason] || selected.end_reason || '进行中' }} · 采集时长：{{ number(selected.eeg_summary?.duration_s, ' s') }} · 收到数据：{{ number(selected.received_seconds, ' s') }}</p>
      <p>合格窗口比例：{{ number(selected.eeg_summary?.qualified_window_ratio == null ? null : selected.eeg_summary.qualified_window_ratio * 100, '%') }} · 丢包：未测量</p>
      <details><summary>窗口轨迹（{{ selected.windows.length }}）</summary>
        <div class="table-wrap"><table><thead><tr><th>EEG 秒</th><th>质量</th><th>W / N1 / N2 分数</th><th>分类耗时</th></tr></thead>
          <tbody><tr v-for="window in selected.windows" :key="window.sequence"><td>{{ number(window.timestamp_s) }}</td><td>{{ number(window.signal_quality) }}</td><td>{{ window.probabilities || '不可用' }}</td><td>{{ number(window.classification_ms, ' ms') }}</td></tr></tbody></table></div>
      </details>
      <h3>音乐变化与输出</h3>
      <p>最终混音录音：{{ selected.browser?.recording_status || '尚未上传 / 浏览器未录音' }} · {{ number(selected.browser?.recorded_seconds, ' s') }}</p>
      <audio v-if="selected.audio" controls :src="`${api}${selected.audio.url}`" />
      <p v-if="selected.audio"><a :href="`${api}${selected.audio.url}`">下载最终混音 WAV</a> · 响度跳变候选：{{ selected.audio.metrics.rms_jump_candidates.length }}</p>
      <p>BPM、起音密度、调性、和弦、真峰值：尚未实现可靠估计</p>
      <details v-if="selected.browser"><summary>播放与控制时间线（{{ selected.browser.events.length }}）</summary><pre>{{ JSON.stringify(selected.browser.events, null, 2) }}</pre></details>
      <details v-if="selected.trace?.length"><summary>EEG → 控制 → 附近音频证据（{{ selected.trace.length }}）</summary><pre>{{ JSON.stringify(selected.trace, null, 2) }}</pre></details>
      <h3>程序性能</h3>
      <p>分类耗时与浏览器调度见窗口和时间线；远端排队 / 推理耗时、硬件输出延迟、耳位声压未测量。</p>
      <p>软件风险筛查不能证明“没有刺耳声音”，舒适性仍需盲听。演示记录不代表睡眠结果；合格窗口比例不是有效采集时长比例。</p>
      <button @click="download">下载完整报告 JSON</button>
    </template>
  </section>
</template>
<style scoped>
.session-reports { border-top: 1px solid #ccd7d0; margin: 20px 0; padding: 18px 0; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 18px; } h3 { font-size: 15px; margin-top: 18px; }
p, td, th { font-size: 13px; } select { max-width: 100%; }
.table-wrap { overflow: auto; } table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 8px; border-bottom: 1px solid #dee5e0; }
pre { max-height: 320px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
audio { width: 100%; max-width: 500px; }
</style>
