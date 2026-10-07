<script setup>
import { computed, onMounted, ref } from 'vue'
import { text as t, language } from '../i18n.js'
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const rows = ref([]), storage = ref(''), error = ref(''), busy = ref(false)
const includeDemo = ref(false), participant = ref(''), condition = ref('all'), selected = ref(null)
const form = ref({ participant: '', condition: 'unassigned', trial: 1, notes: '', comfort: null, musicality: null })
const conditions = computed(() => ({ unassigned: t('未分组', 'Unassigned'), fixed: t('固定音乐', 'Fixed music'), sham: t('伪闭环', 'Sham loop'), closed_loop: t('真闭环', 'Closed loop') }))
const metrics = computed(() => [
  ['duration_s', t('会话时长 (s)', 'Session duration (s)')],
  ['qualified_window_ratio', t('合格窗口比例', 'Qualified window ratio')],
  ['classification_ms', t('分类耗时 (ms)', 'Classification time (ms)')],
  ['alpha_power_uv2', t('α 功率 (μV²)', 'Alpha power (μV²)')],
  ['theta_power_uv2', t('θ 功率 (μV²)', 'Theta power (μV²)')],
  ['beta_power_uv2', t('β 功率 (μV²)', 'Beta power (μV²)')],
  ['recorded_seconds', t('录音时长 (s)', 'Recorded duration (s)')],
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
])
const filtered = computed(() => rows.value.filter(r => r.ended && (includeDemo.value || r.mode === 'brainflow') &&
  (!participant.value || r.participant === participant.value) && (condition.value === 'all' || r.condition === condition.value)))
const participants = computed(() => [...new Set(rows.value.map(r => r.participant).filter(Boolean))].sort())
const groups = computed(() => Object.keys(conditions.value).map(key => ({ key, rows: filtered.value.filter(r => r.condition === key) })))
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
  for (const id of new Set(filtered.value.map(r => r.participant).filter(Boolean))) {
    const mean = condition => {
      const values = filtered.value.filter(r => r.participant === id && r.condition === condition)
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
    const data = await response.json(); rows.value = data.rows; storage.value = data.storage
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function select(row) {
  if (busy.value) return
  error.value = ''; selected.value = null; busy.value = true
  try {
    const response = await fetch(`${api}/api/session-reports/${row.id}`)
    if (!response.ok) throw new Error(t('读取失败', 'Failed to load'))
    const report = await response.json()
    form.value = { participant: '', condition: 'unassigned', trial: 1, notes: '', comfort: null, musicality: null, ...report.experiment }
    selected.value = row
  } catch (e) { error.value = e.message; selected.value = null } finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`${api}/api/session-reports/${selected.value.id}/experiment`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form.value, comfort: form.value.comfort === '' ? null : form.value.comfort, musicality: form.value.musicality === '' ? null : form.value.musicality }) })
    if (!response.ok) throw new Error(t('保存失败，请检查编号和评分范围', 'Save failed; check ID and score ranges'))
    selected.value = null; await refresh()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(refresh)
</script>
<template>
  <section class="experiment-admin">
    <header><h2>{{ t('实验数据分析', 'Experiment Analysis') }}</h2><div><button :disabled="busy" @click="refresh">{{ t('刷新', 'Refresh') }}</button> <a :href="`${api}/api/session-reports/experiments/export.csv`">{{ t('导出全部 CSV', 'Export All CSV') }}</a></div></header>
    <p class="storage">{{ t('本地保存目录', 'Local storage') }}: <code>{{ storage }}</code></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="filters">
      <label>{{ t('匿名参与者', 'Anonymous participant') }}<select v-model="participant"><option value="">{{ t('全部', 'All') }}</option><option v-for="id in participants" :key="id">{{ id }}</option></select></label>
      <label>{{ t('实验条件', 'Condition') }}<select v-model="condition"><option value="all">{{ t('全部', 'All') }}</option><option v-for="(name, key) in conditions" :key="key" :value="key">{{ name }}</option></select></label>
      <label><input v-model="includeDemo" type="checkbox" /> {{ t('包含演示／非设备记录', 'Include demo / non-device records') }}</label>
      <strong>{{ filtered.length }} {{ t('已结束会话', 'completed sessions') }}</strong>
    </div>
    <div class="table-wrap"><table><thead><tr><th>{{ t('会话', 'Session') }}</th><th>{{ t('参与者', 'Participant') }}</th><th>{{ t('条件', 'Condition') }}</th><th>{{ t('时长 s', 'Duration s') }}</th><th>{{ t('合格比例', 'Qualified ratio') }}</th><th>{{ t('录音', 'Recording') }}</th><th></th></tr></thead><tbody>
      <tr v-for="row in filtered" :key="row.id"><td>{{ new Date(row.started_at_s * 1000).toLocaleString(language === 'en' ? 'en-US' : 'zh-CN') }}<small>{{ row.mode }} · {{ row.id.slice(0, 8) }}</small></td><td>{{ row.participant || '—' }}</td><td>{{ conditions[row.condition] }}</td><td>{{ value(row.duration_s) }}</td><td>{{ value(row.qualified_window_ratio) }}</td><td>{{ row.recording_status || t('无录音', 'No recording') }}</td><td><button @click="select(row)">{{ t('标注', 'Label') }}</button></td></tr>
    </tbody></table></div>
    <p v-if="!filtered.length">{{ t('当前筛选下暂无已结束会话', 'No completed sessions match these filters') }}</p>
    <form v-if="selected" class="label-form" @submit.prevent="save">
      <h3>{{ t('会话实验标注', 'Session Labels') }} · {{ selected.id.slice(0, 8) }}</h3>
      <label>{{ t('匿名编号（非姓名）', 'Anonymous ID (not a name)') }}<input v-model="form.participant" maxlength="64" pattern="[A-Za-z0-9_-]*" placeholder="P001" /></label>
      <label>{{ t('实际执行的条件', 'Condition actually performed') }}<select v-model="form.condition"><option v-for="(name,key) in conditions" :key="key" :value="key">{{ name }}</option></select></label>
      <label>{{ t('重复序号', 'Trial number') }}<input v-model.number="form.trial" type="number" min="1" max="10000" required /></label>
      <label>{{ t('盲听舒适度 1–7（可留空）', 'Blinded comfort 1–7 (optional)') }}<input v-model.number="form.comfort" type="number" min="1" max="7" step="1" /></label>
      <label>{{ t('盲听音乐性 1–7（可留空）', 'Blinded musicality 1–7 (optional)') }}<input v-model.number="form.musicality" type="number" min="1" max="7" step="1" /></label>
      <label>{{ t('协议／异常备注（不填写个人信息）', 'Protocol / deviations (no personal information)') }}<textarea v-model="form.notes" maxlength="2000" /></label>
      <div><button :disabled="busy" type="submit">{{ t('保存标注', 'Save Labels') }}</button> <button type="button" @click="selected=null">{{ t('取消', 'Cancel') }}</button></div>
    </form>
    <h3>{{ t('分组描述统计 · 均值 ± 样本标准差', 'Group Descriptive Statistics · Mean ± Sample SD') }}</h3>
    <div class="table-wrap"><table><thead><tr><th>{{ t('指标', 'Metric') }}</th><th v-for="group in groups" :key="group.key">{{ conditions[group.key] }} ({{ group.rows.length }})</th></tr></thead><tbody><tr v-for="[key, name] in metrics" :key="key"><th>{{ name }}</th><td v-for="group in groups" :key="group.key">{{ stats(group.rows, key) }}</td></tr></tbody></table></div>
    <h3>{{ t('参与者内配对差值', 'Within-Participant Paired Differences') }}</h3>
    <p>{{ t('每位参与者每种条件先取重复试验均值，n 为同时具有两种条件有效数据的参与者数。正值仅代表数值增加，不一定代表更好。', 'Repeated trials are averaged per participant and condition. n counts participants with valid data in both conditions. Positive differences indicate an increase, not necessarily improvement.') }}</p>
    <div class="table-wrap"><table><thead><tr><th>{{ t('指标', 'Metric') }}</th><th>{{ t('真闭环 − 固定', 'Closed Loop − Fixed') }}</th><th>{{ t('真闭环 − 伪闭环', 'Closed Loop − Sham') }}</th></tr></thead><tbody><tr v-for="[key,name] in metrics" :key="key"><th>{{ name }}</th><td>{{ paired(key, 'fixed') }}</td><td>{{ paired(key, 'sham') }}</td></tr></tbody></table></div>
    <p>{{ t('仅描述统计，不自动宣称显著性或助眠效果。按参与者筛选可检查同一参与者的重复试验；未经配对、随机化、盲听及条件核验，不能据此推断真闭环优于固定音乐。标注不会改变播放策略。', 'Descriptive statistics only: no significance or sleep-benefit claims. Filter by participant to inspect repeated trials. Paired design, randomization, blinded listening and verified conditions are required before claiming superiority. Labels do not change playback behavior.') }}</p>
    <p>{{ t('合格比例是重叠窗口比例；RMS 不是 LUFS，样本峰值不是真峰值。≥8kHz 比例受采样率影响，低于 16kHz 的录音不可比较。削波与跳变只是风险线索；BPM、和弦、调式、实际扬声器延迟与声压尚未测量。主观评分单独记录。', 'Qualification is an overlapping-window ratio. RMS is not LUFS; sample peak is not true peak. ≥8kHz energy depends on sample rate; recordings below 16kHz are not comparable. Overload and jumps are risk screens only. BPM, chords, mode, speaker latency and SPL remain unmeasured. Subjective scores are recorded separately.') }}</p>
  </section>
</template>
<style scoped>
.experiment-admin { padding: 20px 0; } header { display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; } h2 { font-size:20px; } h3 { font-size:16px; margin:24px 0 12px; } p { font-size:13px; line-height:1.7; } .storage { overflow-wrap:anywhere; } .filters { display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin:20px 0; } label { font-size:13px; } select,input,textarea { max-width:100%; } .filters select,.label-form input,.label-form select,.label-form textarea { display:block; margin-top:6px; } .table-wrap { overflow:auto; } table { border-collapse:collapse; width:100%; font-size:12px; } td,th { text-align:left; padding:10px; border-bottom:1px solid #d9e0df; white-space:nowrap; } th { background:#f0f4f3; } small { display:block; color:#65746e; margin-top:4px; } .label-form { border-top:1px solid #ccd7d0; border-bottom:1px solid #ccd7d0; padding:16px 0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .label-form h3,.label-form>div { grid-column:1/-1; } textarea { width:100%; min-height:72px; } button { border:1px solid #cbd7d2; padding:8px 12px; border-radius:6px; color:#264938; background:#f4f7f6; } @media(max-width:640px) { .label-form { grid-template-columns:1fr; } }
</style>
