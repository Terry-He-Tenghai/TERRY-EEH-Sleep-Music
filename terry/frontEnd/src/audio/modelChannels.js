// CAP16 acquisition order. Model selection never changes the acquisition buffer.
export const CAP_CHANNELS = Object.freeze(['Fp1', 'Fp2', 'C3', 'C4', 'P7', 'P8', 'O1', 'O2', 'F7', 'F8', 'F3', 'F4', 'T7', 'T8', 'P3', 'P4'])
export const MODEL_OPTIONS = Object.freeze([
  { count: 2, channels: ['Fp1', 'Fp2'] },
  { count: 4, channels: ['Fp1', 'Fp2', 'F3', 'F4'] },
  { count: 6, channels: ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8'] },
  { count: 8, channels: CAP_CHANNELS.slice(0, 8) },
  { count: 16, channels: [...CAP_CHANNELS] },
])
export function modelChannels(count) {
  return [...(MODEL_OPTIONS.find(option => option.count === Number(count))?.channels || CAP_CHANNELS)]
}
export function plotChannelIndices(acquisitionChannels, count, showAll = false, live = true) {
  const selected = live && !showAll ? modelChannels(count) : acquisitionChannels
  return selected.map(channel => acquisitionChannels.indexOf(channel)).filter(index => index >= 0)
}
export function qualityChannels(count) {
  return [2, 4, 6].includes(Number(count)) ? modelChannels(count) : [...CAP_CHANNELS]
}
export function modelChannelInfo(event, count = 16) {
  const model = event?.waveform_model
  const info = model?.info || model || {}
  const selectedCount = event?.classification_channels || count
  return {
    selected: Array.isArray(info.selected_channels) ? info.selected_channels : modelChannels(selectedCount),
    quality: Array.isArray(info.quality_channels) ? info.quality_channels : qualityChannels(selectedCount),
  }
}
const reasonLabels = {
  invalid_or_low_quality_eeg: '脑电质量检查未通过',
  non_finite: '包含非有限数值', non_finite_samples: '包含非有限采样值',
  flatline: '平直信号', flat_signal: '平直信号', constant_signal: '恒定信号',
  excessive_amplitude: '幅度过大', amplitude_out_of_range: '幅度超出范围',
  clipping: '信号削顶', saturation: '信号饱和', high_noise: '噪声过大',
  recollecting_after_inference_backlog: '分类处理积压后重新收集窗口',
  collecting_model_window: '正常收集模型窗口',
  nonfinite: '包含非有限数值', high_amplitude: '滤波后幅度过大', low_variation: '信号变化过低',
  packet_gap: '采集数据间断', duplicate_packet: '重复数据包',
  recollecting_after_packet_gap: '丢包或重复包后重新收集窗口',
  waiting_for_live_data: '等待设备恢复数据', insufficient_samples: '采样数量不足',
  sample_rate_mismatch: '采样率不匹配', channel_order_mismatch: '电极顺序不匹配',
}
export function readableReason(reason) {
  if (reason == null || reason === '') return ''
  if (typeof reason === 'string') return reasonLabels[reason] ? `${reasonLabels[reason]}（${reason}）` : reason
  if (Array.isArray(reason)) return reason.map(readableReason).join('；')
  return JSON.stringify(reason)
}
export function waveformDiagnostics(event) {
  const model = event?.waveform_model || {}
  const info = model.info || {}
  const details = event?.quality_details ?? model.quality_details ?? info.quality_details
  return {
    qualityReason: readableReason(event?.quality_reason ?? model.quality_reason ?? info.quality_reason),
    resetReason: readableReason(event?.reset_reason ?? model.reset_reason ?? info.reset_reason),
    details: Array.isArray(details) ? details.map(detail => {
      if (!detail || typeof detail !== 'object') return readableReason(detail)
      const { channel, reason, ...metrics } = detail
      const extra = Object.entries(metrics).map(([key, value]) => `${key}: ${readableReason(value)}`).join(' · ')
      return [channel == null ? '未知电极' : String(channel), readableReason(reason), extra].filter(Boolean).join(' · ')
    }) : details == null ? [] : [readableReason(details)],
  }
}
