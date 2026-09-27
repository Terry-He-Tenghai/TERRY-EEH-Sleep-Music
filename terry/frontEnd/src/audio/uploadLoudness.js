// Bounded RMS compensation, not LUFS normalization or a sound-pressure limit.
// Scan without modifying the decoded buffer; old uploads benefit too.
export async function analyzeUpload(buffer, isCurrent = () => true) {
  let sum = 0, peak = 0, count = 0
  for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
    const samples = buffer.getChannelData(channel)
    for (let start = 0; start < samples.length; start += 262144) {
      if (!isCurrent()) return null
      const end = Math.min(samples.length, start + 262144)
      for (let i = start; i < end; i++) {
        const value = samples[i]
        if (!Number.isFinite(value)) throw new Error('上传音频含无效采样值')
        sum += value * value; peak = Math.max(peak, Math.abs(value)); count++
      }
      // Yield so scanning a 15-minute upload cannot block the audio scheduler.
      await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
  const rms = count ? Math.sqrt(sum / count) : 0
  const silent = rms < 0.00001
  const gain = silent ? 1 : Math.min(4, .12 / rms, .9 / peak)
  return { rms, peak, gain, silent, targetRms: .12, maxGain: 4 }
}
