<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const tracks = ref([]), selectedId = ref(''), loading = ref(false), error = ref('')
const libraryStatus = ref('missing'), audio = ref(null), playing = ref(false), starting = ref(false)
const targetVolume = ref(15), currentVolume = ref(0)
const selected = computed(() => tracks.value.find(track => track.id === selectedId.value))
const playable = computed(() => selected.value?.available)
let frame = 0, generation = 0, disposed = false, request = null

function cancelFade() { cancelAnimationFrame(frame); frame = 0 }
function fadeTo(value, duration = 1500, done = () => {}) {
  cancelFade()
  const player = audio.value
  if (!player) return
  const start = player.volume, began = performance.now(), end = Math.max(0, Math.min(.4, value))
  function tick(now) {
    const progress = Math.min(1, (now - began) / duration)
    player.volume = start + (end - start) * progress
    currentVolume.value = Math.round(player.volume * 100)
    if (progress < 1) frame = requestAnimationFrame(tick)
    else { frame = 0; done() }
  }
  frame = requestAnimationFrame(tick)
}
function stopImmediately() {
  generation += 1
  cancelFade()
  if (audio.value) { audio.value.pause(); audio.value.volume = 0 }
  playing.value = false; starting.value = false; currentVolume.value = 0
}
function selectTrack() {
  stopImmediately()
  error.value = ''
  // Clear the previous source. Selection alone never loads or starts audio.
  audio.value?.removeAttribute('src')
  audio.value?.load()
}
async function loadLibrary() {
  stopImmediately()
  request?.abort(); request = new AbortController()
  loading.value = true; error.value = ''
  try {
    const response = await fetch('/api/music', { signal: request.signal, cache: 'no-store' })
    if (!response.ok) throw new Error('音乐库读取失败，请确认后端已接入音乐接口。')
    const body = await response.json()
    if (!Array.isArray(body.tracks)) throw new Error('音乐库响应格式无效。')
    if (disposed) return
    tracks.value = body.tracks; libraryStatus.value = body.status
    if (!tracks.value.some(track => track.id === selectedId.value)) selectedId.value = ''
    selectTrack()
  } catch (err) {
    if (err.name !== 'AbortError' && !disposed) { error.value = err.message; tracks.value = [] }
  } finally { if (!disposed) loading.value = false }
}
async function play() {
  if (!playable.value || !audio.value || starting.value || playing.value) return
  window.dispatchEvent(new CustomEvent('terry-audio-owner', { detail: 'library' }))
  const token = ++generation, player = audio.value
  starting.value = true; error.value = ''; player.volume = 0
  // Keep this call in the user click handler, rather than a watcher or EEG callback.
  const url = `/api/music/${encodeURIComponent(selectedId.value)}/audio`
  if (player.getAttribute('src') !== url) player.src = url
  try {
    await player.play()
    if (disposed || token !== generation) return
    playing.value = true
    fadeTo(Number(targetVolume.value) / 100)
  } catch (_) {
    if (token === generation && !disposed) {
      stopImmediately()
      error.value = '播放失败：请检查本地文件和浏览器音频支持，然后手动重试。'
    }
  } finally { if (token === generation) starting.value = false }
}
function pause() {
  if (starting.value) { stopImmediately(); return }
  fadeTo(0, 800, stopImmediately)
}
function changeVolume() {
  if (playing.value) fadeTo(Number(targetVolume.value) / 100)
}
function mediaError() {
  if (!audio.value?.getAttribute('src')) return
  stopImmediately(); error.value = '音频无法读取或解码，请人工检查本地素材。'
}
function onVisibility() { if (document.hidden) stopImmediately() }
function onAudioOwner(event) { if (event.detail !== 'library') stopImmediately() }
onMounted(() => { audio.value.volume = 0; loadLibrary(); document.addEventListener('visibilitychange', onVisibility); window.addEventListener('terry-audio-owner', onAudioOwner) })
onBeforeUnmount(() => {
  disposed = true; request?.abort(); stopImmediately()
  audio.value?.removeAttribute('src'); audio.value?.load()
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('terry-audio-owner', onAudioOwner)
})
</script>

<template>
  <section id="music-library" class="music-panel" aria-label="本地音乐手动控制">
    <header><div><h2>离线音乐素材库</h2><p>仅手动控制 · 未连接脑电自动调节</p></div><button type="button" :disabled="loading" @click="loadLibrary">{{ loading ? '读取中…' : '刷新素材库' }}</button></header>
    <p class="notice">需用户点击才会播放；不上传音频、不联网生成。音乐仅供舒适度探索，不保证助眠或治疗效果。如感不适请立即停止。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!loading && !tracks.length" role="status">{{ libraryStatus === 'invalid' ? '素材清单格式无效，请管理员检查 manifest.json。' : '暂无本地音乐素材。请放入音频并在 manifest.json 中登记。' }}</p>
    <label class="track-select">选择素材（选择不会播放）
      <select v-model="selectedId" :disabled="loading || !tracks.length" @change="selectTrack">
        <option value="">请选择曲目</option>
        <option v-for="track in tracks" :key="track.id" :value="track.id">{{ track.title }} — {{ track.available ? '可播放' : '文件不可用' }}</option>
      </select>
    </label>
    <div v-if="selected" class="review">
      <p><strong>{{ selected.title }}</strong> · {{ selected.purpose || '未填写用途' }}</p>
      <p v-if="!selected.available">此素材当前被后端标记为不可用。请刷新素材库；若刚更新播放规则，请确认后端已重启。仍不可用时再检查本地文件、路径和格式。</p>
    </div>
    <div class="music-actions">
      <button type="button" :disabled="!playable || playing || starting || loading" @click="play">{{ starting ? '正在加载…' : '手动播放' }}</button>
      <button type="button" :disabled="!playing && !starting" @click="pause">渐弱暂停</button>
      <button type="button" @click="stopImmediately">立即停止</button>
      <span role="status">{{ starting ? '等待音频' : playing ? '播放中' : '已停止 / 暂停' }}</span>
    </div>
    <label class="volume-control">目标音量 {{ targetVolume }}%（当前 {{ currentVolume }}%）
      <input v-model.number="targetVolume" type="range" min="0" max="40" step="1" aria-label="音乐目标音量" @input="changeVolume" />
    </label>
    <p class="notice">默认 15%，最高 40%，约 1.5 秒渐变；暂停约 0.8 秒渐弱。切曲、离开页面与立即停止会直接静音。设备系统音量仍影响实际声压，请先调低设备音量；浏览器音量比例不代表听力安全阈值。播放结束后不会自动切曲或循环。</p>
    <audio ref="audio" preload="none" @ended="stopImmediately" @error="mediaError" />
  </section>
</template>

<style scoped>
.music-panel { padding: 24px; margin-top: 24px; border: 1px solid #e4e9e2; border-radius: 20px; background: #fafbf9; color: #1c2e1e; }
header, .music-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; justify-content: space-between; }
h2 { margin: 0; font-size: 22px; font-weight: 500; } p { line-height: 1.7; overflow-wrap: anywhere; }
.notice { color: #647260; font-size: 13px; } [role='alert'] { color: #a13434; }
.track-select, .volume-control { display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }
select, button { color: #1c2e1e; background: white; border: 1px solid #dfe5dc; padding: 11px 16px; border-radius: 10px; }
select { width: 100%; } button { cursor: pointer; } button:disabled { opacity: .45; cursor: not-allowed; }
.review { margin: 20px 0; padding: 16px; background: #f0f3ed; border-radius: 12px; font-size: 14px; }
.music-actions { justify-content: flex-start; margin-top: 20px; }.music-actions button:first-child { background: #1c2e1e; color: white; } input[type='range'] { width: min(100%, 420px); accent-color: #4d6d47; }
@media(max-width:600px) { .music-panel { padding:16px; } }
</style>
