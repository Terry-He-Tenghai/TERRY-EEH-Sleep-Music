<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { text as t } from '../i18n.js'
import { audioMessage } from '../audioMessages.js'
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const reports = ref([]), selected = ref(null), error = ref(''), busy = ref(false), recovery = ref(null)
let pollTimer = null, disposed = false
const audioSummary = computed(() => {
  const frames = selected.value?.audio?.metrics?.frames || []
  const mean = key => {
    const values = frames.map(f => f[key]).filter(v => typeof v === 'number' && Number.isFinite(v))
    return values.length ? values.reduce((a,b) => a+b, 0)/values.length : null
  }
  return { rms: mean('rms_dbfs'), centroid: mean('centroid_hz'), high: mean('high_frequency_ratio'),
    clipped: frames.length ? frames.reduce((n,f) => n+f.clipped_samples, 0) : null,
    duration: frames.length ? frames.reduce((n,f) => n+f.duration_s, 0) : null }
})
const aiScores = computed(() => [
  ['pleasantness', t('悦耳度', 'Pleasantness')], ['coherence', t('连贯性', 'Coherence')],
  ['transition_naturalness', t('变化自然度', 'Transition naturalness')],
])
const songScores = computed(() => [['coherence', t('整体连贯性', 'Coherence')], ['musicality', t('整体音乐性', 'Musicality')], ['memorability', t('记忆性', 'Memorability')], ['structure_clarity', t('结构清晰度', 'Structure clarity')], ['vocal_naturalness', t('歌声呼吸／乐句自然性', 'Vocal naturalness')]])
const reasonText = key => ({ duration_complete: t('实验计时结束', 'Experiment duration complete'), manual_stop: t('手动停止', 'Manual stop'), two_valid_n2: t('连续两次有效 N2', 'Two valid N2 windows'), acquisition_error: t('采集异常', 'Acquisition error'), unexpected_end: t('意外结束', 'Unexpected end') }[key] || key || t('进行中', 'In progress'))
const conditionText = key => ({fixed:t('固定音乐','Fixed music'),sham:t('伪闭环','Sham loop'),closed_loop:t('真闭环','Closed loop')}[key] || t('未分组','Unassigned'))
async function refresh() {
  busy.value = true
  try {
    const response = await fetch(`${api}/api/session-reports`, { cache: 'no-store' })
    if (!response.ok) throw new Error('会话报告接口不可用')
    reports.value = await response.json()
    if (selected.value) selected.value = reports.value.find(r => r.id === selected.value.id) || selected.value
  } catch (cause) { error.value = cause.message }
  finally {
    busy.value = false
    clearTimeout(pollTimer)
    if (!disposed) pollTimer = setTimeout(refresh, 5000)
  }
}
function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(selected.value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = `${selected.value.id}-report.json`; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function ready(event) {
  const detail = event.detail || {}
  error.value = detail.error || ''
  recovery.value = detail.error ? detail : null
  await refresh()
  selected.value = reports.value.find(r => r.id === detail.id) || selected.value
}
function recoverAudio() {
  if (!recovery.value?.audio) return
  const url = URL.createObjectURL(recovery.value.audio)
  const link = document.createElement('a'); link.href = url; link.download = 'unsaved-final-mix.wav'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const number = (value, unit = '') => typeof value === 'number' ? `${value.toFixed(2)}${unit}` : t('未测量', 'Not measured')
onMounted(() => { refresh(); window.addEventListener('session-report-ready', ready) })
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); window.removeEventListener('session-report-ready', ready) })
</script>
<template>
  <section class="session-reports" aria-labelledby="report-title">
    <header><h2 id="report-title">{{ t('会话报告', 'Session Reports') }}</h2><button :disabled="busy" @click="refresh">{{ t('刷新报告', 'Refresh Reports') }}</button></header>
    <p v-if="error" role="alert">{{ audioMessage(error) }}</p>
    <button v-if="recovery?.audio" @click="recoverAudio">{{ t('下载未保存的最终录音', 'Download Unsaved Recording') }}</button>
    <p v-if="!reports.length">{{ t('暂无会话记录', 'No session records yet') }}</p>
    <select v-else :value="selected?.id || ''" :aria-label="t('选择会话报告', 'Select session report')" @change="selected = reports.find(r => r.id === $event.target.value)">
      <option value="">{{ t('选择会话', 'Select a session') }}</option>
      <option v-for="report in reports" :key="report.id" :value="report.id">{{ report.experiment?.participant || '—' }} · {{ conditionText(report.experiment?.condition) }} #{{ report.experiment?.trial || 1 }} · {{ new Date(report.started_at_s * 1000).toLocaleString() }} · {{ report.metadata.mode === 'demo' ? t('演示', 'Demo') : t('真实设备', 'Device') }} · {{ reasonText(report.end_reason) }}</option>
    </select>
    <template v-if="selected">
      <h3>{{ t('EEG 与会话', 'EEG & Session') }}</h3>
      <p>{{ t('结束原因', 'End reason') }}: {{ reasonText(selected.end_reason) }} · {{ t('采集时长', 'Duration') }}: {{ number(selected.eeg_summary?.duration_s, ' s') }} · {{ t('收到数据', 'Received data') }}: {{ number(selected.received_seconds, ' s') }}</p>
      <p>{{ t('合格窗口比例', 'Qualified window ratio') }}: {{ number(selected.eeg_summary?.qualified_window_ratio == null ? null : selected.eeg_summary.qualified_window_ratio * 100, '%') }} · {{ t('丢包：未测量', 'Packet loss: not measured') }}</p>
      <details><summary>{{ t('窗口轨迹', 'Window Timeline') }}（{{ selected.windows.length }}）</summary>
        <div class="table-wrap"><table><thead><tr><th>EEG s</th><th>{{ t('质量', 'Quality') }}</th><th>{{ t('W / N1 / N2 分数', 'W / N1 / N2 scores') }}</th><th>{{ t('分类耗时', 'Classification time') }}</th></tr></thead>
          <tbody><tr v-for="window in selected.windows" :key="window.sequence"><td>{{ number(window.timestamp_s) }}</td><td>{{ number(window.signal_quality) }}</td><td>{{ window.probabilities || t('不可用', 'Unavailable') }}</td><td>{{ number(window.classification_ms, ' ms') }}</td></tr></tbody></table></div>
      </details>
      <h3>{{ t('音乐变化与输出', 'Music Changes & Output') }}</h3>
      <p>{{ t('最终混音录音', 'Final Mix Recording') }}: {{ selected.browser?.recording_status || t('尚未上传 / 浏览器未录音', 'Not uploaded / not recorded') }} · {{ number(selected.browser?.recorded_seconds, ' s') }}</p>
      <audio v-if="selected.audio" controls :src="`${api}${selected.audio.url}`" />
      <p v-if="selected.audio"><a :href="`${api}${selected.audio.url}`">{{ t('下载最终混音 WAV', 'Download Final Mix WAV') }}</a> · {{ t('响度跳变候选', 'RMS jump candidates') }}: {{ selected.audio.metrics.rms_jump_candidates.length }}</p>
      <h3>{{ t('自动音频指标', 'Automatic Audio Metrics') }}</h3>
      <p>RMS: {{ number(audioSummary.rms, ' dBFS') }} · {{ t('频谱质心', 'Spectral centroid') }}: {{ number(audioSummary.centroid, ' Hz') }} · {{ t('≥8kHz 能量比例', 'Energy ratio ≥8kHz') }}: {{ number(selected.audio?.metrics.sample_rate_hz > 16000 ? audioSummary.high : null) }}</p>
      <p>{{ t('削波样本数', 'Clipped samples') }}: {{ number(audioSummary.clipped) }} · {{ t('播放错误数', 'Playback errors') }}: {{ selected.browser ? selected.browser.events.filter(e => e.type === 'playback-error').length : t('未测量', 'Not measured') }} · {{ t('分析录音时长', 'Analyzed recording') }}: {{ number(audioSummary.duration, ' s') }}</p>
      <p>{{ t('完整性', 'Completeness') }}: {{ selected.browser?.recording_status === 'partial_memory_limit' ? t('容量限制：部分录音', 'Memory limit: partial recording') : selected.audio ? t('已有录音；全程覆盖尚未验证', 'Recording available; whole-session coverage not verified') : t('无可用音频', 'No available audio') }}</p>
      <h3>{{ t('AI辅助音乐评价（探索性，非参与者评分）', 'AI Music Evaluation (Exploratory, Not Participant Ratings)') }}</h3>
      <p>{{ t('评价状态', 'Evaluation status') }}: {{ selected.ai_music_evaluation?.status || 'unavailable' }} · {{ selected.ai_music_evaluation?.reason || '' }}</p>
      <p v-for="[key, label] in aiScores" :key="key">{{ label }} (1–7): {{ number(selected.ai_music_evaluation?.scores?.[key]) }}</p>
      <p v-if="selected.ai_music_evaluation?.model">{{ selected.ai_music_evaluation.model }} · {{ selected.ai_music_evaluation.model_version }} · {{ selected.ai_music_evaluation.method }}</p>
      <h3>SongEval · {{ t('音乐美学（探索性 1–5）', 'Music Aesthetics (Exploratory 1–5)') }}</h3>
      <p>{{ selected.songeval?.status || 'unavailable' }} · {{ selected.songeval?.reason || '' }}</p>
      <p v-for="[key,label] in songScores" :key="key">{{ label }}: {{ number(selected.songeval?.status === 'completed' ? selected.songeval?.scores?.[key] : null) }}</p>
      <p>{{ selected.songeval?.model_version || '—' }} · {{ selected.songeval?.coverage_scope || '—' }} · {{ number(selected.songeval?.analyzed_audio_seconds, ' s') }}</p>
      <p>{{ t('BPM、起音密度、调性、和弦、真峰值：尚未实现可靠估计', 'BPM, onset density, key, chords and true peak: reliable estimation not implemented') }}</p>
      <details v-if="selected.browser"><summary>{{ t('播放与控制时间线', 'Playback & Control Timeline') }}（{{ selected.browser.events.length }}）</summary><pre>{{ JSON.stringify(selected.browser.events, null, 2) }}</pre></details>
      <details v-if="selected.trace?.length"><summary>{{ t('EEG → 控制 → 附近音频证据', 'EEG → Control → Nearby Audio Evidence') }}（{{ selected.trace.length }}）</summary><pre>{{ JSON.stringify(selected.trace, null, 2) }}</pre></details>
      <h3>{{ t('程序性能', 'Runtime Performance') }}</h3>
      <p>{{ t('分类耗时与浏览器调度见窗口和时间线；远端排队 / 推理耗时、硬件输出延迟、耳位声压未测量。', 'See windows and timeline for classification timing and browser scheduling. Remote queue/inference time, hardware latency and ear-level SPL are not measured.') }}</p>
      <p>{{ t('软件风险筛查不能证明“没有刺耳声音”，舒适性仍需盲听。演示记录不代表睡眠结果；合格窗口比例不是有效采集时长比例。', 'Risk screens cannot establish absence of harsh sounds; blinded comfort ratings are still needed. Demo records are not sleep outcomes. Qualified windows are not valid-duration coverage.') }}</p>
      <button @click="download">{{ t('下载完整报告 JSON', 'Download Full Report JSON') }}</button>
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
button { border:1px solid #cbd7d2; padding:8px 12px; border-radius:6px; color:#264938; background:#f4f7f6; }
</style>
