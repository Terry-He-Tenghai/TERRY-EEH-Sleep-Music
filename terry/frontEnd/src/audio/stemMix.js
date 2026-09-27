// Musical contrast, not an output-volume multiplier. Conservative plans never boost.
export function effectiveStemMix(plan, strength = .85, bypass = false) {
  if (plan.mode === 'conservative') return { ...plan, cutoff: 800 + 6200 * plan.brightness }
  if (bypass) return { ...plan, gains: { piano: .3, strings: .3, bass: .3, pad: .3 }, cutoff: 7200, comparison: true }
  const amount = Math.max(0, Math.min(1, strength))
  const level = Math.max(0, Math.min(1, plan.control_level))
  const shaped = level * level * (3 - 2 * level)
  const contrast = { piano: .015 + .835 * shaped, bass: .01 + .40 * shaped,
    strings: .70 - .65 * shaped, pad: .62 - .58 * shaped }
  const gains = Object.fromEntries(Object.entries(plan.gains).map(([role, value]) => [role, value + amount * (contrast[role] - value)]))
  const cutoff = (800 + 6200 * plan.brightness) * (1 - amount) + (550 + 6650 * shaped) * amount
  return { ...plan, gains, cutoff, strength: amount, comparison: false }
}

export function sampleAudio(analyser, wave, frequency) {
  analyser.getFloatTimeDomainData(wave)
  analyser.getByteFrequencyData(frequency)
  let squares = 0, peak = 0
  for (const value of wave) { squares += value * value; peak = Math.max(peak, Math.abs(value)) }
  const rms = Math.sqrt(squares / wave.length)
  // Display gain is constant and labeled; never normalize silence into motion.
  const waveform = Array.from({ length: 128 }, (_, i) => wave[Math.floor(i * wave.length / 128)])
  const spectrum = Array.from({ length: 32 }, (_, i) => {
    const from = Math.floor(i * frequency.length / 32), to = Math.floor((i + 1) * frequency.length / 32)
    let max = 0
    for (let j = from; j < to; j++) max = Math.max(max, frequency[j])
    return max / 255
  })
  return { waveform, spectrum, rms, peak, rmsDb: rms > 0 ? Math.max(-100, 20 * Math.log10(rms)) : -100 }
}
