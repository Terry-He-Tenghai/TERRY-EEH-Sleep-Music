import { text as t, labels } from '../i18n.js'
export const LIVE_MAX_AGE_MS = 15000
export const WAVEFORM_ORIGIN = 'trained_waveform_cnn_experimental'
const stages = ['W', 'N1', 'N2']

export function isFreshLiveEvent(event, now = Date.now()) {
  const age = now - event?.emitted_at_s * 1000
  return event?.source === 'LIVE' && Number.isFinite(event.emitted_at_s) && age >= 0 && age <= LIVE_MAX_AGE_MS
}

export function liveClassification(event, running, now = Date.now()) {
  if (!running || !isFreshLiveEvent(event, now) || event.inference_mode !== 'waveform_cnn' ||
      event.probability_origin !== WAVEFORM_ORIGIN || event.state?.status !== 'ok' ||
      !['ready', 'waiting'].includes(event.status)) return null
  const p = event.probabilities
  if (!p || !stages.every(key => Number.isFinite(p[key]) && p[key] >= 0 && p[key] <= 1) ||
      Math.abs(stages.reduce((sum, key) => sum + p[key], 0) - 1) > 0.001) return null
  return stages.map(key => [key, p[key]]).sort((a, b) => b[1] - a[1])[0]
}

export function canPlayAutomatic(event, now = Date.now()) {
  if (!event?.session_id || event.status !== 'ready') return false
  if (event.demo_scripted) return event.source === 'DEMO' && event.inference_mode === 'demo_scripted' &&
    event.probability_origin === 'scripted_not_model' && event.playback_mode === 'demo_scripted' &&
    event.state?.status === 'demo_scripted'
  if (event.source !== 'LIVE') return true // Preserve the existing DEMO model pathway.
  return !!liveClassification(event, true, now) && event.classification_confirmed === true &&
    event.playback_mode === 'adaptive'
}

// Permission to KEEP already-started music, never permission to start or switch.
export function canContinueAutomatic(event, playingSession, now = Date.now()) {
  if (event?.source !== 'LIVE' || playingSession == null ||
      String(event.session_id) !== String(playingSession) ||
      !['ready', 'waiting', 'frozen'].includes(event.status)) return false
  const age = now - event.emitted_at_s * 1000
  const stale = Number.isFinite(event.emitted_at_s) && age > LIVE_MAX_AGE_MS
  return stale || ['waiting', 'frozen'].includes(event.status)
}

export const musicStateLabels = labels({
  M1: 'M1 · 清醒安定音乐', M2: 'M2 · 入睡过渡音乐', M3: 'M3 · 浅睡维持音乐',
}, { M1: 'M1 · Awake relaxation', M2: 'M2 · Sleep-onset transition', M3: 'M3 · Light-sleep maintenance' })

export const waveformHoldReasons = labels({
  initializing_waveform_model: '正在加载本地波形模型',
  waveform_model_prediction_failed: '波形模型推理失败，已停止分类和音乐',
  recollecting_after_inference_backlog: '分类处理积压，已丢弃旧数据并重新收集窗口',
  inference_queue_overflow_restart_required: '旧版本分类队列溢出，请停止采集后重启更新的后端',
  collecting_model_window: '正在收集连续 40 秒模型窗口',
  confirming_state_classification: '已有模型分数，等待达到生成分数门槛',
  invalid_or_low_quality_eeg: '脑电质量未通过；已有音乐继续播放，等待有效分类',
  waiting_for_live_data: '等待设备恢复数据；已有音乐继续播放，分类驱动更新暂停',
  recollecting_after_packet_gap: '检测到丢包或重复包，正在重新收集连续 40 秒窗口',
  waveform_model_missing: '缺少所选 cap2 / cap4 / cap6 / cap8 / cap16 波形模型',
  waveform_model_contract_mismatch: '波形模型输入约定与当前设备配置不匹配',
  waveform_model_load_failed: '波形模型加载失败',
  waveform_requires_full_cap_capture: '波形模型需要完整采集全部 16 路电极',
  waveform_model_configuration_error: '波形模型配置错误',
  waveform_cnn_research_only: '波形 CNN 仅供研究，未经本设备验证',
}, {
  initializing_waveform_model: 'Loading local waveform model',
  waveform_model_prediction_failed: 'Waveform inference failed; classification and music stopped',
  recollecting_after_inference_backlog: 'Inference backlog; collecting a new window',
  inference_queue_overflow_restart_required: 'Inference queue overflow; restart the updated backend',
  collecting_model_window: 'Collecting a continuous 40-second model window',
  confirming_state_classification: 'Model scores available; waiting for the generation threshold',
  invalid_or_low_quality_eeg: 'EEG quality rejected; existing music continues pending valid classification',
  waiting_for_live_data: 'Waiting for device data; existing music continues without updates',
  recollecting_after_packet_gap: 'Missing or duplicate packets; recollecting a continuous 40-second window',
  waveform_model_missing: 'Selected cap2 / cap4 / cap6 / cap8 / cap16 model is missing',
  waveform_model_contract_mismatch: 'Waveform model input contract does not match device configuration',
  waveform_model_load_failed: 'Waveform model failed to load',
  waveform_requires_full_cap_capture: 'Waveform model requires all 16 acquisition channels',
  waveform_model_configuration_error: 'Waveform model configuration error',
  waveform_cnn_research_only: 'Research-only waveform CNN; not validated on this device',
})

export function waveformStatus(event, now = Date.now()) {
  if (!isFreshLiveEvent(event, now)) return t('等待新的实时脑电事件；已有音乐继续播放，暂停分类驱动更新', 'Waiting for fresh EEG; existing music continues without classification-driven updates')
  const reason = event.inference_hold_reason || event.reason
  return waveformHoldReasons[reason] || (event.classification_confirmed ? t('分类已确认（研究用途）', 'Classification confirmed (research only)') : t('等待有效稳定分类', 'Waiting for stable valid classification'))
}

export function waveformCollection(event) {
  const seconds = event?.waveform_model?.collected_seconds
  return `${Number.isFinite(seconds) ? Math.min(40, Math.max(0, seconds)).toFixed(1) : '0.0'} / 40 ${t('秒', 's')}`
}
