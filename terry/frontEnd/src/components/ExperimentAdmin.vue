<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { text as t, language } from '../i18n.js'
import ExperimentCharts from './ExperimentCharts.vue'
import EegPowerShifts from './EegPowerShifts.vue'
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const rows = ref([]), storage = ref(''), error = ref(''), busy = ref(false)
const includeDemo = ref(false), participant = ref(''), condition = ref('all'), selected = ref(null)
const selectedIds = ref([]), selectedReport = ref(null), labelForm = ref(null)
watch([participant, condition, includeDemo], () => { selectedIds.value = []; selected.value = null })
const analysisVersion = ref(0)
const protocolReady = ref(false)
const songReady = ref(false), songConsent = ref(false)
let pollTimer = null, disposed = false
const protocolDefaults = () => ({ visit:null, sequence:'', trial_status:'unreviewed', condition_verified:false,
  protocol_version:'', sham_trajectory_id:'', baseline_start_s:null, baseline_end_s:null,
  intervention_start_s:null, intervention_end_s:null, lseq_gts_items:[null,null,null],
  relaxation_vas:null, sleep_difficulty_vas:null, kss_before:null, kss_after:null, sus_items:Array(10).fill(null), transition_naturalness_vas:null,
  prior_sleep_hours:null, caffeine_mg:null, medication_notes:'', adverse_event:'',
  sound_pressure_dba:null, audio_material_id:'', motion_threshold:null, motion_max_gap_s:2 })
const protocolNumbers = computed(() => [
  ['baseline_start_s', t('基线开始（会话秒）', 'Baseline start (session s)'),0,null],
  ['baseline_end_s', t('基线结束（会话秒）', 'Baseline end (session s)'),0,null],
  ['intervention_start_s', t('实验开始（会话秒）', 'Intervention start (session s)'),0,null],
  ['intervention_end_s', t('实验结束（会话秒）', 'Intervention end (session s)'),0,null],
  ['relaxation_vas', t('放松 VAS 0–10', 'Relaxation VAS 0–10'),0,10],
  ['sleep_difficulty_vas', t('入睡困难 VAS 0–10（补充）', 'Sleep difficulty VAS 0–10 (supplemental)'),0,10],
  ['kss_before', t('实验前 KSS 1–9', 'Pre-session KSS 1–9'),1,9],
  ['kss_after', t('实验后 KSS 1–9', 'Post-session KSS 1–9'),1,9],
  ['transition_naturalness_vas', t('过渡自然度 VAS 0–10（非 SUS）', 'Transition naturalness VAS 0–10 (not SUS)'),0,10],
  ['prior_sleep_hours', t('前一晚睡眠（小时）', 'Prior sleep (hours)'),0,24],
  ['caffeine_mg', t('咖啡因摄入 mg', 'Caffeine mg'),0,2000],
  ['sound_pressure_dba', t('耳位实测声压 dBA', 'Measured ear-level SPL dBA'),0,140],
  ['motion_threshold', t('预设低活动阈值', 'Prespecified low-motion threshold'),0,null],
  ['motion_max_gap_s', t('活动采样最大间隔 s', 'Maximum motion sample gap s'),.01,60],
])
const form = ref({ participant: '', condition: 'unassigned', trial: 1, notes: '', comfort: null, musicality: null })
const conditions = computed(() => ({ unassigned: t('未分组', 'Unassigned'), fixed: t('固定音乐', 'Fixed music'), sham: t('伪闭环', 'Sham loop'), closed_loop: t('真闭环', 'Closed loop') }))
const metrics = computed(() => [
  ['duration_s', t('会话时长 (s)', 'Session duration (s)')],
  ['qualified_window_ratio', t('合格窗口比例', 'Qualified window ratio')],
  ['classification_ms', t('分类耗时 (ms)', 'Classification time (ms)')],
  ['backend_cpu_mean_percent', t('后端平均 CPU（单核=100%）', 'Backend mean CPU (100% per core)')],
  ['backend_process_peak_rss_mb', t('后端进程生命周期峰值内存 MiB', 'Backend lifetime peak RSS MiB')],
  ['kss_change', t('KSS 后 − 前', 'KSS post − pre')],
  ['lseq_gts', 'LSEQ GTS (0–100)'],
  ['relaxation_vas', t('放松 VAS', 'Relaxation VAS')],
  ['sleep_difficulty_vas', t('入睡困难 VAS', 'Sleep difficulty VAS')],
  ['sus_score', 'SUS (0–100)'],
  ['transition_naturalness_vas', t('过渡自然度 VAS', 'Transition naturalness VAS')],
  ['minimal_motion_latency_s', t('连续5分钟低活动潜伏期 (s)', 'Five-minute low-motion latency (s)')],
  ['alpha_8_12_power_uv2', t('α 8–12 Hz 功率 (μV²)', 'Alpha 8–12 Hz power (μV²)')],
  ['alpha_8_12_change_uv2', t('α 8–12 Hz 功率 实验 − 基线', 'Alpha 8–12 Hz power intervention − baseline')],
  ['theta_change_uv2', t('θ 功率 实验 − 基线', 'Theta power intervention − baseline')],
  ['alpha_relative_change', t('α 相对功率变化（1–30 Hz 分母）', 'Alpha relative power change (1–30 Hz denominator)')],
  ['theta_relative_change', t('θ 相对功率变化（1–30 Hz 分母）', 'Theta relative power change (1–30 Hz denominator)')],
  ['rms_change_db', t('平均绝对 RMS 变化 dB', 'Mean absolute RMS change dB')],
  ['fallback_proportion', t('已观测控制时段回退比例', 'Observed control fallback proportion')],
  ['alpha_power_uv2', t('α 8–13 Hz 功率（旧口径，μV²）', 'Alpha 8–13 Hz power (legacy, μV²)')],
  ['theta_power_uv2', t('θ 功率 (μV²)', 'Theta power (μV²)')],
  ['beta_power_uv2', t('β 功率 (μV²)', 'Beta power (μV²)')],
  ['recorded_seconds', t('录音时长 (s)', 'Recorded duration (s)')],
  ['analyzed_audio_seconds', t('分析音频时长 (s)', 'Analyzed audio duration (s)')],
  ['recording_session_duration_ratio', t('录音／会话时长比（非完整性证明）', 'Recording/session duration ratio (not verified coverage)')],
  ['rms_dbfs', t('平均分块 RMS (dBFS，非 LUFS)', 'Mean block RMS (dBFS, not LUFS)')],
  ['centroid_hz', t('频谱质心 (Hz)', 'Spectral centroid (Hz)')],
  ['high_frequency_ratio', t('≥8kHz 能量比例', 'Energy ratio ≥8kHz')],
  ['sample_peak_dbfs', t('样本峰值 (dBFS)', 'Sample peak (dBFS)')],
  ['clipped_samples', t('过载样本数', 'Overload samples')],
  ['rms_jump_candidates', t('RMS 跳变候选', 'RMS jump candidates')],
  ['control_events', t('控制事件数', 'Control events')],
  ['playback_errors', t('播放错误数', 'Playback errors')],
  ['download_ms', t('下载耗时 (ms)', 'Download time (ms)')],
  ['decode_ms', t('解码耗时 (ms)', 'Decode time (ms)')],
  ['comfort', t('舒适度（主观 1–7）', 'Comfort (subjective 1–7)')],
  ['musicality', t('音乐性（主观 1–7）', 'Musicality (subjective 1–7)')],
  ['ai_pleasantness', t('AI悦耳度（探索性 1–7）', 'AI pleasantness (exploratory 1–7)')],
  ['ai_coherence', t('AI连贯性（探索性 1–7）', 'AI coherence (exploratory 1–7)')],
  ['ai_transition_naturalness', t('AI变化自然度（探索性 1–7）', 'AI transition naturalness (exploratory 1–7)')],
  ['songeval_coherence', t('SongEval 整体连贯性（1–5）', 'SongEval coherence (1–5)')],
  ['songeval_musicality', t('SongEval 整体音乐性（1–5）', 'SongEval musicality (1–5)')],
  ['songeval_memorability', t('SongEval 记忆性（1–5）', 'SongEval memorability (1–5)')],
  ['songeval_structure_clarity', t('SongEval 结构清晰度（1–5）', 'SongEval structure clarity (1–5)')],
  ['songeval_vocal_naturalness', t('SongEval 歌声呼吸／乐句自然性（1–5）', 'SongEval vocal naturalness (1–5)')],
])
const filtered = computed(() => rows.value.filter(r => r.ended && (includeDemo.value || r.mode === 'brainflow') &&
  (!participant.value || r.participant?.toLocaleLowerCase().includes(participant.value.trim().toLocaleLowerCase())) && (condition.value === 'all' || r.condition === condition.value)))
const analysisRows = computed(() => selectedIds.value.length ? filtered.value.filter(r => selectedIds.value.includes(r.id)) : filtered.value)
const songMetrics = computed(() => metrics.value.filter(([key]) => key.startsWith('songeval_')))
const participants = computed(() => [...new Set(rows.value.map(r => r.participant).filter(Boolean))].sort())
const groups = computed(() => Object.keys(conditions.value).map(key => ({ key, rows: analysisRows.value.filter(r => r.condition === key) })))
const value = n => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : t('未测量', 'Not measured')
function stats(group, key) {
  const values = group.map(r => r[key]).filter(v => typeof v === 'number' && Number.isFinite(v))
  if (!values.length) return t('未测量', 'Not measured')
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const sd = values.length > 1 ? Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / (values.length - 1)) : null
  return `${mean.toFixed(2)}${sd === null ? '' : ` ± ${sd.toFixed(2)}`} (n=${values.length})`
}
function paired(key, comparator) {
  const differences = []
  for (const id of new Set(analysisRows.value.map(r => r.participant).filter(Boolean))) {
    const mean = condition => {
      const values = analysisRows.value.filter(r => r.participant === id && r.condition === condition)
        .map(r => r[key]).filter(v => typeof v === 'number' && Number.isFinite(v))
      return values.length ? values.reduce((a,b) => a+b, 0)/values.length : null
    }
    const active = mean('closed_loop'), control = mean(comparator)
    if (active !== null && control !== null) differences.push({ difference: active-control })
  }
  return stats(differences, 'difference')
}
async function refresh() {
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`${api}/api/session-reports/experiments/summary`, { cache: 'no-store' })
    if (!response.ok) throw new Error(t('实验接口不可用，请重启后端', 'Experiment API unavailable; restart backend'))
    const data = await response.json()
    if (rows.value.some(row => ['running', 'queued'].includes(row.songeval_status) &&
        data.rows.find(next => next.id === row.id)?.songeval_status === 'completed')) analysisVersion.value++
    rows.value = data.rows; storage.value = data.storage
    protocolReady.value = data.protocol_analysis_version === 1
    songReady.value = data.songeval_version === 1
  } catch (e) { error.value = e.message } finally {
    busy.value = false
    clearTimeout(pollTimer)
    if (!disposed) {
      pollTimer = setTimeout(refresh, 5000)
    }
  }
}
async function select(row) {
  if (busy.value) return
  error.value = ''; selected.value = null; busy.value = true
  try {
    const response = await fetch(`${api}/api/session-reports/${row.id}`)
    if (!response.ok) throw new Error(t('读取失败', 'Failed to load'))
    const report = await response.json()
    selectedReport.value = report
    form.value = { ...protocolDefaults(), participant: '', condition: 'unassigned', trial: 1, notes: '', comfort: null, musicality: null, ...report.experiment }
    selected.value = row
    await nextTick()
    labelForm.value?.scrollIntoView({behavior:'smooth',block:'start'})
  } catch (e) { error.value = e.message; selected.value = null } finally { busy.value = false }
}
async function save() {
  if (!protocolReady.value) { error.value = t('当前后端尚未加载实验分析更新，请结束采集后重启后端再保存', 'Backend update not loaded; restart after acquisition ends before saving'); return }
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`${api}/api/session-reports/${selected.value.id}/experiment`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.fromEntries(Object.entries(form.value).map(([key,value]) => [key,
        ['lseq_gts_items','sus_items'].includes(key) ? value.map(v => v === '' ? null : v) :
        [...protocolNumbers.value.map(v=>v[0]),'comfort','musicality','visit'].includes(key) && value === '' ? null : value]))) })
    if (!response.ok) {
      const body = await response.json()
      const detail = Array.isArray(body.detail) ? body.detail.map(e => e.msg).join('; ') : body.detail
      throw new Error(detail || t('保存失败，请检查编号和评分范围', 'Save failed; check ID and score ranges'))
    }
    selected.value = null; analysisVersion.value++; await refresh()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function importPhysiology(event) {
  const file = event.target.files?.[0]
  if (!file || !selected.value) return
  if (!protocolReady.value) { error.value = t('当前后端尚未加载实验分析更新，请结束采集后重启后端再导入', 'Backend update not loaded; restart after acquisition ends before importing'); event.target.value = ''; return }
  error.value = ''; busy.value = true
  try {
    if (file.size > 5*1024*1024) throw new Error(t('文件超过 5 MB', 'File exceeds 5 MB'))
    const response = await fetch(`${api}/api/session-reports/${selected.value.id}/physiology`, {method:'PUT',headers:{'Content-Type':'text/csv'},body:file})
    if (!response.ok) { const body=await response.json(); throw new Error(body.detail || 'Import failed') }
    analysisVersion.value++; await refresh()
  } catch(e) { error.value=e.message } finally { busy.value=false; event.target.value='' }
}
function reportReady() { analysisVersion.value++; refresh() }
onMounted(() => { refresh(); window.addEventListener('session-report-ready', reportReady) })
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); window.removeEventListener('session-report-ready', reportReady) })
async function evaluateSong(row) {
  if (!songReady.value) { error.value = t('请结束采集后重启后端，加载 SongEval 接口', 'Restart backend after acquisition ends to load SongEval'); return }
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`${api}/api/session-reports/${row.id}/songeval`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({send_audio_to_server:songConsent.value})})
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail || 'SongEval failed') }
    await refresh()
  } catch(e) { error.value=e.message } finally { busy.value=false }
}
</script>
<template>
  <section class="experiment-admin">
    <header><h2>{{ t('实验数据分析', 'Experiment Analysis') }}</h2><div><button :disabled="busy" @click="refresh">{{ t('刷新', 'Refresh') }}</button> <a :href="`${api}/api/session-reports/experiments/export.csv`">{{ t('导出全部 CSV', 'Export All CSV') }}</a></div></header>
    <p class="storage">{{ t('本地保存目录', 'Local storage') }}: <code>{{ storage }}</code></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="filters">
      <label>{{ t('搜索受试者', 'Search participant') }}<input v-model="participant" type="search" list="experiment-participants" :placeholder="t('姓名或编号', 'Name or ID')" /><datalist id="experiment-participants"><option v-for="id in participants" :key="id" :value="id" /></datalist></label>
      <label>{{ t('实验条件', 'Condition') }}<select v-model="condition" :aria-label="t('实验条件', 'Condition')"><option value="all">{{ t('全部', 'All') }}</option><option v-for="(name, key) in conditions" :key="key" :value="key">{{ name }}</option></select></label>
      <label><input v-model="includeDemo" type="checkbox" /> {{ t('包含演示／非设备记录', 'Include demo / non-device records') }}</label>
      <strong>{{ filtered.length }} {{ t('已结束会话', 'completed sessions') }}</strong>
      <span v-if="selectedIds.length">{{ selectedIds.length }} {{ t('条已选择', 'selected') }} <button @click="selectedIds=[]">{{ t('清除选择', 'Clear selection') }}</button></span>
    </div>
    <div class="table-wrap session-list"><table><thead><tr><th>{{ t('选择', 'Select') }}</th><th>{{ t('会话', 'Session') }}</th><th>{{ t('参与者', 'Participant') }}</th><th>{{ t('条件／次数', 'Condition / trial') }}</th><th>{{ t('访问／顺序', 'Visit / sequence') }}</th><th>{{ t('审核状态', 'Review status') }}</th><th>{{ t('时长 s', 'Duration s') }}</th><th>{{ t('合格比例', 'Qualified ratio') }}</th><th>{{ t('录音', 'Recording') }}</th><th></th></tr></thead><tbody>
      <tr v-for="row in filtered" :key="row.id"><td><input v-model="selectedIds" type="checkbox" :value="row.id" :aria-label="`${t('选择记录','Select record')} ${row.id.slice(0,8)}`" /></td><td>{{ new Date(row.started_at_s * 1000).toLocaleString(language === 'en' ? 'en-US' : 'zh-CN') }}<small>{{ row.mode }} · {{ row.id.slice(0, 8) }}</small></td><td>{{ row.participant || '—' }}</td><td>{{ conditions[row.condition] }} · #{{ row.trial || 1 }}</td><td>{{ row.visit || '—' }} / {{ row.sequence || '—' }}</td><td>{{ row.trial_status || 'unreviewed' }}<small>{{ row.condition_verified ? t('条件已核验', 'Condition verified') : t('条件未核验', 'Condition unverified') }}</small></td><td>{{ value(row.duration_s) }}</td><td>{{ value(row.qualified_window_ratio) }}</td><td>{{ row.music_source === 'external' ? t('外部播放 · 无本机录音','External playback · no local audio') : row.recording_status || t('无录音', 'No recording') }}</td><td><button :disabled="busy" @click="select(row)">{{ t('查看／标注', 'View / Label') }}</button></td></tr>
    </tbody></table></div>
    <p v-if="!filtered.length">{{ t('当前筛选下暂无已结束会话', 'No completed sessions match these filters') }}</p>
    <p v-if="!includeDemo && rows.some(row => row.ended && row.mode !== 'brainflow')">{{ t('演示记录已隐藏', 'Demo sessions hidden') }}</p>
    <EegPowerShifts :rows="analysisRows" :conditions="conditions" :busy="busy" @label="select" />
    <h3>{{ t('所选记录指标', 'Selected Record Metrics') }}</h3>
    <div class="table-wrap record-comparison"><table><thead><tr><th>{{ t('指标','Metric') }}</th><th v-for="row in analysisRows" :key="row.id">{{ row.participant }} · {{ conditions[row.condition] }} #{{ row.trial || 1 }}<small>{{ row.id.slice(0,8) }}</small></th></tr></thead><tbody><tr v-for="[key,name] in metrics" :key="key"><th>{{ name }}</th><td v-for="row in analysisRows" :key="row.id">{{ value(row[key]) }}</td></tr></tbody></table></div>
    <ExperimentCharts :key="analysisVersion" :record-ids="analysisRows.map(r=>r.id)" :filter-active="true" />
    <h3>{{ t('音频完整性与AI评价来源', 'Audio Completeness & AI Provenance') }}</h3>
    <div class="table-wrap"><table><thead><tr><th>{{ t('会话', 'Session') }}</th><th>{{ t('录音完整性', 'Recording completeness') }}</th><th>{{ t('AI状态', 'AI status') }}</th><th>{{ t('模型／版本', 'Model / version') }}</th><th>{{ t('方法／未评价原因', 'Method / unavailable reason') }}</th></tr></thead><tbody>
      <tr v-for="row in analysisRows" :key="row.id"><td>{{ row.id.slice(0,8) }}</td><td>{{ row.recording_completeness }}</td><td>{{ row.ai_evaluation_status }}</td><td>{{ row.ai_model || '—' }} {{ row.ai_model_version || '' }}</td><td>{{ row.ai_method || row.ai_evaluation_reason }}</td></tr>
    </tbody></table></div>
    <h3>SongEval · {{ t('音乐美学', 'Music Aesthetics') }}</h3>
    <label><input v-model="songConsent" type="checkbox" /> {{ t('允许将最终混音音频发送至指定服务器（不含 EEG／问卷）', 'Allow final-mix audio to be sent to the designated server (no EEG / questionnaires)') }}</label>
    <div class="table-wrap"><table><thead><tr><th>{{ t('会话', 'Session') }}</th><th>{{ t('状态', 'Status') }}</th><th>{{ t('模型版本', 'Model version') }}</th><th>{{ t('分析范围', 'Analyzed scope') }}</th><th>{{ t('原因', 'Reason') }}</th><th></th></tr></thead><tbody><tr v-for="row in analysisRows" :key="row.id"><td>{{ row.id.slice(0,8) }}</td><td>{{ row.songeval_status || 'unavailable' }}</td><td>{{ row.songeval_model_version?.slice(0,12) || '—' }}</td><td>{{ row.songeval_coverage_scope || '—' }}<small>{{ value(row.songeval_analyzed_seconds) }} s</small></td><td>{{ row.songeval_reason || '—' }}</td><td><button :disabled="busy || !songConsent || !row.analyzed_audio_seconds || row.songeval_status==='running'" @click="evaluateSong(row)">{{ t('SongEval 评估', 'Evaluate SongEval') }}</button></td></tr></tbody></table></div>
    <div class="table-wrap song-scores"><table><thead><tr><th>{{ t('会话', 'Session') }}</th><th>{{ t('参与者', 'Participant') }}</th><th>{{ t('条件', 'Condition') }}</th><th v-for="[key,label] in songMetrics" :key="key">{{ label }}</th></tr></thead><tbody><tr v-for="row in analysisRows" :key="row.id"><td>{{ row.id.slice(0,8) }}</td><td>{{ row.participant || '—' }}</td><td>{{ conditions[row.condition] }}</td><td v-for="[key] in songMetrics" :key="key">{{ value(row.songeval_status === 'completed' ? row[key] : null) }}</td></tr></tbody></table></div>
    <form v-if="selected" ref="labelForm" class="label-form" @submit.prevent="save">
      <h3>{{ t('会话实验标注', 'Session Labels') }} · {{ selected.id.slice(0, 8) }}</h3>
      <div class="record-downloads"><a :href="`${api}/api/session-reports/${selected.id}`" target="_blank" rel="noopener">{{ t('完整 EEG 报告 JSON','Full EEG report JSON') }}</a><a v-if="selectedReport?.audio" :href="`${api}${selectedReport.audio.url}`">{{ t('最终混音 WAV','Final mix WAV') }}</a></div>
      <div v-if="selectedReport?.raw_recording" class="storage">{{ t('原始 EEG 目录', 'Raw EEG directory') }}: <code>{{ selectedReport.raw_recording.path }}</code><p v-if="selectedReport.raw_recording.error" role="alert">{{ selectedReport.raw_recording.error }}</p></div>
      <label>{{ t('受试者姓名或编号', 'Participant name or ID') }}<input v-model="form.participant" maxlength="64" placeholder="P001" /></label>
      <label>{{ t('实际执行的条件', 'Condition actually performed') }}<select v-model="form.condition" :disabled="!!selected.execution_version"><option v-for="(name,key) in conditions" :key="key" :value="key">{{ name }}</option></select></label>
      <label>{{ t('重复序号', 'Trial number') }}<input v-model.number="form.trial" type="number" min="1" max="10000" required /></label>
      <label>{{ t('访问序号 1–3', 'Visit 1–3') }}<input v-model.number="form.visit" type="number" min="1" max="3" /></label>
      <label>{{ t('随机分配顺序', 'Allocated sequence') }}<select v-model="form.sequence"><option value="">—</option><option v-for="s in ['ABC','ACB','BAC','BCA','CAB','CBA']" :key="s">{{ s }}</option></select></label>
      <label>{{ t('实验记录状态', 'Trial status') }}<select v-model="form.trial_status"><option value="unreviewed">{{ t('待审核', 'Unreviewed') }}</option><option value="completed">{{ t('已完成', 'Completed') }}</option><option value="interrupted">{{ t('中断', 'Interrupted') }}</option><option value="withdrawn">{{ t('退出', 'Withdrawn') }}</option><option value="excluded">{{ t('排除', 'Excluded') }}</option></select></label>
      <label><input v-model="form.condition_verified" type="checkbox" /> {{ t('实际播放条件已核验', 'Actual playback condition verified') }}</label>
      <label v-for="[key,name,min,max] in protocolNumbers" :key="key">{{ name }}<input v-model.number="form[key]" type="number" :min="min" :max="max" :step="key.startsWith('kss') ? 1 : 'any'" /></label>
      <label v-for="i in 3" :key="`gts${i}`">LSEQ GTS {{ i }} (0–100)<input v-model.number="form.lseq_gts_items[i-1]" type="number" min="0" max="100" step="any" /></label>
      <label v-for="i in 10" :key="`sus${i}`">SUS {{ i }} (1–5)<input v-model.number="form.sus_items[i-1]" type="number" min="1" max="5" step="1" /></label>
      <label>{{ t('协议版本', 'Protocol version') }}<input v-model="form.protocol_version" maxlength="100" /></label>
      <label>{{ t('冻结音频材料编号', 'Frozen audio material ID') }}<input v-model="form.audio_material_id" maxlength="100" /></label>
      <label>{{ t('伪闭环轨迹编号', 'Sham trajectory ID') }}<input v-model="form.sham_trajectory_id" maxlength="100" /></label>
      <label>{{ t('用药记录（不含身份信息）', 'Medication notes (no identifying information)') }}<textarea v-model="form.medication_notes" maxlength="500" /></label>
      <label>{{ t('不适／不良事件', 'Discomfort / adverse events') }}<textarea v-model="form.adverse_event" maxlength="500" /></label>
      <label>{{ t('导入已对齐体动 CSV', 'Import aligned motion CSV') }}<input type="file" accept=".csv" :disabled="busy" @change="importPhysiology" /></label>
      <label>{{ t('盲听舒适度 1–7（可留空）', 'Blinded comfort 1–7 (optional)') }}<input v-model.number="form.comfort" type="number" min="1" max="7" step="1" /></label>
      <label>{{ t('盲听音乐性 1–7（可留空）', 'Blinded musicality 1–7 (optional)') }}<input v-model.number="form.musicality" type="number" min="1" max="7" step="1" /></label>
      <label>{{ t('协议／异常备注（不填写个人信息）', 'Protocol / deviations (no personal information)') }}<textarea v-model="form.notes" maxlength="2000" /></label>
      <div><button :disabled="busy" type="submit">{{ t('保存标注', 'Save Labels') }}</button> <button type="button" @click="selected=null">{{ t('取消', 'Cancel') }}</button></div>
    </form>
    <h3>{{ t('会话级工程描述统计 · 均值 ± 样本标准差', 'Session-Level Engineering Statistics · Mean ± Sample SD') }}</h3>
    <div class="table-wrap"><table><thead><tr><th>{{ t('指标', 'Metric') }}</th><th v-for="group in groups" :key="group.key">{{ conditions[group.key] }} ({{ group.rows.length }})</th></tr></thead><tbody><tr v-for="[key, name] in metrics" :key="key"><th>{{ name }}</th><td v-for="group in groups" :key="group.key">{{ stats(group.rows, key) }}</td></tr></tbody></table></div>
    <h3>{{ t('参与者内配对差值', 'Within-Participant Paired Differences') }}</h3>
    <p>{{ t('每位参与者每种条件先取重复试验均值，n 为同时具有两种条件有效数据的参与者数。正值仅代表数值增加，不一定代表更好。', 'Repeated trials are averaged per participant and condition. n counts participants with valid data in both conditions. Positive differences indicate an increase, not necessarily improvement.') }}</p>
    <div class="table-wrap"><table><thead><tr><th>{{ t('指标', 'Metric') }}</th><th>{{ t('真闭环 − 固定', 'Closed Loop − Fixed') }}</th><th>{{ t('真闭环 − 伪闭环', 'Closed Loop − Sham') }}</th></tr></thead><tbody><tr v-for="[key,name] in metrics" :key="key"><th>{{ name }}</th><td>{{ paired(key, 'fixed') }}</td><td>{{ paired(key, 'sham') }}</td></tr></tbody></table></div>
    <p>{{ t('下方差值为描述统计，包含未审核记录，不自动宣称显著性或助眠效果。正式三条件分析仅纳入已完成并核验条件的设备会话。新记录的实际执行条件不可事后更改；旧记录的标签不能证明实际播放条件。', 'Descriptive differences include unreviewed records and do not establish significance or sleep benefit. Formal three-condition analysis includes only completed, verified hardware sessions. Executed conditions are immutable for new records; legacy labels do not prove playback conditions.') }}</p>
    <p>{{ t('合格比例是重叠窗口比例；RMS 不是 LUFS，样本峰值不是真峰值。≥8kHz 比例受采样率影响，低于 16kHz 的录音不可比较。削波与跳变只是风险线索；BPM、和弦、调式、实际扬声器延迟与声压尚未测量。主观评分单独记录。', 'Qualification is an overlapping-window ratio. RMS is not LUFS; sample peak is not true peak. ≥8kHz energy depends on sample rate; recordings below 16kHz are not comparable. Overload and jumps are risk screens only. BPM, chords, mode, speaker latency and SPL remain unmeasured. Subjective scores are recorded separately.') }}</p>
  </section>
</template>
<style scoped>
.filters input[type="search"] { display:block; margin-top:6px; width:220px; }
.record-comparison { max-height:520px; }
.record-comparison th:first-child { position:sticky; left:0; max-width:190px; white-space:normal; min-width:140px; }
.record-downloads { display:flex; flex-wrap:wrap; gap:16px; }
.participant-button { overflow-wrap:anywhere; }
.experiment-admin { padding: 20px 0; } header { display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; } h2 { font-size:20px; } h3 { font-size:16px; margin:24px 0 12px; } p { font-size:13px; line-height:1.7; } .storage { overflow-wrap:anywhere; } .filters { display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin:20px 0; } label { font-size:13px; } select,input,textarea { max-width:100%; } .filters select,.label-form input,.label-form select,.label-form textarea { display:block; margin-top:6px; } .table-wrap { overflow:auto; } table { border-collapse:collapse; width:100%; font-size:12px; } td,th { text-align:left; padding:10px; border-bottom:1px solid #d9e0df; white-space:nowrap; } th { background:#f0f4f3; } small { display:block; color:#65746e; margin-top:4px; } .label-form { border-top:1px solid #ccd7d0; border-bottom:1px solid #ccd7d0; padding:16px 0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .label-form h3,.label-form>div { grid-column:1/-1; } textarea { width:100%; min-height:72px; } button { border:1px solid #cbd7d2; padding:8px 12px; border-radius:6px; color:#264938; background:#f4f7f6; } @media(max-width:640px) { .label-form { grid-template-columns:1fr; } }
</style>
