import { isScriptedDemo, validateDemoOrigin } from './demoOrigin.js'
import { analyzeUpload } from './uploadLoudness.js'

// Prepared backend MIDI plans only. 60 BPM, 16 beats per phrase; no remote generation.
const PHRASE = 16, STALE_MS = 15_000, MAX_BYTES = 80_000_000
const API_BASE = (import.meta.env?.VITE_API_BASE || '').replace(/\/$/, '')
const clamp = (value, low, high) => Math.max(low, Math.min(high, value))
const text = value => typeof value === 'string' ? value.slice(0, 500) : ''
const voices = ['pad', 'melody', 'bass', 'texture']

// Count the peak simultaneous voices during this note, not every short note
// encountered across a long sustain (which wrongly attenuates long harmony).
export function peakPolyphony(notes, note) {
  const start = note.start_beat, end = start + note.duration_beats
  const edges = []
  for (const other of notes) {
    if (other.voice === 'pad' || other.velocity === 0) continue
    const left = Math.max(start, other.start_beat)
    const right = Math.min(end, other.start_beat + other.duration_beats)
    if (left < right) edges.push([left, 1], [right, -1])
  }
  edges.sort((a, b) => a[0] - b[0] || a[1] - b[1])
  let active = 0, peak = 1
  for (const [, delta] of edges) { active += delta; peak = Math.max(peak, active) }
  return peak
}

// Backend adapter aliases are accepted, but freshness requires a server wall-clock stamp.
export function normalizeAdaptiveEvent(event) {
  if (!event || typeof event !== 'object') return event
  return { ...event,
    session_id: Number.isSafeInteger(event.session_id) ? String(event.session_id) : event.session_id,
    timestamp_s: event.emitted_at_s ?? event.server_timestamp_s ?? event.timestamp_s,
    music_state: event.music_state ?? event.current_music_state,
    motif_variation: event.motif_variation ?? event.variation,
    track: event.track ?? event.selected_track,
  }
}

export function validateAdaptiveEvent(event) {
  if (!event || event.type !== 'adaptive_music') throw new Error('无效的自适应事件类型')
  if (!['LIVE', 'DEMO'].includes(event.source)) throw new Error('缺少 LIVE / DEMO 来源')
  if (typeof event.session_id !== 'string' || !event.session_id || event.session_id.length > 200 || !Number.isSafeInteger(event.sequence) || event.sequence < 0) throw new Error('缺少有效会话标识或序号')
  if (!['ready', 'waiting', 'frozen', 'blocked', 'error', 'stopped'].includes(event.status)) throw new Error('无效事件状态')
  if (event.status !== 'ready') return
  validateDemoOrigin(event)
  if (!Number.isFinite(event.timestamp_s) || Date.now() - event.timestamp_s * 1000 > STALE_MS || event.timestamp_s * 1000 - Date.now() > 5000) throw new Error('事件时间戳过期或时钟不同步（需要服务端 Unix 秒时间）')
  if ((event.bpm != null && event.bpm !== 60) || (event.phrase_beats != null && event.phrase_beats !== 16)) throw new Error('当前播放器仅支持 60 BPM / 16 拍计划')
  if (!['M1', 'M2', 'M3'].includes(event.music_state) || !['M1', 'M2', 'M3'].includes(event.target_music_state)) throw new Error('无效音乐状态')
  const probabilities = event.probabilities || event.state_probabilities
  const conservative = event.playback_mode === 'conservative'
  if (!conservative && (!probabilities || !['W', 'N1', 'N2'].every(key => Number.isFinite(probabilities[key]) && probabilities[key] >= 0 && probabilities[key] <= 1) || Math.abs(['W', 'N1', 'N2'].reduce((sum, key) => sum + probabilities[key], 0) - 1) > .01)) throw new Error('睡眠状态概率无效')
  const repair = event.channel_repair
  const meanImputed = repair?.method === 'available_channel_mean' && repair.experimental === true && repair.usable === true && Array.isArray(repair.valid_channels) && repair.valid_channels.length >= 8 && Number.isFinite(repair.valid_fraction) && repair.valid_fraction >= .5
  if (conservative) {
    if (repair?.method !== 'available_channel_mean' || !Array.isArray(repair.valid_channels) || repair.valid_channels.length < 1 || !Number.isFinite(repair.valid_fraction) || repair.valid_fraction <= 0) throw new Error('保守播放仍需有效电极和新数据')
    const caps = { master: .06, pad: .3, melody: .08, bass: 0, texture: 0 }
    if (!event.gains || Object.entries(caps).some(([key, cap]) => !Number.isFinite(event.gains[key]) || event.gains[key] < 0 || event.gains[key] > cap) || !Array.isArray(event.notes) || event.notes.length > 4 || event.notes.some(note => note.voice !== 'melody' || note.velocity > 35)) throw new Error('保守播放计划超过低增益或稀疏音符限制')
  }
  const minimumQuality = conservative ? 0 : meanImputed ? .5 : .75
  if (!Number.isFinite(event.signal_quality) || event.signal_quality < minimumQuality || event.signal_quality > 1) throw new Error('有效电极或信号质量不足，已禁止声音')
  if (!event.track || typeof event.track.id !== 'string' || !event.track.id || event.track.id.length > 200) throw new Error('没有可用本地底轨；禁止单独启动振荡器')
  if (!Array.isArray(event.notes) || event.notes.length > 512) throw new Error('MIDI 计划缺失或过大')
  for (const note of event.notes) {
    if (!voices.includes(note.voice) || !Number.isFinite(note.start_beat) || note.start_beat < 0 || note.start_beat >= PHRASE || !Number.isFinite(note.duration_beats) || note.duration_beats <= 0 || note.duration_beats > PHRASE || !Number.isInteger(note.midi_note) || note.midi_note < 0 || note.midi_note > 127 || !Number.isInteger(note.velocity) || note.velocity < 0 || note.velocity > 127) throw new Error('MIDI 音符参数无效')
  }
  if (event.waveform != null) {
    if (typeof event.waveform === 'string') {
      if (!['sine', 'triangle', 'square', 'sawtooth'].includes(event.waveform)) throw new Error('不支持的振荡器音色')
    } else {
      if (typeof event.waveform !== 'object' || Array.isArray(event.waveform)) throw new Error('无效波形参数')
      for (const name of ['master_gain', 'brightness', 'reverb_send', 'stereo_width']) {
        const value = event.waveform[name]
        if (value != null && (!Number.isFinite(value) || value < 0 || value > 1)) throw new Error('无效波形参数')
      }
    }
  }
  if (event.waveform_parameters != null) {
    if (typeof event.waveform_parameters !== 'object' || Array.isArray(event.waveform_parameters)) throw new Error('无效音色参数')
    for (const name of ['master_gain', 'brightness', 'reverb_send', 'stereo_width']) {
      const value = event.waveform_parameters[name]
      if (value != null && (!Number.isFinite(value) || value < 0 || value > 1)) throw new Error('无效音色参数')
    }
  }
  if (event.gains != null && (typeof event.gains !== 'object' || Array.isArray(event.gains))) throw new Error('无效增益配置')
  for (const value of Object.values(event.gains || {})) if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error('增益必须在 0–1 之间')
}

export class AdaptiveEngine {
  constructor({ onUpdate = () => {} } = {}) {
    this.uploadLevel = 1
    this.midiLevel = 1
    this.onUpdate = onUpdate
    this.generation = 0; this.loadToken = 0; this.events = []; this.sources = new Set()
    this.armed = false; this.status = 'unarmed'; this.sequence = -1; this.lastFrame = 0
    this.ownership = event => { if (event.detail !== 'adaptive') this.stop(`audio-owner:${text(event.detail)}`) }
    this.visibility = () => { if (document.hidden) this.stop('页面隐藏，自动播放已停止') }
    window.addEventListener('terry-audio-owner', this.ownership)
    document.addEventListener('visibilitychange', this.visibility)
  }
  setUploadLevel(value) {
    this.uploadLevel = clamp(Number.isFinite(value) ? value : 1, 0, 6)
    if (this.trackSource?.uploadGain && this.ctx) this.ramp(this.trackSource.uploadGain.gain, this.uploadLevel, this.ctx.currentTime, 3)
    this.log('upload-level', { multiplier: this.uploadLevel }); this.publish()
  }
  setMidiLevel(value) {
    this.midiLevel = clamp(Number.isFinite(value) ? value : 1, 0, 2)
    if (this.midiTrim && this.ctx) this.ramp(this.midiTrim.gain, this.midiLevel, this.ctx.currentTime, 2)
    this.log('midi-level', { multiplier: this.midiLevel }); this.publish()
  }
  log(type, data = {}) {
    this.events.push({ at: new Date().toISOString(), audio_time_s: this.ctx?.currentTime ?? null, type, ...data })
    if (this.events.length > 2000) this.events.splice(0, this.events.length - 2000)
  }
  publish(extra = {}) {
    const now = this.ctx?.currentTime || 0
    this.onUpdate({ armed: this.armed, status: this.status, reason: this.reason || '', source: this.source || null,
      uploadLevel: this.uploadLevel, midiLevel: this.midiLevel, loudness: this.trackSource?.loudness ?? null,
      activeTrack: this.activeTrack || null, fadingTrack: this.fadingTrack || null, activeState: this.activeState || null,
      activeSequence: this.activeSequence ?? null, activeNotes: this.activeNotes || [], planned: this.pending || null,
      beat: this.origin == null ? 0 : Math.max(0, now - this.origin) % PHRASE,
      phrase: this.origin == null ? 0 : Math.max(0, Math.floor((now - this.origin) / PHRASE)) + 1,
      nextBoundarySeconds: this.origin == null ? null : Math.max(0, this.origin + this.nextPhrase * PHRASE - now),
      logCount: this.events.length, ...extra })
  }
  // Must be invoked directly in the acquisition click handler, before any await.
  arm() {
    this.stop('重新启动采集')
    if (document.hidden) { this.reason = '页面隐藏，无法启用声音'; this.publish(); return Promise.resolve(false) }
    const token = this.generation
    try {
      const Context = window.AudioContext || window.webkitAudioContext
      if (!Context) throw new Error('浏览器不支持 Web Audio')
      const context = new Context()
      this.ctx = context
      const resumed = context.resume() // Intentionally synchronous user-gesture invocation.
      this.master = context.createGain(); this.master.gain.value = 0
      const compressor = context.createDynamicsCompressor()
      compressor.threshold.value = -12; compressor.knee.value = 12; compressor.ratio.value = 4
      compressor.attack.value = .003; compressor.release.value = .25
      this.compressor = compressor
      compressor.connect(this.master); this.master.connect(context.destination)
      this.filter = context.createBiquadFilter(); this.filter.type = 'lowpass'; this.filter.frequency.value = 4000
      this.filter.connect(compressor)
      this.delay = context.createDelay(1); this.delay.delayTime.value = .18
      this.wet = context.createGain(); this.wet.gain.value = 0
      this.filter.connect(this.delay); this.delay.connect(this.wet); this.wet.connect(compressor)
      this.midiTrim = context.createGain(); this.midiTrim.gain.value = this.midiLevel
      this.midiTrim.connect(this.filter)
      this.buses = {}
      for (const voice of voices) {
        const gain = context.createGain(), pan = context.createStereoPanner()
        gain.gain.value = 0
        pan.pan.value = voice === 'melody' ? -.25 : voice === 'texture' ? .25 : 0
        pan.connect(gain); gain.connect(voice === 'pad' ? this.filter : this.midiTrim); this.buses[voice] = { gain, pan }
      }
      this.armed = true; this.status = 'waiting'; this.reason = '声音已授权，等待采集后的新 ready 事件；尚未播放'
      this.session = null; this.sequence = -1; this.armedAt = Date.now(); this.lastReadyAt = 0
      window.dispatchEvent(new CustomEvent('terry-audio-owner', { detail: 'adaptive' }))
      this.timer = window.setInterval(() => {
        try { this.tick() } catch (error) { this.stop(error.message, 'error') }
      }, 40)
      context.onstatechange = () => { if (this.armed && context.state !== 'running') this.stop('音频上下文中断', 'blocked') }
      this.log('armed'); this.publish()
      return Promise.resolve(resumed).then(() => {
        if (token !== this.generation) return false
        if (context.state !== 'running') { this.stop('浏览器未授权声音，请重新启动采集', 'blocked'); return false }
        return true
      }).catch(error => { if (token === this.generation) this.stop(error.message, 'blocked'); return false })
    } catch (error) { this.stop(error.message, 'error'); return Promise.resolve(false) }
  }
  consume(event) {
    if (!this.armed || !event) return
    try {
      event = normalizeAdaptiveEvent(event)
      validateAdaptiveEvent(event)
      if (event.status === 'ready' && event.timestamp_s * 1000 < this.armedAt - 1000) throw new Error('忽略启动前的旧事件，请重新启动采集')
      if (this.session && event.session_id !== this.session) throw new Error('采集会话已改变，请重新启动采集')
      if (event.sequence <= this.sequence) return // Duplicates never refresh the freshness deadline.
      this.session = event.session_id; this.sequence = event.sequence; this.source = event.source
      const probabilities = event.probabilities || event.state_probabilities
      this.log('backend-event', { session_id: this.session, sequence: this.sequence, status: event.status, source: event.source, reason: text(event.reason), timestamp_s: event.timestamp_s,
        probability_origin: event.probability_origin ?? 'model', demo_scripted: event.demo_scripted === true,
        probabilities: probabilities ? { W: probabilities.W, N1: probabilities.N1, N2: probabilities.N2 } : null,
        signal_quality: event.signal_quality, music_state: event.music_state, target_music_state: event.target_music_state })
      if (event.status !== 'ready') {
        if (['stopped', 'error'].includes(event.status)) { this.stop(text(event.reason) || event.status, event.status); return }
        const electrodeHold = ['no_valid_electrodes', 'invalid_or_low_quality_eeg', 'insufficient_valid_channels_rechecking'].includes(event.reason)
        const fresh = Number.isFinite(event.timestamp_s) && Math.abs(Date.now() - event.timestamp_s * 1000) <= STALE_MS
        if (electrodeHold && fresh && this.currentPlan && this.activeTrack) {
          // A bounded audio-only bridge, never a new EEG inference result.
          this.qualityHoldAt ??= performance.now()
          this.pending = { ...this.currentPlan, notes: [], gains: { master: .06, pad: .3, melody: 0, bass: 0, texture: 0 } }
          for (const voice of ['melody', 'bass', 'texture']) this.ramp(this.buses[voice].gain.gain, 0, this.ctx.currentTime, 8)
          this.ramp(this.master.gain, Math.min(.06, this.master.gain.value), this.ctx.currentTime, 8)
          this.status = 'holding'; this.reason = '电极暂时失效：仅保留背景，最多30秒；恢复前不推断新睡眠状态'
          this.publish(); return
        }
        this.silence(); this.lastReadyAt = 0; this.status = event.status
        this.reason = text(event.reason) || '等待后端许可；已静音'; this.publish(); return
      }
      if (this.fadeStopTimer) return // Finish a timed fade; re-arm explicitly afterwards.
      this.qualityHoldAt = null
      this.lastReadyAt = performance.now(); this.readyTimestamp = event.timestamp_s * 1000
      this.pending = {
        probability_origin: event.probability_origin ?? 'model', demo_stage: event.demo_stage ?? null,
        session_id: this.session, sequence: event.sequence, source: event.source, timestamp_s: event.timestamp_s,
        music_state: text(event.music_state), target_music_state: text(event.target_music_state), reason: text(event.reason),
        waveform: (event.playback_mode === 'adaptive' || isScriptedDemo(event)) && ['probabilities_80_features_20_contrast_v2', 'continuous_harmony_v3', 'continuous_arrangement_v4'].includes(event.modulation?.mapping) ? 'triangle' : typeof event.waveform === 'string' ? event.waveform : 'sine',
        enhancedMidi: (event.playback_mode === 'adaptive' || isScriptedDemo(event)) && ['probabilities_80_features_20_contrast_v2', 'continuous_harmony_v3', 'continuous_arrangement_v4'].includes(event.modulation?.mapping),
        waveform_parameters: { ...(event.waveform_parameters || (event.waveform && typeof event.waveform === 'object' ? event.waveform : {})) },
        continuousHarmony: (event.playback_mode === 'adaptive' || isScriptedDemo(event)) && ['continuous_harmony_v3', 'continuous_arrangement_v4'].includes(event.modulation?.mapping),
        motif_variation: text(event.motif_variation), gains: { ...event.gains },
        notes: event.notes.map(n => ({ start_beat: n.start_beat, duration_beats: n.duration_beats, midi_note: n.midi_note, velocity: n.velocity, voice: n.voice, phrase: n.phrase })),
        track: { id: event.track.id, title: text(event.track.title) || event.track.id },
      }
      this.reason = text(event.reason)
      if (this.bufferId !== event.track.id && this.loadingId !== event.track.id) this.loadTrack(event.track.id)
      else if (this.bufferId === event.track.id && this.loadingId) {
        this.abort?.abort(); this.loadToken++; this.loadingId = null
        this.status = this.activeTrack ? 'playing' : 'ready'
      }
      this.publish()
    } catch (error) { this.stop(error.message, 'blocked') }
  }
  async loadTrack(id) {
    this.abort?.abort()
    const request = new AbortController(), token = ++this.loadToken, generation = this.generation, context = this.ctx, session = this.session
    this.abort = request; this.loadingId = id; this.status = 'buffering'; this.publish()
    const valid = () => this.armed && generation === this.generation && token === this.loadToken && this.session === session && this.pending?.track.id === id
    try {
      // Never trust audio_url as a network destination; opaque ID selects this fixed local endpoint.
      const response = await fetch(`${API_BASE}/api/music/${encodeURIComponent(id)}/audio`, { signal: request.signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
      if (!response.ok) throw new Error(`本地底轨下载失败 (${response.status})`)
      if (Number(response.headers.get('content-length')) > MAX_BYTES) throw new Error('底轨超过 80 MB 限制')
      if (!response.body) throw new Error('浏览器不支持受限音频下载')
      const reader = response.body.getReader(), chunks = []; let size = 0
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > MAX_BYTES || !valid()) { await reader.cancel(); if (!valid()) return; throw new Error('底轨超过 80 MB 限制') }
        chunks.push(value)
      }
      if (!valid()) return
      const bytes = new Uint8Array(size); let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
      chunks.length = 0
      const buffer = await context.decodeAudioData(bytes.buffer)
      if (!valid()) return
      if (!Number.isFinite(buffer.duration) || buffer.duration < 8 || buffer.duration > 900 || buffer.numberOfChannels > 2) throw new Error('底轨需为 8–900 秒的单声道或双声道音频')
      const loudness = id.startsWith('user_') ? await analyzeUpload(buffer, valid) : null
      if (!valid()) return
      this.buffer = buffer; this.bufferLoudness = loudness; this.bufferId = id; this.loadingId = null
      this.status = this.origin == null ? 'ready' : 'playing'; this.reason = '底轨已解码，等待 16 秒乐句边界'
      this.log('track-decoded', { id, duration_s: buffer.duration, loudness }); this.publish()
    } catch (error) { if (valid()) this.stop(error.message, 'blocked') }
  }
  ramp(parameter, value, at, seconds = .5) {
    if (parameter.cancelAndHoldAtTime) parameter.cancelAndHoldAtTime(at)
    else { parameter.cancelScheduledValues(at); parameter.setValueAtTime(parameter.value, at) }
    parameter.linearRampToValueAtTime(value, at + seconds)
  }
  retain(source, nodes = []) {
    const entry = { source, nodes }; this.sources.add(entry)
    source.onended = () => { source.disconnect(); nodes.forEach(node => node.disconnect()); this.sources.delete(entry) }
    return entry
  }
  scheduleTrack(plan, at) {
    if (this.trackSource?.id === plan.track.id) return
    const source = this.ctx.createBufferSource(), gain = this.ctx.createGain()
    source.buffer = this.buffer; source.loop = true
    const uploadGain = plan.track.id.startsWith('user_') ? this.ctx.createGain() : null
    const normalization = uploadGain ? this.ctx.createGain() : null
    source.connect(gain)
    if (uploadGain) {
      normalization.gain.value = this.bufferLoudness?.gain ?? 1
      uploadGain.gain.setValueAtTime(this.uploadLevel, at)
      // Uploaded music is a complete mix, not a quiet pad voice. Preserve its
      // spectrum and avoid multiplying it by the EEG-controlled pad gain.
      gain.connect(normalization); normalization.connect(uploadGain); uploadGain.connect(this.compressor)
    } else gain.connect(this.buses.pad.pan)
    gain.gain.setValueAtTime(0, at); gain.gain.linearRampToValueAtTime(1, at + 8)
    const previous = this.trackSource
    if (previous) {
      this.ramp(previous.gain.gain, 0, at, 8); previous.source.stop(at + 8.05)
    }
    this.retain(source, uploadGain ? [gain, uploadGain, normalization] : [gain]); source.start(at)
    this.trackSource = { source, gain, uploadGain, loudness: this.bufferLoudness, id: plan.track.id }
    this.transitionTrack = { at, until: at + 8, track: plan.track, previous: this.activeTrack }
    this.log('track-crossfade-scheduled', { track: plan.track, previous: this.activeTrack, audio_time_s: at, duration_s: 8, loop: true })
  }
  schedulePhrase(plan, at) {
    this.scheduleTrack(plan, at)
    const defaults = { pad: .65, melody: .25, bass: .18, texture: .08 }
    for (const voice of voices) this.ramp(this.buses[voice].gain.gain, clamp(plan.gains[voice] ?? defaults[voice], 0, 1), at, 2)
    const parameters = plan.waveform_parameters
    this.ramp(this.filter.frequency, 300 + 6000 * (parameters.brightness ?? .35), at, 2)
    this.ramp(this.wet.gain, (parameters.reverb_send ?? 0) * .3, at, 2)
    this.ramp(this.buses.melody.pan.pan, -.45 * (parameters.stereo_width ?? .65), at, 2)
    this.ramp(this.buses.texture.pan.pan, .45 * (parameters.stereo_width ?? .65), at, 2)
    this.ramp(this.master.gain, clamp(plan.gains.master ?? .15 * (parameters.master_gain ?? 1), 0, .22), at, 2)
    for (const note of plan.notes) {
      if (note.voice === 'pad' || note.velocity === 0) continue
      const sustained = plan.continuousHarmony && note.voice === 'texture'
      const start = at + note.start_beat, end = Math.min(at + PHRASE + (sustained ? .5 : 0), start + note.duration_beats)
      const oscillator = this.ctx.createOscillator(), envelope = this.ctx.createGain()
      const overtone = plan.enhancedMidi && note.voice === 'melody' ? this.ctx.createOscillator() : null
      const overtoneGain = overtone ? this.ctx.createGain() : null
      oscillator.type = note.voice === 'bass' ? 'sine' : plan.waveform
      oscillator.frequency.value = 440 * 2 ** ((note.midi_note - 69) / 12)
      if (overtone && overtoneGain) {
        overtone.type = 'sine'
        overtone.frequency.value = oscillator.frequency.value * 2
        overtoneGain.gain.value = 0.16
      }
      // Pad notes are symbolic only: never attenuate audible MIDI because of
      // notes that are not synthesized. Bound the enhanced melody's amplitude
      // by simultaneous voices, not the total number spread over 16 seconds.
      const simultaneous = peakPolyphony(plan.notes, note)
      const level = note.velocity / 127 * (plan.enhancedMidi ? .28 / Math.max(1, Math.sqrt(simultaneous)) : .12 / Math.max(1, Math.sqrt(plan.notes.length / 8)))
      envelope.gain.setValueAtTime(0, start)
      const attack = sustained ? .4 : .05, release = sustained ? .5 : .08
      envelope.gain.linearRampToValueAtTime(level, start + Math.min(attack, (end - start) / 3))
      envelope.gain.setValueAtTime(level, Math.max(start + (end - start) / 3, end - release))
      envelope.gain.linearRampToValueAtTime(0, end)
      oscillator.connect(envelope); envelope.connect(this.buses[note.voice].pan)
      if (overtone && overtoneGain) {
        overtone.connect(overtoneGain); overtoneGain.connect(envelope)
        this.retain(overtone, [overtoneGain])
      }
      this.retain(oscillator, [envelope])
      oscillator.start(start); oscillator.stop(end + .01)
      if (overtone) { overtone.start(start); overtone.stop(end + .01) }
    }
    this.transitionPlan = { at, plan }
    this.log('phrase-scheduled', { sequence: plan.sequence, phrase_index: this.nextPhrase, audio_time_s: at, plan })
  }
  fadeStop(reason) {
    if (this.fadeStopTimer) return
    this.ramp(this.master.gain, 0, this.ctx.currentTime, 8)
    this.status = 'fading'; this.reason = reason; this.publish()
    this.fadeStopTimer = setTimeout(() => { this.fadeStopTimer = null; this.stop(reason, 'blocked') }, 8100)
  }
  tick() {
    if (!this.armed) return
    if (document.hidden) { this.stop('页面隐藏'); return }
    if (this.fadeStopTimer) return
    if (this.qualityHoldAt != null && performance.now() - this.qualityHoldAt >= 30000) { this.fadeStop('电极持续失效，8秒渐出停止'); return }
    if (this.qualityHoldAt == null && this.lastReadyAt && (performance.now() - this.lastReadyAt > STALE_MS || Date.now() - this.readyTimestamp > STALE_MS)) { this.fadeStop('超过15秒无新计划，8秒渐出停止'); return }
    if (!this.pending || this.ctx.state !== 'running') return
    const now = this.ctx.currentTime
    if (this.origin == null) {
      if (this.bufferId !== this.pending.track.id) return
      this.origin = now + .2; this.nextPhrase = 0
    }
    const boundary = this.origin + this.nextPhrase * PHRASE
    if (now - boundary > .25) { this.stop('音频调度延迟，已安全停止', 'blocked'); return }
    if (boundary <= now + .12) {
      // A replacement that is still downloading never silences the old bed mid-phrase.
      const plan = this.bufferId === this.pending.track.id ? this.pending : this.currentPlan
      if (plan) this.schedulePhrase(plan, boundary)
      this.nextPhrase++
    }
    if (this.transitionTrack && now >= this.transitionTrack.at) {
      this.activeTrack = this.transitionTrack.track
      this.fadingTrack = now < this.transitionTrack.until ? this.transitionTrack.previous : null
      if (now >= this.transitionTrack.until) this.transitionTrack = null
    }
    if (this.transitionPlan && now >= this.transitionPlan.at) {
      this.currentPlan = this.transitionPlan.plan; this.activeState = this.currentPlan.music_state
      this.activeSequence = this.currentPlan.sequence; this.activeNotes = this.currentPlan.notes
      this.transitionPlan = null; this.status = this.qualityHoldAt != null ? 'holding' : this.loadingId ? 'buffering' : 'playing'
      this.log('phrase-started', { sequence: this.activeSequence, track: this.activeTrack })
    }
    if (now - this.lastFrame >= .1) { this.lastFrame = now; this.publish() }
  }
  silence() {
    this.loadToken++; this.abort?.abort(); this.abort = null; this.loadingId = null
    if (this.master && this.ctx) { this.master.gain.cancelScheduledValues(this.ctx.currentTime); this.master.gain.setValueAtTime(0, this.ctx.currentTime) }
    for (const { source, nodes } of this.sources) { source.onended = null; try { source.stop() } catch { /* Already ended. */ } source.disconnect(); nodes.forEach(node => node.disconnect()) }
    this.sources.clear(); this.buffer = null; this.bufferId = null; this.pending = null; this.currentPlan = null
    this.trackSource = null; this.activeTrack = null; this.fadingTrack = null; this.activeState = null; this.activeSequence = null; this.activeNotes = []
    this.transitionTrack = null; this.transitionPlan = null; this.origin = null; this.nextPhrase = 0; this.lastFrame = 0
  }
  stop(reason = '用户停止', status = 'stopped') {
    this.generation++; this.armed = false; clearInterval(this.timer); this.timer = null
    clearTimeout(this.fadeStopTimer); this.fadeStopTimer = null; this.qualityHoldAt = null
    this.silence(); this.status = status; this.reason = reason
    if (this.ctx) { this.ctx.onstatechange = null; this.ctx.close().catch(() => {}); this.ctx = null }
    this.compressor = null; this.midiTrim = null; this.bufferLoudness = null
    this.master = null; this.buses = null; this.filter = null; this.delay = null; this.wet = null; this.lastReadyAt = 0
    this.log('stop', { reason }); this.publish()
  }
  exportLog() {
    return { schema_version: 1, mode: 'adaptive', bpm: 60, phrase_beats: PHRASE, crossfade_seconds: 8, master_ceiling: .22,
      exported_at: new Date().toISOString(), retained_events_limit: 2000, events: this.events.slice(),
      limitations: 'Engineering oscillator preview; harmony and pitch compatibility with the local Suno bed are not validated. Pad MIDI is omitted. Bed loops from its beginning; no beat detection or synchronization to its original tempo. Logs report scheduling/context playback, not speaker or physiological evidence. No microphone, pitch detection, or remote generation.' }
  }
  dispose() {
    this.stop('组件卸载'); window.removeEventListener('terry-audio-owner', this.ownership)
    document.removeEventListener('visibilitychange', this.visibility)
  }
}
