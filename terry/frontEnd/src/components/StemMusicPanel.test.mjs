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

test('all waveform model sizes support stems without relaxing confirmation or quality gates', () => {
  for (const count of [2, 4, 6, 8, 16]) {
    const e = { ...event(), inference_mode: 'waveform_cnn', probability_origin: 'trained_waveform_cnn_experimental',
      classification_channels: count, classification_confirmed: true, state: { status: 'ok', baseline_ready: false } }
    assert.equal(validateStemFrame(e, 'Track00008').mode, 'adaptive')
    assert.throws(() => validateStemFrame({ ...e, classification_confirmed: false }, 'Track00008'))
    assert.throws(() => validateStemFrame({ ...e, signal_quality: .99 }, 'Track00008'))
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
  engine.serverStamp=Date.now()-16000; engine.tick(); assert.equal(engine.status,'holding')
  const gain=engine.master.gain.value; engine.setStrength(.2); assert.equal(engine.master.gain.value,gain)
  engine.stop()
})
test('LIVE invalid electrodes keep existing stems without new classification; recovery resumes controls', () => {
  const { engine }=harness(); engine.consume(event()); engine.tick(); engine.ctx.currentTime = .1
  const plan = engine.plan, applied = engine.applied, freshness = engine.lastReady
  engine.consume({ ...event(2), status:'frozen', stem_mix:null, reason:'invalid_or_low_quality_eeg', probabilities: null, state: null })
  assert.equal(engine.entries.size,4); assert.equal(engine.plan,plan); assert.equal(engine.applied, applied)
  assert.equal(engine.liveHeld, true); assert.equal(engine.lastReady, freshness)
  engine.consume(event(3)); engine.tick(); assert.equal(engine.entries.size,4)
  assert.equal(engine.liveHeld, false); assert.equal(engine.applied.sequence, 3)
  engine.stop()
})

test('LIVE stale stems retain the applied mix through loop cycles and resume only with fresh data', () => {
  const { engine, sources } = harness(); engine.consume(event()); engine.tick()
  const applied = engine.applied, ready = engine.lastReady
  engine.serverStamp = Date.now()-16000
  const stamp = engine.serverStamp
  engine.ctx.currentTime = 19; engine.tick()
  assert.equal(engine.status, 'holding'); assert.equal(engine.entries.size, 8)
  assert.equal(sources.length, 8); assert.equal(engine.master.gain.value, .18)
  engine.setStrength(.1); engine.setComparison(true)
  assert.equal(engine.applied, applied); assert.equal(engine.lastReady, ready); assert.equal(engine.serverStamp, stamp)
  engine.consume({ ...event(2), emitted_at_s: (Date.now()-16000)/1000 })
  assert.equal(engine.sequence, 1); assert.equal(engine.applied, applied)
  engine.consume(event(3)); engine.tick()
  assert.equal(engine.status, 'playing'); assert.equal(engine.applied.sequence, 3)
  engine.stop(); assert.equal(engine.entries.size, 0); assert.equal(engine.armed, false)
  assert.ok(sources.every(s => s.end === undefined))
})
test('LIVE waiting for data holds started stems, prevents delayed start, and stops on session change or unload', () => {
  for (const started of [false, true]) {
    const { engine } = harness(); engine.consume(event())
    if (started) { engine.tick(); engine.ctx.currentTime = .1; engine.tick() }
    const ready = engine.lastReady
    engine.consume({ ...event(2), status: 'frozen', stem_mix: null, reason: 'waiting_for_live_data' })
    engine.tick()
    assert.equal(engine.entries.size, started ? 4 : 0)
    assert.equal(engine.status, started ? 'holding' : 'waiting'); assert.equal(engine.lastReady, ready)
    engine.consume(event(3)); engine.tick(); assert.equal(engine.entries.size, 4)
    engine.consume({ ...event(4), session_id: 2 }); assert.equal(engine.armed, false); assert.equal(engine.entries.size, 0)
    engine.dispose()
  }
  const { engine } = harness(); engine.consume(event()); engine.serverStamp = Date.now()-16000; engine.tick()
  assert.equal(engine.entries.size, 0); assert.equal(engine.origin, undefined)
  engine.dispose()
})
test('LIVE held stems obey stopped events and disposal', () => {
  for (const dispose of [false, true]) {
    const { engine } = harness(); engine.consume(event()); engine.tick()
    engine.serverStamp = Date.now()-16000; engine.tick()
    if (dispose) engine.dispose()
    else engine.consume({ ...event(1), emitted_at_s: (Date.now()-16000)/1000, status: 'stopped', stem_mix: null })
    assert.equal(engine.entries.size, 0); assert.equal(engine.armed, false)
  }
})
