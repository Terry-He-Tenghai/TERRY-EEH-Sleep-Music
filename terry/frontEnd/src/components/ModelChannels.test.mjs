import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, watch, nextTick } from 'vue'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { CAP_CHANNELS, MODEL_OPTIONS, modelChannels, plotChannelIndices, qualityChannels, modelChannelInfo, waveformDiagnostics } from '../audio/modelChannels.js'
import { liveClassification, waveformStatus, waveformCollection } from '../audio/liveClassification.js'

const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
function appHarness() {
  const script = parse(app).descriptor.scriptSetup.content.replace(/^import .*$/gm, '').replace(/import\.meta\.env\.\w+/g, "''")
  const bindings = { ref, computed, watch, nextTick, onMounted() {}, onBeforeUnmount() {},
    CAP_CHANNELS, MODEL_OPTIONS, plotChannelIndices, qualityChannels, classifyLive: liveClassification,
    waveformStatus, waveformCollection, location: { protocol: 'http:', host: 'localhost' },
    window: { devicePixelRatio: 1 } }
  return new Function(...Object.keys(bindings), `${script}\nreturn { mode, classificationChannels, showAllChannels, plotIndices, plottedChannels, signal, canvas, enabledCount, appendSamples, channelsMatch, waveformError, draw, toggleAll }`)(...Object.values(bindings))
}

test('all five model options retain exact electrode order and CAP16 data indices', () => {
  const expected = [[2, ['C3', 'C4'], [2, 3]], [4, ['Fp1', 'Fp2', 'C3', 'C4'], [0, 1, 2, 3]],
    [6, ['Fp1', 'Fp2', 'C3', 'C4', 'F3', 'F4'], [0, 1, 2, 3, 10, 11]],
    [8, CAP_CHANNELS.slice(0, 8), Array.from({ length: 8 }, (_, i) => i)],
    [16, [...CAP_CHANNELS], Array.from({ length: 16 }, (_, i) => i)]]
  assert.deepEqual(MODEL_OPTIONS.map(option => option.count), [2, 4, 6, 8, 16])
  for (const [count, channels, indices] of expected) {
    assert.deepEqual(modelChannels(count), channels)
    assert.deepEqual(plotChannelIndices(CAP_CHANNELS, count), indices)
    assert.deepEqual(qualityChannels(count), count <= 6 ? channels : [...CAP_CHANNELS])
    assert.deepEqual(plotChannelIndices(CAP_CHANNELS, count, true), Array.from({ length: 16 }, (_, i) => i))
  }
})

test('App model/show-all changes preserve full buffer and strict ordered message validation', async () => {
  const h = appHarness()
  h.mode.value = 'brainflow'; await nextTick()
  for (const count of [2, 4, 6, 8, 16]) {
    h.classificationChannels.value = count
    h.showAllChannels.value = false
    await nextTick()
    assert.equal(h.signal.value.length, 16)
    assert.equal(h.plotIndices.value.length, count)
    assert.equal(h.channelsMatch([...CAP_CHANNELS]), true)
    assert.equal(h.channelsMatch(modelChannels(2)), false)
    h.appendSamples({ channels: [...CAP_CHANNELS], sample_rate_hz: 250, timestamp_s: 0, samples_uv: CAP_CHANNELS.map((_, i) => [i, i + 1]) })
    const buffer = h.signal.value
    assert.deepEqual(buffer[10].slice(-2), [10, 11])
    h.showAllChannels.value = true; await nextTick()
    assert.equal(h.plotIndices.value.length, 16)
    assert.equal(h.signal.value, buffer)
    assert.equal(h.enabledCount.value, 16)
    assert.deepEqual(h.plottedChannels.value.map(channel => channel.name), [...CAP_CHANNELS])
    const wrongOrder = [...CAP_CHANNELS].reverse()
    h.appendSamples({ channels: wrongOrder, sample_rate_hz: 250, samples_uv: CAP_CHANNELS.map(() => [99]) })
    assert.equal(h.signal.value, buffer)
    assert.match(h.waveformError.value, /不匹配/)
  }
})

test('App draws selected names from original indices, while visible toggles only affect plotting', async () => {
  const h = appHarness()
  h.mode.value = 'brainflow'; h.classificationChannels.value = 6
  await nextTick()
  const labels = [], colors = []
  const context = { setTransform() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() { colors.push(this.strokeStyle) }, fillText(text) { labels.push(text) } }
  h.canvas.value = { width: 0, height: 0, getBoundingClientRect: () => ({ width: 600, height: 500 }), getContext: () => context }
  h.appendSamples({ channels: [...CAP_CHANNELS], sample_rate_hz: 250, timestamp_s: 0, samples_uv: CAP_CHANNELS.map((_, i) => [i, i + 2]) })
  assert.deepEqual(labels.slice(0, 6), ['Fp1', 'Fp2', 'C3', 'C4', 'F3', 'F4'])
  assert.deepEqual(colors.slice(-6), ['#27708b', '#a35b25', '#867017', '#7954a3', '#a94747', '#8159a0'])
  assert.deepEqual(h.plottedChannels.value.slice(-2), [{ name: 'F3', index: 10 }, { name: 'F4', index: 11 }])
  h.toggleAll({ target: { checked: false } })
  assert.equal(h.enabledCount.value, 0)
  h.showAllChannels.value = true
  assert.equal(h.enabledCount.value, 10)
  assert.equal(h.signal.value.length, 16)
})

test('backend model info and structured quality details are readable without changing gates', () => {
  const event = { classification_channels: 2, waveform_model: { info: {
    selected_channels: ['C3', 'C4'], quality_channels: ['C3', 'C4'],
    quality_details: [{ channel: 'C3', reason: 'flatline', std_uv: 0 }, { channel: 'C4', reason: 'future_reason', amplitude_uv: 200 }],
    quality_reason: 'invalid_or_low_quality_eeg', reset_reason: 'packet_gap',
  } } }
  assert.deepEqual(modelChannelInfo(event), { selected: ['C3', 'C4'], quality: ['C3', 'C4'] })
  const result = waveformDiagnostics(event)
  assert.match(result.qualityReason, /质量检查未通过/)
  assert.match(result.resetReason, /采集数据间断/)
  assert.match(result.details[0], /C3.*平直信号.*std_uv: 0/)
  assert.match(result.details[1], /C4.*future_reason.*amplitude_uv: 200/)
  assert.deepEqual(modelChannelInfo({ classification_channels: 8 }).quality, [...CAP_CHANNELS])
  assert.deepEqual(waveformDiagnostics(null).details, [])
  assert.equal(waveformDiagnostics({ quality_details: [null] }).details[0], '')
})

test('model quality component compiles and every music pathway displays it', () => {
  const source = readFileSync(new URL('./WaveformQuality.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  compileScript(descriptor, { id: 'WaveformQuality' })
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'WaveformQuality.vue', id: 'WaveformQuality' }).errors, [])
  for (const filename of ['AutomaticAcePanel.vue', 'StemMusicPanel.vue', 'AdaptiveMusicPanel.vue']) {
    assert.match(readFileSync(new URL(filename, import.meta.url), 'utf8'), /<WaveformQuality/)
  }
  assert.match(app, /查看全部 16 路/)
  assert.match(app, /采集通道/)
  assert.match(app, /分类通道/)
  assert.match(app, /可见通道/)
})
