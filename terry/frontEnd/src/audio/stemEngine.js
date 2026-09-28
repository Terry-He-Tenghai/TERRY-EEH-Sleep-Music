import { effectiveStemMix, sampleAudio } from './stemMix.js'
import { isScriptedDemo, validateDemoOrigin } from './demoOrigin.js'
// Original, aligned WAV stems only. No MIDI overlay, tempo conversion or inference here.
const API = (import.meta.env?.VITE_API_BASE || '').replace(/\/$/, '')
const ROLES = ['piano', 'strings', 'bass', 'pad']
const FRESH_MS = 15000
const TRACKS = Array.from({ length: 20 }, (_, index) => `Track${String(index + 1).padStart(5, '0')}`)

export function validateStemFrame(raw, trackId, now = Date.now()) {
  if (!raw || raw.type !== 'adaptive_music' || !['LIVE', 'DEMO'].includes(raw.source)) throw new Error('分轨事件来源无效')
  if (!['string', 'number'].includes(typeof raw.session_id) || !String(raw.session_id) || !Number.isSafeInteger(raw.sequence) || raw.sequence < 0) throw new Error('分轨会话序号无效')
  const stamp = raw.emitted_at_s
  if (!Number.isFinite(stamp) || now - stamp * 1000 > FRESH_MS || stamp * 1000 - now > 5000) throw new Error('分轨计划过期或时钟不同步')
  if (!['ready', 'waiting', 'frozen', 'blocked', 'error', 'stopped'].includes(raw.status)) throw new Error('分轨状态无效')
  if (raw.status !== 'ready') return null
  validateDemoOrigin(raw)
  const plan = raw.stem_mix
  if (!plan || plan.track_id !== trackId || !TRACKS.includes(trackId) || !['adaptive', 'conservative', 'demo_scripted'].includes(plan.mode)) throw new Error('分轨音乐计划与所选素材不一致')
  if ((plan.mode !== 'conservative' && (!Number.isFinite(plan.control_level) || plan.control_level < 0 || plan.control_level > 1)) || !Number.isFinite(plan.brightness) || plan.brightness < 0 || plan.brightness > 1 || !Number.isFinite(plan.transition_seconds) || plan.transition_seconds < 1 || plan.transition_seconds > 20) throw new Error('分轨控制参数无效')
  if (!plan.gains || ROLES.some(role => !Number.isFinite(plan.gains[role]) || plan.gains[role] < 0 || plan.gains[role] > 1)) throw new Error('声部增益无效')
  if (plan.mode === 'conservative' && (plan.control_level !== null || ROLES.some(role => plan.gains[role] > .12))) throw new Error('保守分轨计划超出固定低增益范围')
  if (plan.mode === 'demo_scripted') {
    if (!isScriptedDemo(raw)) throw new Error('分轨动态演示来源无效')
    const p = raw.probabilities
    if (!p || ['W','N1','N2'].some(k => !Number.isFinite(p[k]) || p[k] < 0 || p[k] > 1) || Math.abs(p.W+p.N1+p.N2-1) > .01) throw new Error('预设概率无效')
  } else if (plan.mode === 'adaptive') {
    const repair = raw.channel_repair
    const imputed = repair?.method === 'available_channel_mean' && repair.experimental === true && repair.usable === true && repair.valid_channels?.length >= 8 && repair.valid_fraction >= .5
    const spectral = raw.source === 'LIVE' && raw.inference_mode === 'spectral_heuristic' && raw.probability_origin === 'eeg_spectral_heuristic_unvalidated' && repair?.used_channels?.length >= 1 && Number.isFinite(repair.valid_fraction) && repair.valid_fraction > 0
    const qualityFloor = spectral ? 0 : imputed ? .5 : .75
    const p = raw.probabilities
    if (raw.playback_mode !== 'adaptive' || raw.state?.status !== 'ok' || (!spectral && raw.state?.baseline_ready !== true) || !p || ['W', 'N1', 'N2'].some(k => !Number.isFinite(p[k]) || p[k] < 0 || p[k] > 1) || Math.abs(p.W + p.N1 + p.N2 - 1) > .01 || !Number.isFinite(raw.signal_quality) || raw.signal_quality < qualityFloor || raw.signal_quality > 1) throw new Error('尚无有效脑电分类，禁止自适应分轨')
  } else {
    if (raw.playback_mode !== 'conservative' || !raw.channel_repair?.valid_channels?.length) throw new Error('保守分轨仍需有效电极')
  }
  return { ...plan, probability_origin: raw.probability_origin ?? 'model', demo_stage: raw.demo_stage ?? null, gains: { ...plan.gains }, sequence: raw.sequence, source: raw.source }
}

export class StemEngine {
  constructor({ onUpdate = () => {}, contextFactory, fetcher = (...args) => fetch(...args) } = {}) {
    this.onUpdate = onUpdate; this.contextFactory = contextFactory || (() => new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 }))
    this.strength = .85; this.bypass = false; this.mixRevision = 0
    this.fetcher = fetcher; this.token = 0; this.entries = new Set(); this.events = []; this.volume = .18
    this.ownership = event => { if (event.detail !== 'stems') this.stop('其他播放器接管') }
    this.visibility = () => { if (document.hidden) this.stop('页面隐藏，已停止') }
    window.addEventListener('terry-audio-owner', this.ownership)
    document.addEventListener('visibilitychange', this.visibility)
  }
  log(type, fields = {}) {
    this.events.push({ type, time: new Date().toISOString(), audio_time_s: this.ctx?.currentTime ?? null, ...fields })
    if (this.events.length > 1000) this.events.shift()
  }
  publish() {
    const now = this.ctx?.currentTime || 0
    this.onUpdate({ armed: !!this.armed, status: this.status || 'stopped', reason: this.reason || '',
      strength: this.strength, bypass: this.bypass, cutoff: this.filter?.frequency.value ?? 0,
      audio: this.armed && this.origin != null && this.analyser ? sampleAudio(this.analyser, this.waveData, this.frequencyData) : null,
      plan: this.plan || null, applied: this.applied || null, source: this.source, volume: this.volume,
      elapsed: this.origin == null ? 0 : Math.max(0, now - this.origin),
      stems: (this.stems || []).map(s => ({ id: s.id, role: s.role, label: s.label,
        target: this.applied?.gains[s.role] ?? this.plan?.gains[s.role] ?? 0, current: s.gain?.gain.value ?? 0 })), logCount: this.events.length })
  }
  arm(track) {
    this.stop('重新开始分轨会话')
    this.events = []
    if (!track || !TRACKS.includes(track.id) || !Array.isArray(track.stems) || track.stems.length !== 4) { this.reason = '分轨素材不可用，请刷新列表'; this.publish(); return Promise.resolve(false) }
    if (document.hidden) return Promise.resolve(false)
    const token = this.token
    try {
      this.ctx = this.contextFactory(); const ctx = this.ctx
      const resumed = ctx.resume() // Invoked in start-click gesture, before network.
      this.master = ctx.createGain(); this.master.gain.value = 0
      this.compressor = ctx.createDynamicsCompressor()
      this.compressor.threshold.value = -12; this.compressor.knee.value = 12; this.compressor.ratio.value = 6
      this.compressor.attack.value = .003; this.compressor.release.value = .3
      this.analyser = ctx.createAnalyser(); this.analyser.fftSize = 1024; this.analyser.smoothingTimeConstant = .65
      this.analyser.minDecibels = -85; this.analyser.maxDecibels = -15
      this.waveData = new Float32Array(this.analyser.fftSize); this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount)
      this.compressor.connect(this.master); this.master.connect(this.analyser); this.analyser.connect(ctx.destination)
      this.filter = ctx.createBiquadFilter(); this.filter.type = 'lowpass'; this.filter.Q.value = .5
      this.filter.frequency.value = 6000; this.filter.connect(this.compressor)
      this.trackId = track.id; this.track = track; this.stems = []; this.session = null; this.sequence = -1
      this.armedAt = Date.now(); this.armed = true; this.status = 'buffering'; this.reason = '准备原曲分轨，等待新的有效脑电计划'
      this.abort = new AbortController()
      window.dispatchEvent(new CustomEvent('terry-audio-owner', { detail: 'stems' }))
      this.timer = setInterval(() => { try { this.tick() } catch (e) { this.stop(e.message) } }, 50)
      ctx.onstatechange = () => { if (this.armed && ctx.state !== 'running') this.stop('音频上下文中断') }
      this.log('armed', { track: this.trackId }); this.publish()
      return Promise.resolve(resumed).then(async () => {
        if (!this.armed || token !== this.token) return false
        if (ctx.state !== 'running') throw new Error('浏览器未授权音频')
        await this.load(track, token, ctx)
        return this.armed && token === this.token
      }).catch(e => { if (token === this.token) this.stop(e.message); return false })
    } catch (e) { this.stop(e.message); return Promise.resolve(false) }
  }
  async load(track, token, ctx) {
    let total = 0
    const valid = () => this.armed && token === this.token
    const loaded = []
    for (const stem of track.stems) {
      if (!/^S\d{2}$/.test(stem.id) || !ROLES.includes(stem.role)) throw new Error('声部清单无效')
      const response = await this.fetcher(`${API}/api/stem-music/${track.id}/stems/${stem.id}/audio`, { signal: this.abort.signal, cache: 'no-store', redirect: 'error' })
      if (!valid()) return
      if (!response.ok || !response.body) throw new Error(`声部 ${stem.id} 读取失败`)
      const reader = response.body.getReader(), chunks = []; let size = 0
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.byteLength; total += value.byteLength
        if (size > 25000000 || total > 80000000 || !valid()) { await reader.cancel(); if (!valid()) return; throw new Error('分轨下载超过大小限制') }
        chunks.push(value)
      }
      const bytes = new Uint8Array(size); let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
      const buffer = await ctx.decodeAudioData(bytes.buffer)
      if (!valid()) return
      if (buffer.numberOfChannels !== 1 || buffer.duration < 8 || buffer.duration > 600 || (loaded.length && Math.abs(buffer.duration - loaded[0].buffer.duration) > .02)) throw new Error('分轨时长或声道不一致，无法同步')
      const gain = ctx.createGain(); gain.gain.value = 0; gain.connect(this.filter)
      loaded.push({ ...stem, buffer, gain })
    }
    if (!valid()) return
    this.stems = loaded; this.duration = loaded[0].buffer.duration; this.status = 'waiting'; this.reason = '四个声部已缓冲，等待有效计划'
    this.log('loaded', { track: track.id, duration_s: this.duration, stems: loaded.map(s => s.id) }); this.publish()
  }
  consume(event) {
    if (!this.armed || !event) return
    try {
      const plan = validateStemFrame(event, this.trackId)
      if (event.emitted_at_s * 1000 < this.armedAt - 1000) throw new Error('收到启动前旧计划')
      const session = String(event.session_id)
      if (this.session && session !== this.session) throw new Error('脑电会话已改变，请重新开始')
      if (event.sequence <= this.sequence) return
      this.session = session; this.sequence = event.sequence; this.source = event.source
      if (!plan) {
        this.plan = null
        if (['stopped', 'blocked', 'error'].includes(event.status)) { this.stop(event.reason || event.status); return }
        this.clearSources(); this.applied = null; this.status = 'waiting'; this.reason = event.reason || '等待有效电极'
        this.publish(); return
      }
      if (this.fadeDeadline != null) return
      this.plan = plan; this.lastReady = performance.now(); this.serverStamp = event.emitted_at_s * 1000
      this.log('plan', { sequence: plan.sequence, mode: plan.mode, control_level: plan.control_level, gains: plan.gains })
      this.publish()
    } catch (e) { this.stop(e.message) }
  }
  ramp(param, value, at, duration) {
    if (param.cancelAndHoldAtTime) param.cancelAndHoldAtTime(at)
    else { param.cancelScheduledValues(at); param.setValueAtTime(param.value, at) }
    param.linearRampToValueAtTime(value, at + duration)
  }
  scheduleCycle(at) {
    for (const stem of this.stems) {
      const source = this.ctx.createBufferSource(), fade = this.ctx.createGain()
      source.buffer = stem.buffer; source.connect(fade); fade.connect(stem.gain)
      fade.gain.setValueAtTime(0, at); fade.gain.linearRampToValueAtTime(1, at + 1)
      fade.gain.setValueAtTime(1, at + this.duration - 1); fade.gain.linearRampToValueAtTime(0, at + this.duration)
      const entry = { source, fade }; this.entries.add(entry)
      source.onended = () => { source.disconnect(); fade.disconnect(); this.entries.delete(entry) }
      source.start(at); source.stop(at + this.duration + .01)
    }
    this.nextCycle = at + this.duration - 1
    this.log('cycle-scheduled', { at, track: this.trackId, duration_s: this.duration })
  }
  tick() {
    if (!this.armed) return
    if (document.hidden) { this.stop('页面隐藏'); return }
    const now = this.ctx.currentTime
    if (this.fadeDeadline != null) {
      if (performance.now() >= this.fadeDeadline) this.stop('超过15秒无有效计划，已渐出停止')
      return
    }
    if (this.plan && (performance.now() - this.lastReady > FRESH_MS || Date.now() - this.serverStamp > FRESH_MS)) {
      this.ramp(this.master.gain, 0, now, 2); this.fadeDeadline = performance.now() + 2100
      this.status = 'fading'; this.reason = '计划过期，2秒渐出'; this.publish(); return
    }
    if (!this.plan || this.stems.length !== 4 || this.ctx.state !== 'running') return
    if (this.origin == null) {
      this.origin = now + .1; this.scheduleCycle(this.origin)
      this.ramp(this.master.gain, this.volume, now, 3)
    }
    if (this.nextCycle < now - .25) { this.stop('分轨调度延迟，请保持页面前台'); return }
    if (this.nextCycle <= now + .15) this.scheduleCycle(this.nextCycle)
    if (this.applied?.sequence !== this.plan.sequence || this.appliedRevision !== this.mixRevision) {
      const mix = effectiveStemMix(this.plan, this.strength, this.bypass)
      for (const stem of this.stems) this.ramp(stem.gain.gain, mix.gains[stem.role], now, this.plan.transition_seconds)
      this.ramp(this.filter.frequency, mix.cutoff, now, this.plan.transition_seconds)
      this.applied = mix; this.appliedRevision = this.mixRevision; this.status = 'playing'
      this.reason = this.plan.mode === 'demo_scripted' ? '动态演示：预设状态驱动音乐，不是机器学习预测' : this.plan.mode === 'conservative' ? '基线/分类准备中：固定保守混音，非睡眠状态驱动' : '有效脑电驱动原曲声部比例与亮度'
      this.log('applied', { demo_scripted: this.plan.mode === 'demo_scripted', probability_origin: this.plan.probability_origin, demo_stage: this.plan.demo_stage, sequence: this.plan.sequence, mode: this.plan.mode, gains: mix.gains, brightness: this.plan.brightness, cutoff: mix.cutoff, strength: this.strength, comparison: !!mix.comparison })
    }
    if (!this.lastUi || now - this.lastUi > .2) { this.lastUi = now; this.publish() }
  }
  setStrength(value) {
    if (!Number.isFinite(value)) return
    this.strength = Math.max(0, Math.min(1, value)); this.mixRevision++
    this.log('strength', { value: this.strength }); this.tick(); this.publish()
  }
  setComparison(value) {
    this.bypass = !!value; this.mixRevision++
    this.log('comparison', { enabled: this.bypass, scope: 'four-selected-stems-not-original-full-mix' }); this.tick(); this.publish()
  }
  setVolume(value) {
    this.volume = Math.max(0, Math.min(.3, Number(value) || 0))
    if (this.origin != null && this.fadeDeadline == null) this.ramp(this.master.gain, this.volume, this.ctx.currentTime, 2)
    this.publish()
  }
  clearSources() {
    if (this.ctx && this.master) { this.master.gain.cancelScheduledValues(this.ctx.currentTime); this.master.gain.setValueAtTime(0, this.ctx.currentTime) }
    for (const { source, fade } of this.entries) { source.onended = null; try { source.stop() } catch { /* already ended */ } source.disconnect(); fade.disconnect() }
    this.entries.clear(); this.origin = null; this.nextCycle = null; this.lastUi = null
  }
  stop(reason = '用户停止') {
    this.token++; this.armed = false; clearInterval(this.timer); this.abort?.abort(); this.clearSources()
    if (this.ctx) { this.ctx.onstatechange = null; this.ctx.close().catch(() => {}) }
    this.ctx = null; this.analyser = null; this.waveData = null; this.frequencyData = null; this.stems = []; this.plan = null; this.applied = null; this.fadeDeadline = null
    this.status = 'stopped'; this.reason = reason; this.log('stop', { reason }); this.publish()
  }
  exportLog() { return { mode: 'original-stem-mix', track: this.trackId, events: this.events, limitations: 'Browser scheduling only, no EEG/audio hardware synchronization or clinical efficacy. MIDI is not edited. Loop boundary uses a 1-second crossfade, not beat matching.' } }
  dispose() { this.stop('组件卸载'); window.removeEventListener('terry-audio-owner', this.ownership); document.removeEventListener('visibilitychange', this.visibility) }
}
