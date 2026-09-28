import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { StemEngine, validateStemFrame } from '../audio/stemEngine.js'

function event(sequence = 1) {
  return { type: 'adaptive_music', session_id: 1, sequence, emitted_at_s: Date.now()/1000, source: 'LIVE', status: 'ready', playback_mode: 'adaptive',
    state: { status: 'ok', baseline_ready: true }, probabilities: { W: .8, N1: .15, N2: .05 }, signal_quality: 1,
    stem_mix: { track_id: 'Track00008', mode: 'adaptive', control_level: .8, brightness: .8, transition_seconds: 3, gains: { piano: .8, bass: .4, strings: .2, pad: .2 } } }
}
function harness() {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
  const param = () => ({ value: 0, cancelAndHoldAtTime() {}, cancelScheduledValues() {}, setValueAtTime(v) { this.value=v }, linearRampToValueAtTime(v) { this.value=v } })
  const sources = []
  const node = () => ({ gain: param(), frequency: param(), connect() {}, disconnect() {} })
  const engine = new StemEngine()
  engine.ctx = { state: 'running', currentTime: 0, close: () => Promise.resolve(), createGain: node, createBufferSource: () => {
    const source = { connect() {}, disconnect() {}, start(at) { this.at=at }, stop(at) { this.end=at } }; sources.push(source); return source
  } }
  engine.master = node(); engine.filter = node(); engine.armed = true; engine.armedAt = Date.now()
  engine.trackId = 'Track00008'; engine.sequence = -1; engine.duration = 20
  engine.stems = ['bass','piano','strings','piano'].map((role,i) => ({ id: `S0${i}`, role, gain: node(), buffer: {} }))
  return { engine, sources }
}
test('App and stem panel compile', () => {
  for (const file of ['./StemMusicPanel.vue', '../App.vue']) {
    const { descriptor } = parse(readFileSync(new URL(file, import.meta.url), 'utf8'))
    compileScript(descriptor, { id: 'stem-test' })
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: file, id: 'stem-test' }).errors, [])
  }
})
test('stem events reject stale, wrong track, invalid gain and unready classification', () => {
  assert.equal(validateStemFrame(event(), 'Track00008').mode, 'adaptive')
  for (const mutate of [e => { e.emitted_at_s -= 16 }, e => { e.stem_mix.track_id = 'Track00020' }, e => { e.stem_mix.gains.piano = NaN }, e => { e.state.baseline_ready = false }]) {
    const e=event(); mutate(e); assert.throws(() => validateStemFrame(e, 'Track00008'))
  }
})
test('live spectral classification permits 8 or 16 channel stem feedback without a trained baseline', () => {
  for (const count of [8, 16]) {
    const e = event()
    e.state.baseline_ready = false
    e.inference_mode = 'spectral_heuristic'
    e.probability_origin = 'eeg_spectral_heuristic_unvalidated'
    e.classification_channels = count
    e.channel_repair = { used_channels: Array.from({ length: count }, (_, i) => `CH${i}`), valid_fraction: count / 16 }
    e.signal_quality = count / 16
    assert.equal(validateStemFrame(e, 'Track00008').mode, 'adaptive')
    delete e.probability_origin
    assert.throws(() => validateStemFrame(e, 'Track00008'))
  }
})

test('conservative plan has no fabricated EEG control value', () => {
  const e=event(); e.playback_mode='conservative'; e.stem_mix.mode='conservative'; e.stem_mix.control_level=null
  e.stem_mix.gains={piano:.12,strings:.08,bass:.02,pad:.10}
  e.channel_repair={valid_channels:['C3']}; e.state=null; e.probabilities=null
  assert.equal(validateStemFrame(e,'Track00008').control_level,null)
})

test('four original stems start on one clock; changing EEG does not restart them', () => {
  const { engine, sources } = harness()
  engine.consume(event()); engine.tick()
  assert.equal(sources.length, 4); assert.equal(new Set(sources.map(s => s.at)).size, 1)
  const e=event(2); e.stem_mix.control_level=.1; e.stem_mix.gains.piano=.1; e.stem_mix.gains.strings=.8
  engine.consume(e); engine.tick()
  assert.equal(sources.length, 4)
  assert.ok(engine.stems[1].gain.gain.value < .1)
  assert.ok(engine.stems[2].gain.gain.value > .2)
  engine.stop(); assert.equal(engine.entries.size, 0)
})
test('fresh frames sustain ten minutes, repeated sequence cannot refresh freshness', () => {
  const { engine, sources } = harness()
  for (let t=0; t<600; t+=.1) {
    engine.ctx.currentTime=t
    engine.consume(event(engine.sequence+1)); engine.tick()
    for (const source of sources) if (source.end <= t) { source.onended?.(); source.onended=null }
    assert.ok(engine.entries.size <= 8)
  }
  assert.ok(sources.length >= 120)
  const old=engine.lastReady
  engine.consume(event(engine.sequence)); assert.equal(engine.lastReady,old)
  engine.serverStamp=Date.now()-16000; engine.tick(); assert.equal(engine.status,'fading')
  const gain=engine.master.gain.value; engine.setVolume(.3); assert.equal(engine.master.gain.value,gain)
  engine.stop()
})
test('invalid electrodes silence without reusing prior classification; recovery starts afresh', () => {
  const { engine }=harness(); engine.consume(event()); engine.tick()
  engine.consume({ ...event(2), status:'frozen', stem_mix:null, reason:'no_valid_electrodes' })
  assert.equal(engine.entries.size,0); assert.equal(engine.plan,null)
  engine.consume(event(3)); engine.tick(); assert.equal(engine.entries.size,4)
  engine.stop()
})
