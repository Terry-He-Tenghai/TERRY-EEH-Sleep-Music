import { test, expect } from '@playwright/test'

test('offline Web Audio renders audible bed and MIDI without sample clipping', async ({ page }) => {
  await page.goto('/')
  const result = await page.evaluate(async () => {
    const { AdaptiveEngine } = await import('/src/audio/adaptiveEngine.js')
    const { analyzeUpload } = await import('/src/audio/uploadLoudness.js')
    async function render(midiLevel) {
      const ctx = new OfflineAudioContext(2, 20*16000, 16000)
      const engine = new AdaptiveEngine()
      engine.ctx = ctx; engine.master = ctx.createGain(); engine.master.gain.value = 0
      engine.compressor = ctx.createDynamicsCompressor()
      engine.compressor.threshold.value = -12; engine.compressor.knee.value = 12
      engine.compressor.ratio.value = 4
      engine.compressor.connect(engine.master); engine.master.connect(ctx.destination)
      engine.filter = ctx.createBiquadFilter(); engine.filter.type = 'lowpass'; engine.filter.connect(engine.compressor)
      engine.wet = ctx.createGain()
      engine.midiTrim = ctx.createGain(); engine.midiTrim.gain.value = midiLevel; engine.midiTrim.connect(engine.filter)
      engine.buses = {}
      for (const voice of ['pad','melody','bass','texture']) {
        const gain = ctx.createGain(), pan = ctx.createStereoPanner()
        pan.connect(gain); gain.connect(voice === 'pad' ? engine.filter : engine.midiTrim)
        engine.buses[voice] = { gain, pan }
      }
      engine.buffer = ctx.createBuffer(1, 16000*8, 16000)
      const data = engine.buffer.getChannelData(0)
      for (let i=0; i<data.length; i++) data[i] = .02*Math.sin(2*Math.PI*220*i/16000)
      engine.bufferLoudness = await analyzeUpload(engine.buffer)
      const notes = Array.from({ length: 16 }, (_, i) => ({ start_beat: i, duration_beats: .8, midi_note: 72, velocity: 64, voice: 'melody' }))
      notes.push({ start_beat: 12, duration_beats: 4.5, midi_note: 60, velocity: 40, voice: 'texture' })
      const plan = { track: { id: 'user_test' }, gains: { master: .18, melody: .7, texture: .4 }, notes,
        waveform_parameters: { brightness: .7 }, waveform: 'triangle', enhancedMidi: true, continuousHarmony: true }
      engine.schedulePhrase(plan, .2)
      engine.schedulePhrase(plan, 16.2)
      const output = await ctx.startRendering()
      let sum=0, peak=0, count=0
      for (const value of output.getChannelData(0).slice(10*16000)) {
        sum += value*value; peak = Math.max(peak, Math.abs(value)); count++
      }
      engine.ctx = null // OfflineAudioContext has no close(); rendering is complete.
      engine.dispose()
      return { rms: Math.sqrt(sum/count), peak }
    }
    return { bed: await render(0), mix: await render(1), enhanced: await render(2) }
  })
  expect(result.bed.rms).toBeGreaterThan(.005)
  expect(result.mix.rms).toBeGreaterThan(result.bed.rms)
  expect(result.enhanced.rms).toBeGreaterThan(result.mix.rms)
  expect(result.enhanced.peak).toBeLessThan(1)
})
