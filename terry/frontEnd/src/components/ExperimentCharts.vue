<script setup>
import { computed, ref, watch } from 'vue'
import { text as t } from '../i18n.js'
const props = defineProps({ recordIds: { type: Array, default: () => [] }, filterActive: Boolean })
const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const data = ref(null), error = ref(''), busy = ref(false), participant = ref(''), metric = ref('relaxation_vas')
const conditions = ['fixed', 'sham', 'closed_loop']
const names = computed(() => [t('A 固定音乐', 'A Fixed'), t('B 伪闭环', 'B Sham'), t('C 真闭环', 'C Closed loop')])
const colors = ['#527f9b', '#b97835', '#27836d']
const metricNames = {
  lseq_gts: 'LSEQ GTS', relaxation_vas: 'Relaxation VAS', sleep_difficulty_vas: 'Sleep-onset difficulty VAS (supplementary)',
  kss_change: 'KSS post minus pre', sus_score: 'SUS usability', transition_naturalness_vas: 'Transition naturalness VAS (not SUS)',
  minimal_motion_latency_s: 'Latency to 5 minutes of minimal motion', alpha_change_uv2: 'Alpha power: intervention minus baseline',
  theta_change_uv2: 'Theta power: intervention minus baseline', alpha_8_12_change_uv2: 'Alpha 8–12 Hz power: intervention minus baseline',
  alpha_relative_change: 'Alpha 8–12 Hz relative power change', theta_relative_change: 'Theta 4–8 Hz relative power change',
  rms_change_db: 'Mean absolute RMS change', fallback_proportion: 'Observed control fallback proportion',
  classification_ms: 'Classification duration (not end-to-end latency)', qualified_window_ratio: 'Qualified overlapping-window ratio',
  backend_cpu_mean_percent: 'Mean backend CPU (one core = 100%)', backend_process_peak_rss_mb: 'Backend lifetime peak memory',
  musicality: 'Blinded musicality rating', songeval_musicality: 'SongEval musicality (exploratory)',
}
const metricLabel = key => t(data.value?.metrics?.[key]?.label, metricNames[key] || key)
const metricUnit = unit => t(unit, ({ '分': 'points', '比例': 'ratio' })[unit] || unit)
const selectedMetric = computed(() => data.value?.metrics?.[metric.value])
const people = computed(() => (data.value?.participants || []).filter(p => !participant.value || p.participant === participant.value))
const values = computed(() => people.value.flatMap(p => conditions.map(c => p.conditions[c].metrics[metric.value])).filter(Number.isFinite))
const range = computed(() => {
  if (!values.value.length) return [0, 1]
  const low = Math.min(...values.value), high = Math.max(...values.value), padding = Math.max((high-low)*.15, Math.abs(high)*.05, .5)
  return [low-padding, high+padding]
})
const x = i => 95 + i*210
const y = v => 225 - (v-range.value[0])/(range.value[1]-range.value[0])*190
const ticks = computed(() => Array.from({length:5}, (_,i) => range.value[0]+(range.value[1]-range.value[0])*i/4))
const format = n => Number.isFinite(n) ? n.toFixed(2) : '—'
const pValue = n => Number.isFinite(n) ? (n < .001 ? '<0.001' : n.toFixed(3)) : '—'
let requestVersion = 0
async function refresh() {
  const version = ++requestVersion
  busy.value = true; error.value = ''
  try {
    const query = new URLSearchParams()
    if (props.filterActive) (props.recordIds.length ? props.recordIds : ['']).forEach(id => query.append('ids', id))
    const response = await fetch(`${api}/api/session-reports/experiments/analysis?${query}`, {cache:'no-store'})
    if (!response.ok) throw new Error(t('分析接口不可用，请重启后端', 'Analysis unavailable; restart backend'))
    const result = await response.json()
    if (version !== requestVersion) return
    data.value = result
    if (!result.participants.some(p => p.participant === participant.value)) participant.value = ''
  } catch(e) { if (version === requestVersion) error.value = e.message } finally { if (version === requestVersion) busy.value = false }
}
watch(() => `${props.filterActive}:${props.recordIds.join(',')}`, refresh, { immediate: true })
</script>
<template>
  <section class="protocol-analysis">
    <header><h3>{{ t('三条件对比', 'Three-Condition Comparison') }}</h3><button :disabled="busy" @click="refresh">{{ t('更新分析', 'Update analysis') }}</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="data">
      <div class="counts"><span>{{ t('参与者', 'Participants') }} <b>{{ data.counts.participants }}</b></span><span>{{ t('三条件完成', 'Complete crossover') }} <b>{{ data.counts.complete_participants }}</b></span><span>{{ t('会话', 'Sessions') }} <b>{{ data.counts.sessions }}</b></span><span>{{ t('纳入分析', 'Eligible sessions') }} <b>{{ data.counts.eligible_sessions }}</b></span><span>{{ t('失败／中断', 'Failed / interrupted') }} <b>{{ data.counts.failed_sessions }}</b></span></div>
      <div class="controls"><label>{{ t('对比对象', 'Comparison') }}<select v-model="participant" :aria-label="t('对比对象', 'Comparison')"><option value="">{{ t('整体 · 每位用户配对', 'Cohort · participant pairs') }}</option><option v-for="p in data.participants" :key="p.participant">{{ p.participant }}</option></select></label><label>{{ t('分析指标', 'Outcome') }}<select v-model="metric" :aria-label="t('分析指标', 'Outcome')"><option v-for="(m,key) in data.metrics" :key="key" :value="key">{{ metricLabel(key) }} ({{ metricUnit(m.unit) }})</option></select></label></div>
      <figure v-if="values.length" class="comparison-chart">
        <figcaption>{{ participant || t('整体参与者内对比', 'Cohort paired comparison') }} · {{ metricLabel(metric) }} ({{ metricUnit(selectedMetric.unit) }})</figcaption>
        <svg viewBox="0 0 610 275" role="img" :aria-label="`${metricLabel(metric)} ${t('三条件配对图', 'three-condition paired chart')}`">
          <g v-for="tick in ticks" :key="tick"><line x1="65" x2="575" :y1="y(tick)" :y2="y(tick)" stroke="#e0e6e5"/><text x="57" :y="y(tick)+4" text-anchor="end" font-size="11" fill="#596763">{{ format(tick) }}</text></g>
          <g v-for="p in people" :key="p.participant">
            <template v-for="(c,i) in conditions" :key="c">
              <line v-if="i>0 && Number.isFinite(p.conditions[c].metrics[metric]) && Number.isFinite(p.conditions[conditions[i-1]].metrics[metric])" :x1="x(i-1)" :x2="x(i)" :y1="y(p.conditions[conditions[i-1]].metrics[metric])" :y2="y(p.conditions[c].metrics[metric])" stroke="#879591" :opacity="participant ? 1 : .4" stroke-width="1.5"/>
              <circle v-if="Number.isFinite(p.conditions[c].metrics[metric])" :cx="x(i)" :cy="y(p.conditions[c].metrics[metric])" r="5" :fill="colors[i]"><title>{{ p.participant }} · {{ names[i] }}: {{ format(p.conditions[c].metrics[metric]) }}</title></circle>
            </template>
          </g>
          <text v-for="(name,i) in names" :key="name" :x="x(i)" y="255" text-anchor="middle" font-size="13" :fill="colors[i]">{{ name }}</text>
        </svg>
      </figure>
      <p v-else class="empty">{{ t('该指标暂无已核验、已完成的实验数据', 'No verified completed data for this outcome') }}</p>
      <div class="table-wrap"><table><thead><tr><th>{{ t('用户', 'Participant') }}</th><th v-for="name in names" :key="name">{{ name }}</th><th>{{ t('三条件完成', 'Complete crossover') }}</th></tr></thead><tbody><tr v-for="p in people" :key="p.participant"><th>{{ p.participant }}</th><td v-for="c in conditions" :key="c">{{ format(p.conditions[c].metrics[metric]) }} <small>{{ p.conditions[c].eligible_sessions }}/{{ p.conditions[c].sessions }} {{ t('纳入／会话', 'eligible / sessions') }}</small></td><td>{{ p.complete ? t('是', 'Yes') : t('未完成', 'Incomplete') }}</td></tr></tbody></table></div>
      <template v-if="!participant && selectedMetric">
        <h4>{{ t('整体统计 · 每位用户每条件一个均值', 'Cohort Statistics · One Mean per Participant per Condition') }}</h4>
        <div class="table-wrap"><table><thead><tr><th>{{ t('条件', 'Condition') }}</th><th>n</th><th>{{ t('均值', 'Mean') }}</th><th>SD</th><th>{{ t('中位数', 'Median') }}</th></tr></thead><tbody><tr v-for="(c,i) in conditions" :key="c"><th>{{ names[i] }}</th><td>{{ selectedMetric.groups[c].n }}</td><td>{{ format(selectedMetric.groups[c].mean) }}</td><td>{{ format(selectedMetric.groups[c].sd) }}</td><td>{{ format(selectedMetric.groups[c].median) }}</td></tr></tbody></table></div>
        <p>Friedman · {{ t('完整配对人数', 'Complete-case n') }} {{ selectedMetric.complete_n }} · {{ t('探索性未校正 p', 'Exploratory unadjusted p') }} {{ pValue(selectedMetric.friedman?.p) }}</p>
        <div class="table-wrap"><table><thead><tr><th>{{ t('配对差值', 'Paired difference') }}</th><th>n</th><th>{{ t('均值', 'Mean') }}</th><th>SD</th><th>Wilcoxon p</th><th>Holm p</th></tr></thead><tbody><tr v-for="c in ['fixed','sham']" :key="c"><th>C − {{ c==='fixed' ? 'A' : 'B' }}</th><td>{{ selectedMetric.paired[c].n }}</td><td>{{ format(selectedMetric.paired[c].mean) }}</td><td>{{ format(selectedMetric.paired[c].sd) }}</td><td>{{ pValue(selectedMetric.paired[c].p) }}</td><td>{{ pValue(selectedMetric.paired[c].p_holm) }}</td></tr></tbody></table></div>
      </template>
      <p class="scope">{{ t('仅纳入已结束、标为已完成且实际条件已核验的设备会话。缺失不补零；失败记录仍保留。统计单位是用户，重复会话先取均值。低活动潜伏期不是临床入睡时间；模型输出不是临床睡眠分期。', 'Only ended, completed, condition-verified hardware sessions are eligible. Missing stays missing; failed records remain. Participants are the statistical unit; repeated sessions are averaged. Low-motion latency and model outputs are not clinical sleep endpoints.') }}</p>
    </template>
  </section>
</template>
<style scoped>
.protocol-analysis{border-top:1px solid #d5dfda;padding:20px 0}header,.counts,.controls{display:flex;gap:20px;flex-wrap:wrap;align-items:center}header{justify-content:space-between}h3{font-size:18px;margin:0}h4{font-size:15px;margin:24px 0 10px}.counts{padding:18px 0;border-bottom:1px solid #d5dfda}.counts span{font-size:13px}.counts b{margin-left:8px;font-size:20px}.controls{margin:20px 0}label{font-size:13px}select{display:block;margin-top:6px;max-width:100%;padding:7px}figure{margin:20px 0;max-width:800px}figcaption{font-size:14px;font-weight:600;margin-bottom:12px}svg{display:block;width:100%;height:auto}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:10px;text-align:left;border-bottom:1px solid #d9e0df;white-space:nowrap}th{background:#f0f4f3}small{display:block;color:#65746e}p{font-size:13px;line-height:1.7}.scope{color:#596763}.empty{padding:28px 0;color:#596763}button{padding:8px 12px;border:1px solid #cbd7d2;border-radius:6px;background:#f4f7f6}@media(max-width:640px){.controls{display:grid;grid-template-columns:1fr}select{width:100%}}
</style>
