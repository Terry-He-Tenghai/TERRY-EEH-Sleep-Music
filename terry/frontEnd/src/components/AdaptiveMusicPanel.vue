<script setup>
import { computed, onBeforeUnmount, shallowRef, watch } from 'vue'
import { isScriptedDemo } from '../audio/demoOrigin.js'
import { AdaptiveEngine } from '../audio/adaptiveEngine.js'

const props = defineProps({ event: { type: Object, default: null }, disabled: { type: Boolean, default: false } })
const scripted = computed(() => props.event?.demo_scripted === true)
const playback = shallowRef({ armed: false, status: 'unarmed', reason: '启动 EEG 采集时授权声音；无需手动编辑 MIDI', activeNotes: [], beat: 0, phrase: 0, logCount: 0 })
const engine = new AdaptiveEngine({ onUpdate: update => { playback.value = update } })
const statusLabels = { holding: '短暂电极失效 · 背景保持', fading: '音频渐出中', unarmed: '未授权', waiting: '等待有效计划 / 静音', ready: '已缓冲 / 等待边界', buffering: '本地底轨缓冲中', playing: '浏览器正在播放', frozen: '信号冻结 / 静音', blocked: '播放阻止 / 静音', error: '错误 / 静音', stopped: '已停止' }
const statusLabel = computed(() => statusLabels[playback.value.status] || playback.value.status)
const plannedState = computed(() => props.event?.music_state || props.event?.current_music_state || '—')
const targetState = computed(() => props.event?.target_music_state || '—')
const plannedTrack = computed(() => props.event?.track || props.event?.selected_track)
const quality = computed(() => Number.isFinite(props.event?.signal_quality) ? `${(props.event.signal_quality * 100).toFixed(0)}%` : '不可用')
const classifierState = computed(() => props.event?.state || {})
const futureN2 = computed(() => Number.isFinite(classifierState.value.n2_within_5m_probability) ? classifierState.value.n2_within_5m_probability : null)
const baselineReady = computed(() => classifierState.value.baseline_ready === true)
const inferenceBlocked = computed(() => ['blocked', 'error', 'frozen'].includes(props.event?.status))
const baselineLabel = computed(() => scripted.value ? '动态演示不使用基线' : props.event?.inference_mode === 'spectral_heuristic' ? '频谱估计不使用基线' : inferenceBlocked.value ? '已阻塞' : props.event?.status === 'stopped' ? '已停止' : !props.event?.state ? '尚未开始' : baselineReady.value ? '已就绪' : '采集中')
const inferenceStatus = computed(() => scripted.value ? '预设演示，未运行分类器' : inferenceBlocked.value ? '推理已阻塞' : ({ ok: '分类结果已返回', warming_up: '特征预热中', signal_invalid: '信号无效' }[classifierState.value.status] || backendReason.value))
const featureDefinitions = [
  ['frontal_beta_z', '额区 β 基线偏差'], ['posterior_alpha_z', '后部 α 基线偏差'],
  ['central_theta_z', '中央 θ 基线偏差'], ['central_sigma_z', '中央 σ 基线偏差'],
  ['frontocentral_delta_z', '额中央 δ 基线偏差'], ['alpha_theta_slope_1m', 'α/θ 1 分钟斜率'],
]
const spectralFeatures = [['delta_ratio', 'δ 相对功率'], ['theta_ratio', 'θ 相对功率'], ['alpha_ratio', 'α 相对功率'], ['sigma_ratio', 'σ 相对功率'], ['beta_ratio', 'β 相对功率']]
const interpretableFeatures = computed(() => {
  const values = props.event?.interpretable_features || {}
  return (props.event?.inference_mode === 'spectral_heuristic' ? spectralFeatures : featureDefinitions).map(([key, label]) => ({ key, label, value: Number.isFinite(values[key]) ? values[key] : null }))
})
const featureWidth = value => `${Math.min(100, Math.abs(value || 0) / 3 * 100)}%`
const probabilities = computed(() => {
  const values = props.event?.probabilities || props.event?.state_probabilities || {}
  return ['W', 'N1', 'N2'].map(key => ({ key, value: Number.isFinite(values[key]) && values[key] >= 0 && values[key] <= 1 ? values[key] : null }))
})
const now = shallowRef(Date.now())
const freshnessTimer = setInterval(() => { now.value = Date.now() }, 1000)
const resultStale = computed(() => !!props.event?.state && (!Number.isFinite(props.event.timestamp_s) || now.value - props.event.timestamp_s * 1000 > 15000))
const classifierReady = computed(() => props.event?.playback_mode !== 'conservative' && !resultStale.value && classifierState.value.status === 'ok' && probabilities.value.every(p => p.value !== null))
const classification = computed(() => {
  if (scripted.value) return props.event?.status === 'ready' && !resultStale.value ? `预设 ${props.event.demo_stage || '—'}（非模型分类）` : '演示已暂停 / 过期'
  if (inferenceBlocked.value) return '推理已阻塞'
  if (props.event?.status === 'stopped') return '采集已停止'
  if (!classifierReady.value) return '等待有效分类'
  const best = [...probabilities.value].sort((a, b) => b.value - a.value)[0]
  return `${{ W: '清醒', N1: '睡眠阶段1', N2: '睡眠阶段2' }[best.key]}（${best.key}）`
})
const confidence = computed(() => classifierReady.value ? `${(Math.max(...probabilities.value.map(p => p.value)) * 100).toFixed(1)}%` : '不可用')
const history = shallowRef([])
watch(() => props.event, (event, previous) => {
  if (!event) { history.value = []; return }
  if (event.session_id !== previous?.session_id) history.value = []
  const time = event.eeg_timestamp_s
  if (!Number.isFinite(time) || history.value.at(-1)?.time === time) return
  const p = event.probabilities || {}
  history.value = [...history.value, { time, values: event.state?.status === 'ok' && probabilities.value.every(item => item.value !== null) ? p : {} }].slice(-100)
})
function probabilityPoints(key) {
  const rows = history.value, first = rows[0]?.time || 0, span = Math.max(3, (rows.at(-1)?.time || 0) - first)
  const segments = []; let segment = []
  for (const row of rows) {
    const value = row.values[key]
    if (!Number.isFinite(value)) { if (segment.length) segments.push(segment.join(' ')); segment = []; continue }
    segment.push(`${40 + (row.time - first) / span * 720},${130 - value * 110}`)
  }
  if (segment.length) segments.push(segment.join(' '))
  return segments
}
const reasonLabels = {
  collecting_eeg_window: '正在收集 6 秒脑电窗口', eeg_spectral_heuristic_unvalidated: '频谱分类估计已返回，未经验证',
  live_inference_requires_8_or_16_channels: '实时分类需要 8 或 16 路脑电信号',
  initializing_inference: '正在加载模型', collecting_baseline_and_state_windows: '等待基线与状态窗口',
  collecting_clean_baseline: '正在收集清洁基线，当前配置300秒；信号质量会影响准备时间',
  warming_up_inference_features: '推理特征预热中', collecting_state_probability_windows: '正在累计分类窗口',
  invalid_or_low_quality_eeg: '信号质量不足，音乐已冻结', invalid_state_probabilities: '状态概率无效，音乐已冻结',
  inference_requires_250_hz_no_resampling: '模型要求250Hz，请停止后选择250Hz重新开始',
  configured_realtime_models_missing: '缺少配置对应的模型文件，无法分类',
  reduced_montage_requires_retrained_model: '当前 8 电极布局尚无经过训练验证的匹配模型；分类及自动音乐已停用。',
  physical_channel_map_unconfirmed_set_TERRY_EEG_CHANNEL_MAP_CONFIRMED_after_verification: '尚未确认物理帽位映射。确认设备通道与config.hardware.yaml一致后，由操作者设置TERRY_EEG_CHANNEL_MAP_CONFIRMED=1并重启后端。',
  conservative_audio_without_classification: '保守音乐计划：低增益背景与稀疏MIDI，非睡眠分类驱动',
  conservative_track_missing: '保守播放缺少可用本地背景音乐',
  no_valid_electrodes: '全部电极未通过检查，暂停声音并持续重新检查',
  insufficient_valid_channels_rechecking: '本窗口有效电极少于8个，正在持续重新检查；恢复后自动重建基线，无需反复重启采集',
  insufficient_valid_channels_restart_required: '有效电极少于8个，均值补全已停止。检查接触后重新开始采集',
  hardware_timestamp_discontinuity_restart_required: '设备接收时间出现倒退或超过2秒间隔，请检查连接后重新采集',
  hardware_package_discontinuity_restart_required: '设备样本计数不连续，可能丢包、重复或乱序；请检查Wi-Fi连接后重新采集',
  invalid_hardware_package_counters_restart_required: '设备样本计数缺失或格式无效，无法确认数据连续性',
  acquisition_stopped: '采集已停止', acquisition_stale_restart_required: '脑电断流，需重新开始采集',
}
const qcReasonLabels = { valid: '通过', nonfinite: '缺失或非有限值', flatline: '平直或长时间不变', excessive_amplitude: '去趋势后幅度仍过大', repeated_artifacts: '多次大幅异常' }
const qcNumber = value => Number.isFinite(value) ? value.toFixed(1) : '—'
const backendReason = computed(() => reasonLabels[props.event?.reason] || props.event?.reason || '尚未收到后端事件')
const notes = computed(() => (Array.isArray(props.event?.notes) ? props.event.notes : []).slice(0, 512).filter(note => Number.isFinite(note.start_beat) && note.start_beat >= 0 && note.start_beat < 16 && Number.isFinite(note.duration_beats) && note.duration_beats > 0 && Number.isInteger(note.midi_note) && note.midi_note >= 0 && note.midi_note <= 127))
const pitchRange = computed(() => {
  const pitches = notes.value.map(note => note.midi_note)
  return { low: Math.max(0, Math.min(48, ...pitches) - 2), high: Math.min(127, Math.max(84, ...pitches) + 2) }
})
const y = note => 20 + (pitchRange.value.high - note.midi_note) / (pitchRange.value.high - pitchRange.value.low + 1) * 190
const height = computed(() => Math.max(2, 190 / (pitchRange.value.high - pitchRange.value.low + 1)))
const samePlan = computed(() => playback.value.activeSequence === props.event?.sequence)
const source = computed(() => props.event?.source === 'LIVE' ? 'LIVE · 实时设备' : props.event?.source === 'DEMO' ? 'DEMO · 演示数据' : '未收到来源')
let downloadUrl = null, downloadTimer = null
function arm() {
  if (props.disabled) { engine.stop('采集功能已禁用', 'blocked'); return Promise.resolve(false) }
  return engine.arm()
}
function stop(reason = '用户停止自动声音') { engine.stop(reason) }
function downloadLog() {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl)
  clearTimeout(downloadTimer)
  downloadUrl = URL.createObjectURL(new Blob([JSON.stringify(engine.exportLog(), null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = downloadUrl; anchor.download = `terry-adaptive-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  document.body.appendChild(anchor); anchor.click(); anchor.remove()
  downloadTimer = setTimeout(() => { URL.revokeObjectURL(downloadUrl); downloadUrl = null }, 1000)
}
watch(() => props.event, event => { if (!props.disabled) engine.consume(event) }, { flush: 'sync' })
watch(() => props.disabled, disabled => { if (disabled) engine.stop('采集功能已禁用') }, { flush: 'sync' })
onBeforeUnmount(() => {
  engine.dispose(); clearTimeout(downloadTimer); clearInterval(freshnessTimer)
  if (downloadUrl) URL.revokeObjectURL(downloadUrl)
})
defineExpose({ arm, stop })
</script>

<template>
  <section class="adaptive-panel" aria-labelledby="adaptive-music-title">
    <header class="panel-header">
      <div><p class="eyebrow">EEG → 音乐</p><h2 id="adaptive-music-title">自动音乐</h2></div>
      <span class="source-tag" :class="{ demo: event?.source === 'DEMO' }">{{ source }}</span>
    </header>
    <aside v-if="scripted" class="notice compact-notice" role="status"><strong>预设演示 · 非模型预测</strong><span> · {{ event.demo_stage }} · {{ Number(event.demo_elapsed_s || 0).toFixed(0) }} 秒</span><details><summary>演示说明</summary><p>清醒→N1→N2→清醒循环；概率是音乐控制权重，不是模型置信度。</p></details></aside>
    <div class="status-row"><span class="status-dot" :class="{ playing: playback.activeTrack }" /><strong>{{ statusLabel }}</strong><span v-if="!playback.armed">启动采集后播放</span></div>
    <p class="reason" role="status">{{ reasonLabels[playback.reason] || playback.reason }}<template v-if="event?.reason && event.reason !== playback.reason"> · {{ backendReason }}</template></p>
    <aside v-if="event?.playback_mode === 'conservative'" class="notice compact-notice" role="status"><strong>保守音乐 · 非睡眠分类驱动</strong><details><summary>为什么</summary><p>分类或基线未满足条件；使用固定稀疏 MIDI 与背景。{{ reasonLabels[event.inference_hold_reason] || event.inference_hold_reason }}</p></details></aside>
    <details v-if="(event?.playback_mode === 'adaptive' || isScriptedDemo(event)) && event?.modulation" class="notice modulation-details">
      <summary>{{ scripted ? '预设状态音乐控制' : '脑电连续音乐控制' }} · {{ event.modulation.control_level.toFixed(2) }} / 1</summary>
      <p>控制量平滑 {{ event.modulation.smoothing_seconds ?? 20 }} 秒 · 每16秒应用乐句。该控制量是音乐规则，不是临床指标。</p>
      <p>旋律 {{ event.modulation.melody_notes }} 音符 · 时长 {{ event.modulation.target_duration_beats.toFixed(2) }} 拍 · 亮度 {{ event.modulation.brightness.toFixed(2) }} · 旋律 ×{{ event.modulation.melody_gain.toFixed(2) }} · 背景 ×{{ event.modulation.pad_gain.toFixed(2) }}。</p>
      <details><summary>映射说明</summary>
        <p v-if="event.modulation.mapping === 'continuous_arrangement_v4'">持续编排 v4：每16秒应用乐句，动机与和弦按作曲周期发展，不代表脑电变化。</p>
        <p v-if="event.modulation.mapping === 'continuous_harmony_v3'">持续和声 v3：每16秒循环调度和声音符，低增益长音保留。</p>
        <p v-if="event.modulation.mapping === 'probabilities_80_features_20_contrast_v2'">增强编排：三角波旋律与音区偏移；稳定脑电不会人为制造随机波动。</p>
        <p v-if="!scripted">输入为 W/N1 分类概率，条件允许时叠加基线特征。</p>
      </details>
    </details>
    <div class="state-grid">
      <article><h3>后端目标</h3><p class="state-value">{{ plannedState }} <span>→ {{ targetState }}</span></p><p>{{ plannedTrack?.title || plannedTrack?.id || '未选择背景' }}</p><small>计划 {{ event?.sequence ?? '—' }} · {{ event?.motif_variation || event?.variation || '—' }}</small></article>
      <article><h3>当前播放</h3><p class="state-value">{{ playback.activeState || '静音' }}</p><p>{{ playback.activeTrack?.title || '尚未播放' }}</p><small v-if="playback.activeTrack">已应用 {{ playback.activeSequence }}</small><small v-if="playback.fadingTrack">淡出：{{ playback.fadingTrack.title }}</small></article>
    </div>
    <section class="classifier-card" aria-labelledby="classifier-title">
      <div class="classifier-heading"><div><h3 id="classifier-title">{{ scripted ? '预设状态' : '分类状态' }}</h3></div><span class="classifier-status">{{ inferenceStatus }}</span></div>
      <div class="classification-summary"><div><span>当前状态</span><strong>{{ classification }}</strong></div><div><span>N2（5分钟）</span><strong>{{ futureN2 === null ? '不可用' : `${(futureN2 * 100).toFixed(1)}%` }}</strong></div><div><span>基线</span><strong>{{ baselineLabel }}</strong></div><div><span>窗口</span><strong>{{ Number.isFinite(event?.eeg_timestamp_s) ? `${event.eeg_timestamp_s.toFixed(1)} s` : '—' }}</strong></div></div>
      <aside v-if="event?.channel_repair" class="notice compact-notice" role="status"><strong>{{ event.channel_repair.imputed_channels?.length ? '均值补全' : '电极质量' }}</strong><span> · 有效 {{ event.channel_repair.valid_channels?.length ?? 0 }} / {{ event.channel_repair.channels?.length ?? 16 }}</span><details><summary>质量详情</summary><p v-if="event.channel_repair.imputed_channels?.length">补全：{{ event.channel_repair.imputed_channels.join('、') }}。补全不是实际测量，分类准确率尚未验证。</p><p>检查约每6秒更新；波形有线条不等于质量合格。时间 {{ qcNumber(event.channel_repair.window_end_s) }} 秒。</p><details v-if="event.channel_repair.channels?.length"><summary>逐通道诊断</summary><div style="overflow-x:auto"><table style="width:100%;text-align:left"><thead><tr><th>电极</th><th>判断</th><th>峰峰值</th><th>范围</th><th>平直</th></tr></thead><tbody><tr v-for="item in event.channel_repair.channels" :key="item.channel"><td>{{ item.channel }}</td><td>{{ qcReasonLabels[item.reason] || item.reason }}</td><td>{{ qcNumber(item.raw_peak_to_peak_uv) }}</td><td>{{ qcNumber(item.detrended_range_uv) }}</td><td>{{ item.flat_fraction == null ? '—' : `${(item.flat_fraction * 100).toFixed(1)}%` }}</td></tr></tbody></table></div></details></details></aside>
      <p v-if="inferenceBlocked" role="alert">{{ backendReason }}。波形采集成功不表示分类已开始。</p><p v-if="resultStale" role="status">分类数据超过15秒未更新，仅显示上次记录。</p>
      <details class="classifier-details"><summary>分类概率与特征</summary><div class="probabilities" aria-label="睡眠状态概率"><div v-for="item in probabilities" :key="item.key"><label :for="`adaptive-prob-${item.key}`">{{ item.key }} <span>{{ item.value === null ? '不可用' : `${(item.value * 100).toFixed(1)}%` }}</span></label><meter :id="`adaptive-prob-${item.key}`" min="0" max="1" :value="item.value ?? 0" :aria-label="`${item.key} 概率`" /></div><p>质量 <strong>{{ quality }}</strong> · 最高概率 {{ confidence }}</p></div><div class="feature-grid"><div v-for="item in interpretableFeatures" :key="item.key" class="feature-item"><label><span>{{ item.label }}</span><strong>{{ item.value === null ? '不可用' : item.value.toFixed(2) }}</strong></label><div class="feature-track"><i v-if="item.value !== null" :style="{ width: featureWidth(item.value), transform: item.value < 0 ? 'translateX(-100%)' : 'none' }" :class="{ negative: item.value < 0 }" /></div></div></div></details>
    </section>
    <div class="probabilities" aria-label="睡眠状态概率">
      <div v-for="item in probabilities" :key="item.key"><label :for="`adaptive-prob-${item.key}`">{{ item.key }} <span>{{ item.value === null ? '不可用' : `${(item.value * 100).toFixed(1)}%` }}</span></label><meter :id="`adaptive-prob-${item.key}`" min="0" max="1" :value="item.value ?? 0" :aria-label="`${item.key} 概率`" /></div>
      <p>信号质量 <strong>{{ quality }}</strong></p>
    </div>
    <p class="legend">W：清醒 · N1：浅睡眠阶段 1 · N2：浅睡眠阶段 2。概率{{ scripted ? '为预设演示权重，非模型预测' : '为后端估计，非临床诊断' }}。</p>
    <details v-if="history.length" class="classifier-details" aria-label="最近分类概率趋势">
      <summary>分类趋势 · {{ history.length }} 个窗口</summary>
      <svg viewBox="0 0 800 165" style="width:100%;max-height:210px" role="img" aria-label="W N1 N2 概率时间曲线">
        <text x="4" y="24">100%</text><text x="12" y="133">0%</text><line x1="40" x2="760" y1="130" y2="130" stroke="#c7d5c5" />
        <g v-for="(color, key) in {W:'#377aaf',N1:'#478c54',N2:'#8052a5'}" :key="key"><polyline v-for="(points,i) in probabilityPoints(key)" :key="i" :points="points" fill="none" :stroke="color" stroke-width="2" /></g>
        <text x="40" y="157">{{ history[0].time.toFixed(0) }} s</text><text x="760" y="157" text-anchor="end">{{ history.at(-1).time.toFixed(0) }} s</text>
      </svg>
    </details>
    <div class="roll-heading"><h3>MIDI 钢琴卷帘</h3><span>{{ notes.length }} 音符 · 16 拍</span></div>
    <div class="piano-roll">
      <svg viewBox="0 0 860 238" role="img" aria-label="最新后端计划的只读 MIDI 音符；灰色 pad 音符不合成">
        <rect x="44" y="16" width="800" height="200" class="roll-background" />
        <g v-for="beat in 17" :key="beat"><line :x1="44 + (beat - 1) * 50" :x2="44 + (beat - 1) * 50" y1="16" y2="216" class="grid-line" :class="{ bar: (beat - 1) % 4 === 0 }" /><text :x="44 + (beat - 1) * 50" y="232" text-anchor="middle">{{ beat - 1 }}</text></g>
        <text x="3" y="25">{{ pitchRange.high }}</text><text x="3" y="211">{{ pitchRange.low }}</text>
        <rect v-for="(note, index) in notes" :key="index" :x="44 + note.start_beat * 50" :y="y(note)" :width="Math.max(1, Math.min(note.duration_beats, 16 - note.start_beat) * 50 - 1)" :height="height" rx="1" class="midi-note" :class="note.voice"><title>{{ note.voice }} · MIDI {{ note.midi_note }} · 起始 {{ note.start_beat }} 拍 · 时长 {{ note.duration_beats }} 拍 · 力度 {{ note.velocity }}{{ note.voice === 'pad' ? '（不合成，由本地底轨代替）' : '' }}</title></rect>
        <line v-if="playback.activeTrack && samePlan" :x1="44 + playback.beat * 50" :x2="44 + playback.beat * 50" y1="16" y2="216" class="playhead" />
      </svg>
    </div>
    <p class="legend"><span class="melody-key">■ 旋律</span> · <span class="bass-key">■ 低音</span> · <span style="color:#8062a3">■ 持续和声 / 纹理</span> · 灰色 pad 仅展示、不合成。{{ samePlan && playback.activeTrack ? '播放线对应当前已应用计划。' : '最新计划与当前播放可能不同，播放线暂不显示。' }}</p>
    <section v-if="(playback.activeTrack?.id || plannedTrack?.id || '').startsWith('user_')" class="upload-volume" aria-labelledby="upload-volume-label">
      <details><summary>上传背景音量 ×{{ (playback.uploadLevel ?? 1).toFixed(1) }}</summary><label id="upload-volume-label" class="sr-only" for="upload-volume">上传背景音量补偿</label><input id="upload-volume" type="range" min="0" max="6" step="0.1" :value="playback.uploadLevel ?? 1" @input="engine.setUploadLevel(Number($event.target.value))" /><p>调整上传背景，不放大 MIDI；0 为静音。</p><p v-if="playback.loudness">RMS {{ playback.loudness.rms.toFixed(4) }} · 峰值 {{ playback.loudness.peak.toFixed(4) }} · 自动 ×{{ playback.loudness.gain.toFixed(2) }}。不是 LUFS 或声压测量。</p></details>
    </section>
    <section class="upload-volume"><details><summary>MIDI 音量 ×{{ (playback.midiLevel ?? 1).toFixed(1) }}</summary><label class="sr-only" for="midi-level">MIDI 音量</label><input id="midi-level" type="range" min="0" max="2" step="0.1" :value="playback.midiLevel ?? 1" @input="engine.setMidiLevel(Number($event.target.value))" /><p>0 为原曲对照，1 为默认，2 为增强试听；仅调整 MIDI 层。</p></details></section>
    <div class="playback-clock"><span>当前乐句 {{ playback.phrase || '—' }} · 拍位 {{ playback.activeTrack ? playback.beat.toFixed(1) : '—' }}</span><span>下一边界 {{ playback.nextBoundarySeconds == null ? '—' : `${playback.nextBoundarySeconds.toFixed(1)} 秒` }}</span></div>
    <details class="notice compact-notice"><summary>播放说明</summary><p>后端生成 MIDI 计划，浏览器合成并叠加本地背景。底轨切换在乐句边界淡化；兼容性与声压安全未验证。</p></details>
    <footer><button type="button" :disabled="!playback.armed" @click="stop()">停止声音</button><button type="button" class="secondary" @click="downloadLog">下载日志（{{ playback.logCount }}）</button><details><summary>安全与日志说明</summary><small>页面隐藏、手动停止或其他播放器接管时立即停止。短暂电极失效最多保持背景30秒；无新计划超过15秒后淡出。日志仅记录浏览器调度，不证明扬声器输出。</small></details></footer>
  </section>
</template>

<style scoped>
.upload-volume { margin:20px 0; padding:18px; border:1px solid #dce6db; border-radius:12px; background:white; }
.upload-volume label { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; font-size:14px; }
.upload-volume input { display:block; width:100%; margin:16px 0; accent-color:#376b4b; }
.upload-volume p { margin:0; font-size:12px; color:#546659; line-height:1.8; }
.adaptive-panel { color: #17362d; background: #f9fbf8; border: 1px solid #dce6db; border-radius: 20px; padding: clamp(18px, 3vw, 32px); margin: 24px 0; font-family: inherit; }
.panel-header, .status-row, .roll-heading, .playback-clock, footer { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.panel-header, .roll-heading, .playback-clock { justify-content: space-between; }
h2 { margin: 4px 0 16px; font-size: 25px; } h3 { font-size: 14px; margin: 0 0 12px; } p { line-height: 1.65; }
.eyebrow, small, .legend, .roll-heading > span, .playback-clock { font-size: 12px; color: #546659; }
.eyebrow { margin: 0; letter-spacing: .05em; }.source-tag { padding: 8px 12px; border-radius: 20px; background: #e1eddf; font-size: 12px; }.source-tag.demo { background: #fff0ca; color: #755315; }
.status-row { font-size: 13px; }.status-dot { width: 9px; height: 9px; border-radius: 50%; background: #9aa69b; }.status-dot.playing { background: #378259; }.reason { font-size: 13px; overflow-wrap: anywhere; min-height: 24px; }
.state-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 18px 0; }.state-grid article { background: white; border: 1px solid #e2e9df; border-radius: 12px; padding: 18px; min-width: 0; overflow-wrap: anywhere; }.state-grid p { margin: 6px 0; }.state-value { font-size: 26px; font-weight: 600; }.state-value span { font-size: 16px; color: #70816f; }.state-grid small { display: block; }
.classifier-card { background: white; border: 1px solid #e2e9df; border-radius: 12px; padding: 18px; margin: 18px 0; }.classifier-heading { display:flex; justify-content:space-between; align-items:start; gap:12px; }.classifier-heading h3 { margin-bottom:4px; }.classifier-heading p { margin:0; font-size:12px; color:#68776a; }.classifier-status { flex-shrink:0; padding:5px 9px; border-radius:999px; background:#edf3ea; color:#48694d; font-size:11px; }.classification-summary { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }.classification-summary div { background:#f8faf7; border-radius:8px; padding:10px; }.classification-summary span, .classification-summary strong { display:block; }.classification-summary span { font-size:11px; color:#718071; }.classification-summary strong { margin-top:4px; font-size:16px; }.feature-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px 18px; }.feature-item label { display:flex; justify-content:space-between; gap:8px; font-size:11px; color:#5c6d60; }.feature-item strong { color:#244b38; }.feature-track { height:5px; margin-top:6px; border-radius:5px; background:linear-gradient(90deg, transparent 49.5%, #9cac9b 49.5%, #9cac9b 50.5%, transparent 50.5%), #edf1eb; overflow:hidden; }.feature-track i { display:block; height:100%; margin-left:50%; border-radius:5px; background:#568666; transform-origin:left; }.feature-track i.negative { margin-left:50%; background:#b47962; transform-origin:right; }
.probabilities { display: grid; grid-template-columns: repeat(3, 1fr) auto; align-items: center; gap: 20px; }.probabilities label { display: flex; justify-content: space-between; font-size: 12px; gap: 8px; }.probabilities meter { width: 100%; height: 12px; accent-color: #4c7753; }.probabilities p { font-size: 12px; }.legend { margin: 8px 0 20px; }
.piano-roll { overflow-x: auto; border: 1px solid #dce4d8; border-radius: 10px; background: white; }.piano-roll svg { width: 100%; min-width: 560px; display: block; }.roll-background { fill: #f9fbf7; }.grid-line { stroke: #e8eee4; }.grid-line.bar { stroke: #c9d7c4; }svg text { fill: #64715d; font-size: 10px; }.midi-note { fill: #5b967b; }.midi-note.pad { fill: #c7cdc4; }.midi-note.bass { fill: #a07e4f; }.midi-note.texture { fill: #9181ae; }.playhead { stroke: #c94032; stroke-width: 2; }.melody-key { color: #3e795f; }.bass-key { color: #926d3e; }
.notice { background: #f1f1e6; padding: 15px 18px; border-radius: 10px; color: #5e614b; font-size: 12px; line-height: 1.8; margin: 20px 0; }button { border: 1px solid #214c3b; background: #214c3b; color: white; border-radius: 9px; padding: 10px 16px; font: inherit; font-size: 13px; cursor: pointer; }button.secondary { background: transparent; color: #214c3b; }button:disabled { opacity: .45; cursor: not-allowed; }button:focus-visible { outline: 3px solid #8bad66; outline-offset: 3px; }footer small { flex-basis: 100%; line-height: 1.6; }
@media (max-width: 640px) { .state-grid { grid-template-columns: 1fr; }.probabilities { grid-template-columns: 1fr 1fr 1fr; gap: 10px; }.probabilities p { grid-column: 1 / -1; margin: 0; }.roll-heading { align-items: start; } }
</style>
