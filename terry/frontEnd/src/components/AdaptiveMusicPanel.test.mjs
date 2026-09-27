import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { analyzeUpload } from '../audio/uploadLoudness.js'
import { AdaptiveEngine, peakPolyphony } from '../audio/adaptiveEngine.js'

const buffer = values => ({ numberOfChannels: 1, getChannelData: () => Float32Array.from(values) })
test('quiet and loud uploads receive bounded compensation without modifying source', async () => {
  const quiet = await analyzeUpload(buffer([.01, -.01]))
  assert.equal(quiet.gain, 4)
  const loud = await analyzeUpload(buffer([.8, -.8]))
  assert.ok(loud.gain < 1)
  const impulse = await analyzeUpload(buffer([1, ...Array(999).fill(.01)]))
  assert.ok(impulse.peak * impulse.gain <= .900001)
  assert.equal((await analyzeUpload(buffer([0, 0]))).gain, 1)
  assert.equal(await analyzeUpload(buffer([.1]), () => false), null)
  await assert.rejects(analyzeUpload(buffer([NaN])))
})
test('adaptive panel compiles with independent MIDI and upload controls', () => {
  const { descriptor } = parse(readFileSync(new URL('./AdaptiveMusicPanel.vue', import.meta.url), 'utf8'))
  compileScript(descriptor, { id: 'adaptive-test' })
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'AdaptiveMusicPanel.vue', id: 'adaptive-test' }).errors, [])
})

test('sustained harmony normalization counts simultaneous rather than sequential notes', () => {
  const sustain = { voice: 'texture', start_beat: 0, duration_beats: 4, velocity: 40 }
  const melody = Array.from({ length: 8 }, (_, i) => ({ voice: 'melody', start_beat: i*.5, duration_beats: .4, velocity: 60 }))
  assert.equal(peakPolyphony([sustain, ...melody], sustain), 2)
})

function harness() {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
  const param = () => ({ value: 0, setValueAtTime(v) { this.value = v }, linearRampToValueAtTime(v) { this.value = v }, cancelAndHoldAtTime() {}, cancelScheduledValues() {} })
  const nodes = []
  const node = () => {
    const n = { gain: param(), pan: param(), frequency: param(), outputs: [],
      connect(to) { this.outputs.push(to) }, disconnect() {}, start(at) { this.startTime = at }, stop(at) { this.stopTime = at } }
    nodes.push(n); return n
  }
  const engine = new AdaptiveEngine()
  engine.ctx = { currentTime: 0, state: 'running', createGain: node, createBufferSource: node, createOscillator: node }
  engine.master = node(); engine.compressor = node(); engine.filter = node(); engine.wet = node()
  engine.buses = Object.fromEntries(['pad','melody','bass','texture'].map(v => [v, { gain: node(), pan: node() }]))
  engine.buffer = {}; engine.bufferId = 'user_test'; engine.bufferLoudness = { gain: 4 }
  const plan = { track: { id: 'user_test' }, music_state: 'M1', gains: { master: .18 }, waveform_parameters: {}, waveform: 'triangle', enhancedMidi: true, continuousHarmony: true, notes: [
    { voice: 'melody', start_beat: 0, duration_beats: 1, midi_note: 72, velocity: 64 },
    { voice: 'texture', start_beat: 12, duration_beats: 4.5, midi_note: 60, velocity: 40 },
  ] }
  return { engine, plan, nodes }
}
test('upload bypasses pad attenuation; overtone shares envelope and is stoppable', () => {
  const { engine, plan } = harness()
  engine.schedulePhrase(plan, 1)
  assert.equal(engine.master.gain.value, .18)
  assert.deepEqual(engine.trackSource.uploadGain.outputs, [engine.compressor])
  assert.equal(engine.trackSource.source.loop, true)
  const sources = [...engine.sources]
  assert.equal(sources.length, 4) // bed, melody fundamental, overtone, texture
  const overtone = sources.find(e => e.source.frequency.value > 1000)
  assert.ok(overtone)
  assert.equal(overtone.nodes[0].outputs[0].outputs[0], engine.buses.melody.pan)
  assert.ok(sources.some(e => Math.abs(e.source.stopTime - 17.51) < .0001))
  engine.silence()
  assert.equal(engine.sources.size, 0)
})
test('fresh plans schedule continuously for ten minutes without restarting bed', () => {
  const { engine, plan } = harness()
  engine.armed = true; engine.pending = plan
  for (let time = 0; time <= 600; time += .05) {
    engine.ctx.currentTime = time
    engine.lastReadyAt = performance.now(); engine.readyTimestamp = Date.now()
    engine.tick()
    for (const entry of [...engine.sources]) {
      if (entry.source.stopTime <= time) entry.source.onended?.()
    }
    assert.equal(engine.armed, true)
    assert.ok(engine.sources.size <= 8)
  }
  assert.ok(engine.events.filter(e => e.type === 'phrase-scheduled').length >= 37)
  assert.equal(engine.events.filter(e => e.type === 'track-crossfade-scheduled').length, 1)
})
test('stale plans still trigger fade rather than indefinite playback', () => {
  const { engine, plan } = harness()
  engine.armed = true; engine.pending = plan; engine.lastReadyAt = performance.now()
  engine.readyTimestamp = Date.now() - 16000
  let reason
  engine.fadeStop = value => { reason = value }
  engine.tick()
  assert.match(reason, /15秒/)
})
