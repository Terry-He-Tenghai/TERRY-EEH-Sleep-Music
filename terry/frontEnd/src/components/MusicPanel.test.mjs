// Run: node --test src/components/MusicPanel.test.mjs
// Exercise component handlers with browser audio stubs; not an acoustic/device test.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'

const source = readFileSync(new URL('./MusicPanel.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
function harness() {
  let now = 0, id = 0, plays = 0, pauses = 0, mounted, unmounted
  const frames = new Map(), attributes = new Map()
  const player = { volume: 1, pause() { pauses++ }, play() { plays++; return Promise.resolve() },
    load() {}, getAttribute(key) { return attributes.get(key) }, removeAttribute(key) { attributes.delete(key) },
    set src(value) { attributes.set('src', value) } }
  const context = vm.createContext({ ref: value => ({ value }), computed: get => ({ get value() { return get() } }),
    onMounted: callback => { mounted = callback }, onBeforeUnmount: callback => { unmounted = callback },
    performance: { now: () => now }, requestAnimationFrame: callback => { frames.set(++id, callback); return id },
    cancelAnimationFrame: key => frames.delete(key), AbortController,
    window: { dispatchEvent() {}, addEventListener() {}, removeEventListener() {} }, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail } },
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
    fetch: async () => ({ ok: true, json: async () => ({ status: 'ready', tracks: [] }) }) })
  const script = descriptor.scriptSetup.content.replace(/^import .* from 'vue'\r?\n/m, '')
  vm.runInContext(`${script}\nglobalThis.api = { tracks, selectedId, audio, playing, starting, targetVolume, play, pause, stopImmediately, selectTrack, changeVolume, loadLibrary, onVisibility };`, context)
  const api = context.api
  api.audio.value = player
  api.tracks.value = [{ id: 'calm-01', available: true, review: { status: 'approved' } }]
  api.selectedId.value = 'calm-01'
  return { api, player, context, mount: () => mounted(), unmount: () => unmounted(),
    plays: () => plays, pauses: () => pauses,
    advance(ms) { now += ms; const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(now)) } }
}

test('Vue script and template compile', () => {
  compileScript(descriptor, { id: 'music-panel-test' })
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'MusicPanel.vue', id: 'music-panel-test' }).errors, [])
  assert.doesNotMatch(descriptor.template.content, /\bautoplay\b/)
})
test('mount and selection never autoplay', async () => {
  const h = harness(); h.mount(); await Promise.resolve(); await Promise.resolve()
  h.api.selectTrack(); assert.equal(h.plays(), 0); assert.equal(h.player.volume, 0)
  h.unmount()
})
test('explicit click starts at zero and fades to conservative default', async () => {
  const h = harness(); await h.api.play()
  assert.equal(h.plays(), 1); assert.equal(h.player.volume, 0)
  assert.equal(h.player.getAttribute('src'), '/api/music/calm-01/audio')
  h.advance(750); assert.ok(h.player.volume > 0 && h.player.volume < .15)
  h.advance(750); assert.equal(h.player.volume, .15)
  h.api.targetVolume.value = 100; h.api.changeVolume(); h.advance(1500)
  assert.equal(h.player.volume, .4)
  h.api.pause(); h.advance(800); assert.equal(h.player.volume, 0); assert.equal(h.api.playing.value, false)
})
test('review status no longer gates playback; unavailable files still cannot play', async () => {
  for (const status of ['pending', 'rejected']) {
    const h = harness(); h.api.tracks.value[0].review.status = status
    await h.api.play(); assert.equal(h.plays(), 1)
  }
  const h = harness(); h.api.tracks.value[0].available = false
  await h.api.play(); assert.equal(h.plays(), 0)
})
test('stop during pending play prevents fade and playing state', async () => {
  const h = harness(); let resolve
  h.player.play = () => new Promise(done => { resolve = done })
  const pending = h.api.play(); h.api.stopImmediately(); resolve(); await pending; h.advance(2000)
  assert.equal(h.player.volume, 0); assert.equal(h.api.playing.value, false)
})
test('switch, visibility change and unmount silence playback', async () => {
  const h = harness(); await h.api.play(); h.advance(1500)
  h.api.selectTrack(); assert.equal(h.player.volume, 0)
  assert.equal(h.player.getAttribute('src'), undefined)
  await h.api.play(); h.advance(1500); h.context.document.hidden = true; h.api.onVisibility()
  assert.equal(h.player.volume, 0)
  h.unmount(); assert.ok(h.pauses() >= 3)
})
