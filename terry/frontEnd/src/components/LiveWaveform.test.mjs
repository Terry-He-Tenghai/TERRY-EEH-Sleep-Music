import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, watch, reactive } from 'vue'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { liveClassification, isFreshLiveEvent, canPlayAutomatic, waveformStatus, waveformCollection, waveformHoldReasons } from '../audio/liveClassification.js'

const now = 100000
const ready = () => ({ source: 'LIVE', session_id: '1', emitted_at_s: now / 1000,
  inference_mode: 'waveform_cnn', probability_origin: 'trained_waveform_cnn_experimental',
  status: 'ready', state: { status: 'ok' }, probabilities: { W: .1, N1: .2, N2: .7 },
  classification_confirmed: true, classification_channels: 8, playback_mode: 'adaptive',
  waveform_model: { model: 'cap8', collected_seconds: 40, required_seconds: 40, experimental: true } })

test('LIVE display requires running, fresh normalized finite W/N1/N2 model scores', () => {
  assert.deepEqual(liveClassification(ready(), true, now), ['N2', .7])
  assert.equal(liveClassification(ready(), false, now), null)
  for (const event of [
    { ...ready(), emitted_at_s: 84.999 }, { ...ready(), emitted_at_s: 101 },
    { ...ready(), probability_origin: 'eeg_spectral_heuristic_unvalidated' },
    { ...ready(), state: { status: 'invalid' } }, { ...ready(), status: 'frozen' },
    ...[null, { W: NaN, N1: .2, N2: .8 }, { W: .2, N1: .2, N2: .2 },
      { W: -.1, N1: .2, N2: .9 }, { W: .5, N1: .5 }].map(probabilities => ({ ...ready(), probabilities })),
  ]) assert.equal(liveClassification(event, true, now), null)
  assert.equal(isFreshLiveEvent({ ...ready(), emitted_at_s: 85 }, now), true)
  assert.equal(isFreshLiveEvent({ ...ready(), emitted_at_s: '100' }, now), false)
  assert.deepEqual(liveClassification({ ...ready(), probabilities: { ...ready().probabilities, REM: 1 } }, true, now), ['N2', .7])
})

test('confirmation scores display while automatic playback remains blocked', () => {
  const event = { ...ready(), status: 'waiting', classification_confirmed: false, inference_hold_reason: 'confirming_state_classification' }
  assert.ok(liveClassification(event, true, now))
  assert.equal(canPlayAutomatic(event, now), false)
  assert.equal(canPlayAutomatic(ready(), now), true)
  for (const patch of [{ classification_confirmed: false }, { playback_mode: 'conservative' },
    { status: 'waiting' }, { status: 'blocked' }, { probabilities: null }, { emitted_at_s: 84 }]) {
    assert.equal(canPlayAutomatic({ ...ready(), ...patch }, now), false)
  }
  assert.equal(canPlayAutomatic({ source: 'DEMO', status: 'ready', session_id: 'demo' }, now), true)
  assert.equal(canPlayAutomatic({ source: 'DEMO', status: 'ready', session_id: 'demo', demo_scripted: true }, now), false)
})

test('model warmup and all new hold reasons have explicit labels', () => {
  assert.equal(waveformCollection({ waveform_model: { collected_seconds: 12.34 } }), '12.3 / 40 秒')
  assert.match(waveformStatus({ ...ready(), reason: 'collecting_model_window' }, now), /40 秒/)
  for (const reason of ['confirming_state_classification', 'invalid_or_low_quality_eeg', 'waiting_for_live_data',
    'recollecting_after_packet_gap', 'waveform_model_missing', 'waveform_model_contract_mismatch',
    'waveform_model_load_failed', 'waveform_requires_full_cap_capture', 'waveform_model_configuration_error']) {
    assert.equal(waveformStatus({ ...ready(), reason }, now), waveformHoldReasons[reason])
  }
  assert.match(waveformStatus(ready(), now + 15001), /暂停/)
})

const panel = readFileSync(new URL('./AutomaticAcePanel.vue', import.meta.url), 'utf8')
test('App and automatic panel compile with research-only waveform labels', () => {
  for (const [filename, source] of [['AutomaticAcePanel.vue', panel], ['App.vue', readFileSync(new URL('../App.vue', import.meta.url), 'utf8')]]) {
    const { descriptor } = parse(source)
    compileScript(descriptor, { id: filename })
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: filename }).errors, [])
    assert.match(source, /不是校准置信度/)
    assert.match(source, /未经本设备验证/)
    assert.doesNotMatch(source, /频谱估计|YASA/)
  }
})

function harness(fetcher, decode = async () => ({})) {
  let time = now, interval, cleanup
  const nodes = []
  const param = () => ({ value: 0, setValueAtTime() {}, linearRampToValueAtTime() {}, cancelScheduledValues() {} })
  class AudioContext {
    currentTime = 0
    destination = {}
    resume() { return Promise.resolve() }
    close() {}
    createGain() { return { gain: param(), connect() {}, disconnect() {} } }
    createBufferSource() {
      const node = { connect() {}, disconnect() {}, start() { this.started = true }, stop() { this.stopped = true } }
      nodes.push(node); return node
    }
    decodeAudioData(data) { return decode(data) }
  }
  const props = reactive({ event: ready() })
  const script = parse(panel).descriptor.scriptSetup.content.replace(/^import .*$/gm, '').replace('import.meta.env.VITE_API_BASE', "''")
  // Execute the actual script-setup functions with mocked browser/audio/timer APIs.
  const names = ['ref', 'computed', 'watch', 'onBeforeUnmount', 'defineProps', 'defineExpose', 'window', 'fetch',
    'setInterval', 'clearInterval', 'Date', 'canPlayAutomatic', 'waveformCollection', 'waveformHoldReasons', 'waveformStatus']
  const fakeDate = { now: () => time }
  const exposed = new Function(...names, `${script}\nreturn { arm, stop, refresh }`)(
    ref, computed, watch, fn => { cleanup = fn }, () => props, () => {}, { AudioContext }, fetcher,
    fn => { interval = fn; return 1 }, () => {}, fakeDate,
    (event, timestamp = time) => canPlayAutomatic(event, timestamp), waveformCollection, waveformHoldReasons,
    (event, timestamp = time) => waveformStatus(event, timestamp))
  return { ...exposed, props, nodes, tick: () => interval(), setTime: value => { time = value }, cleanup: () => cleanup() }
}
const statusResponse = { ok: true, json: async () => ({ status: 'ready', session_id: '1', audio_url: '/audio.wav' }) }
const audioResponse = { ok: true, arrayBuffer: async () => new ArrayBuffer(1) }
const settle = () => new Promise(resolve => setImmediate(resolve))

test('looping audio stops on stale LIVE event without another backend message', async () => {
  let calls = 0
  const h = harness(async () => ++calls % 2 ? statusResponse : audioResponse)
  try {
    await h.arm(); await settle()
    assert.equal(h.nodes[0].started, true)
    h.setTime(now + 15001)
    await h.tick()
    assert.equal(h.nodes[0].stopped, true)
    assert.equal(calls, 2, 'no fetch is issued for stale input')
  } finally { h.cleanup() }
})

test('freshness is checked after asynchronous audio decoding', async () => {
  let finish, calls = 0
  const h = harness(async () => ++calls % 2 ? statusResponse : audioResponse,
    () => new Promise(resolve => { finish = resolve }))
  try {
    await h.arm(); await settle()
    h.setTime(now + 15001); finish({}); await settle()
    assert.equal(h.nodes.length, 0)
  } finally { h.cleanup() }
})

test('waiting and nonconfirmed events stop sound immediately even with unchanged status', async () => {
  for (const patch of [{ status: 'waiting' }, { classification_confirmed: false }, { state: { status: 'invalid' } }]) {
    let calls = 0
    const h = harness(async () => ++calls % 2 ? statusResponse : audioResponse)
    try {
      await h.arm(); await settle()
      h.props.event = { ...ready(), ...patch }
      assert.equal(h.nodes[0].stopped, true)
      await h.tick()
      assert.equal(calls, 2)
    } finally { h.cleanup() }
  }
})

test('waiting during audio decoding aborts the request and prevents late playback', async () => {
  let finish, calls = 0, audioSignal
  const h = harness(async (_url, options) => {
    if (++calls === 1) return statusResponse
    audioSignal = options.signal
    return audioResponse
  }, () => new Promise(resolve => { finish = resolve }))
  try {
    await h.arm(); await settle()
    h.props.event = { ...ready(), status: 'waiting', inference_hold_reason: 'confirming_state_classification' }
    assert.equal(audioSignal.aborted, true)
    finish({}); await settle()
    assert.equal(h.nodes.length, 0)
  } finally { h.cleanup() }
})

test('stale guard aborts a pending status request before loading can suppress checks', async () => {
  let signal
  const h = harness((_url, options) => {
    signal = options.signal
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  })
  try {
    await h.arm()
    h.setTime(now + 15001); await h.tick()
    assert.equal(signal.aborted, true)
  } finally { h.cleanup() }
})
