<script setup>
import { computed } from 'vue'
import { text as t } from '../i18n.js'

defineProps({ rows: { type: Array, default: () => [] }, conditions: { type: Object, required: true }, busy: Boolean })
defineEmits(['label'])

const measures = computed(() => [
  { key: 'alpha_8_12', name: 'Alpha · 8–12 Hz', kind: t('绝对功率', 'Absolute power'), unit: 'μV²', baseline: 'alpha_8_12_baseline_uv2', intervention: 'alpha_8_12_intervention_uv2', change: 'alpha_8_12_change_uv2' },
  { key: 'theta', name: 'Theta · 4–8 Hz', kind: t('绝对功率', 'Absolute power'), unit: 'μV²', baseline: 'theta_baseline_uv2', intervention: 'theta_intervention_uv2', change: 'theta_change_uv2' },
  { key: 'alpha_relative', name: 'Alpha · 8–12 Hz', kind: t('相对功率 / 1–30 Hz', 'Relative power / 1–30 Hz'), unit: '%', baseline: 'alpha_baseline_relative', intervention: 'alpha_intervention_relative', change: 'alpha_relative_change', relative: true },
  { key: 'theta_relative', name: 'Theta · 4–8 Hz', kind: t('相对功率 / 1–30 Hz', 'Relative power / 1–30 Hz'), unit: '%', baseline: 'theta_baseline_relative', intervention: 'theta_intervention_relative', change: 'theta_relative_change', relative: true },
])
const finite = n => typeof n === 'number' && Number.isFinite(n)
function format(n, relative = false, signed = false) {
  if (!finite(n)) return t('未测量', 'Not measured')
  const rounded = Number((n * (relative ? 100 : 1)).toFixed(2))
  return `${signed && rounded > 0 ? '+' : ''}${rounded.toFixed(2)}`
}
function hasPhase(row, phase) {
  const start = row[`${phase}_start_s`], end = row[`${phase}_end_s`]
  return finite(start) && finite(end) && start >= 0 && end > start
}
function phaseRange(row, phase) {
  return hasPhase(row, phase) ? `${format(row[`${phase}_start_s`])}–${format(row[`${phase}_end_s`])} s` : t('未标注', 'Not labeled')
}
function status(row) {
  const messages = []
  if (row.mode !== 'brainflow') messages.push(t('演示／非设备数据', 'Demo / non-device data'))
  if (!hasPhase(row, 'baseline')) messages.push(t('缺基线时段', 'Baseline interval missing'))
  if (!hasPhase(row, 'intervention')) messages.push(t('缺干预时段', 'Intervention interval missing'))
  const hasPower = ['alpha_8_12_power_uv2', 'theta_power_uv2', ...measures.value.flatMap(m => [m.baseline, m.intervention])].some(key => finite(row[key]))
  if (!hasPower) messages.push(t('无已记录的合格频段功率', 'No recorded qualified band power'))
  else if (hasPhase(row, 'baseline') && hasPhase(row, 'intervention') && measures.value.some(m => !finite(row[m.change]))) {
    messages.push(t('阶段功率不完整', 'Incomplete phase power'))
  }
  return messages.length ? messages.join(' · ') : t('阶段功率齐全', 'Phase power complete')
}
</script>

<template>
  <section class="eeg-power-shifts" aria-labelledby="eeg-power-title">
    <header class="section-heading">
      <h3 id="eeg-power-title">{{ t('脑电频段功率偏移', 'EEG Band Power Shifts') }}</h3>
      <span>{{ rows.length }} {{ t('条记录', 'records') }}</span>
    </header>
    <p class="scope">{{ t('质量合格的 40 秒窗口 · 基线 / 干预均值 · Δ = 干预 − 基线', 'Quality-qualified 40 s windows · baseline / intervention means · Δ = intervention − baseline') }}</p>
    <p v-if="!rows.length" class="empty">{{ t('当前筛选下暂无 EEG 实验记录', 'No EEG experiment records match these filters') }}</p>
    <div v-else class="power-records">
      <article v-for="row in rows" :key="row.id" class="power-record" :data-record-id="row.id">
        <header class="record-heading">
          <div>
            <h4>{{ row.participant || t('未命名受试者', 'Unnamed participant') }} · {{ conditions[row.condition] }} #{{ row.trial || 1 }}</h4>
            <small>{{ row.id.slice(0, 8) }}</small>
          </div>
          <button type="button" :disabled="busy" @click="$emit('label', row)">{{ t('阶段标注', 'Label phases') }}</button>
        </header>
        <p class="data-status">{{ status(row) }}</p>
        <dl class="record-context">
          <div><dt>{{ t('基线时段', 'Baseline interval') }}</dt><dd>{{ phaseRange(row, 'baseline') }}</dd></div>
          <div><dt>{{ t('干预时段', 'Intervention interval') }}</dt><dd>{{ phaseRange(row, 'intervention') }}</dd></div>
          <div><dt>{{ t('整段 Alpha 8–12 Hz 均值', 'Session Alpha 8–12 Hz mean') }}</dt><dd>{{ format(row.alpha_8_12_power_uv2) }}<span v-if="finite(row.alpha_8_12_power_uv2)"> μV²</span></dd></div>
          <div><dt>{{ t('整段 Theta 4–8 Hz 均值', 'Session Theta 4–8 Hz mean') }}</dt><dd>{{ format(row.theta_power_uv2) }}<span v-if="finite(row.theta_power_uv2)"> μV²</span></dd></div>
        </dl>
        <table :aria-label="`${t('频段功率', 'Band power')} ${row.id.slice(0, 8)}`">
          <thead><tr><th scope="col">{{ t('频段 / 指标', 'Band / measure') }}</th><th scope="col">{{ t('基线', 'Baseline') }}</th><th scope="col">{{ t('干预', 'Intervention') }}</th><th scope="col">{{ t('变化 Δ', 'Change Δ') }}</th></tr></thead>
          <tbody>
            <tr v-for="measure in measures" :key="measure.key" :data-measure="measure.key">
              <th scope="row">{{ measure.name }}<small>{{ measure.kind }} ({{ measure.unit }})</small></th>
              <td>{{ format(row[measure.baseline], measure.relative) }}</td>
              <td>{{ format(row[measure.intervention], measure.relative) }}</td>
              <td class="change">{{ format(row[measure.change], measure.relative, true) }}<small v-if="finite(row[measure.change])">{{ measure.relative ? t('百分点', 'percentage points') : 'μV²' }}</small></td>
            </tr>
          </tbody>
        </table>
      </article>
    </div>
  </section>
</template>

<style scoped>
.eeg-power-shifts { margin: 24px 0; padding: 20px 0 0; border-top: 1px solid #d5dfda; min-width: 0; }
.section-heading, .record-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
h3 { font-size: 18px; margin: 0; }
h4 { font-size: 14px; margin: 0; overflow-wrap: anywhere; }
.section-heading span, .scope, .data-status, .empty { font-size: 13px; color: #596763; }
.scope { margin: 10px 0 16px; line-height: 1.6; }
.power-records { max-height: 640px; overflow: auto; }
.power-record { padding: 16px 0 20px; border-top: 1px solid #d9e0df; }
.record-heading > div { flex: 1; min-width: 0; }
.record-heading button { flex: none; border: 1px solid #cbd7d2; padding: 8px 12px; border-radius: 6px; color: #264938; background: #f4f7f6; }
.data-status { margin: 10px 0; line-height: 1.6; }
.record-context { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; font-size: 12px; margin: 12px 0 16px; }
.record-context div { min-width: 0; }
dt { color: #596763; }
dd { margin: 5px 0 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px; }
th, td { padding: 10px 8px; border-bottom: 1px solid #d9e0df; text-align: right; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
thead th { background: #f0f4f3; }
th:first-child { text-align: left; width: 38%; }
tbody th { font-weight: 500; }
.change { background: #f2f5f7; font-weight: 600; }
small { display: block; margin-top: 4px; font-size: 11px; font-weight: 400; line-height: 1.5; color: #65746e; }
@media (max-width: 640px) {
  .record-context { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  th, td { padding: 9px 4px; }
  th:first-child { width: 34%; }
}
</style>
