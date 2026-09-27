import test from 'node:test'
import assert from 'node:assert/strict'
import { effectiveStemMix, sampleAudio } from '../audio/stemMix.js'

test('contrast expands musical roles while keeping output gain separate', () => {
  const base = { mode: 'adaptive', control_level: .5, brightness: .5, gains: { piano:.44, strings:.22, bass:.18, pad:.18 } }
  const quiet = effectiveStemMix({ ...base, control_level: .05 }, 1)
  const awake = effectiveStemMix({ ...base, control_level: .95 }, 1)
  assert.ok(quiet.gains.strings > awake.gains.strings)
  assert.ok(awake.gains.piano > quiet.gains.piano)
  assert.ok(awake.gains.bass > quiet.gains.bass)
  assert.notEqual(quiet.cutoff, awake.cutoff)
  const conservative = effectiveStemMix({ ...base, mode: 'conservative', control_level: null, gains: { piano:.12, strings:.08, bass:.02, pad:.1 } }, 1)
  assert.equal(conservative.gains.piano, .12)
})
test('audio analyzer returns fixed-scale waveform, spectrum and level', () => {
  const analyser = { getFloatTimeDomainData(a) { a.set([0, .25, -.25, 0]) }, getByteFrequencyData(a) { a.fill(0); a[2] = 128 } }
  const result = sampleAudio(analyser, new Float32Array(4), new Uint8Array(4))
  assert.equal(result.waveform.length, 128); assert.equal(result.spectrum.length, 32)
  assert.ok(result.rms > 0 && result.peak > 0 && result.rmsDb < 0)
})
