// Manual research preview only. All musical events use the AudioContext clock.
export const PRESETS = {
  M1: { gains: { pad: .72, melody: .34, bass: .26, texture: .16 }, brightness: .5, reverb: .18, width: .72, master: .8 },
  M2: { gains: { pad: .68, melody: .16, bass: .18, texture: .11 }, brightness: .3, reverb: .28, width: .58, master: .68 },
  M3: { gains: { pad: .58, melody: 0, bass: 0, texture: .08 }, brightness: .14, reverb: .38, width: .42, master: .52 },
}
export const frequency = note => 440 * 2 ** ((note - 69) / 12)
export function validatePlans(plans) {
  for (const state of Object.keys(PRESETS)) {
    const plan = plans[state]
    if (!plan || !Array.isArray(plan.notes) || plan.notes.length > 1000) throw new Error('编排数据不完整')
    for (const n of plan.notes) {
      if (!['pad', 'melody', 'bass'].includes(n.voice) || !Number.isFinite(n.start_beat) || n.start_beat < 0 || n.start_beat >= 16 || !Number.isFinite(n.duration_beats) || n.duration_beats <= 0 || n.duration_beats > 16 || !Number.isInteger(n.midi_note) || n.midi_note < 0 || n.midi_note > 127 || !Number.isInteger(n.velocity) || n.velocity < 1 || n.velocity > 127) throw new Error('MIDI音符参数无效')
    }
  }
}
export class ManualEngine {
  constructor({ onUpdate = () => {}, onRecording = () => {}, contextFactory, fetcher = (...args) => globalThis.fetch(...args) } = {}) {
    this.onUpdate = onUpdate; this.onRecording = onRecording
    this.contextFactory = contextFactory || (() => new (window.AudioContext || window.webkitAudioContext)())
    this.fetcher = fetcher; this.generation = 0; this.events = []; this.running = false; this.loading = false
  }
  log(type, data = {}) { this.events.push({ time_s: this.ctx && this.origin ? Math.max(0, this.ctx.currentTime - this.origin) : 0, type, ...data }) }
  async loadTrack(id, signal) {
    const response = await this.fetcher(`/api/music/${encodeURIComponent(id)}/audio`, { signal, cache: 'no-store' })
    if (!response.ok) throw new Error('本地音频无法读取，请刷新音乐库或检查后端')
    const size = Number(response.headers.get('content-length'))
    if (size > 80_000_000) throw new Error('预览仅支持80MB以内的音频')
    const bytes = await response.arrayBuffer()
    if (bytes.byteLength > 80_000_000) throw new Error('预览仅支持80MB以内的音频')
    const sha = globalThis.crypto?.subtle ? Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('') : null
    const audio = await this.ctx.decodeAudioData(bytes)
    return { audio, sha }
  }
  async start({ padId, textureId = '', plans, seed = 42, transpose = 0, variation = 'auto', timbre = 'sine', record = false, initialState = 'M1' }) {
    if (this.running || this.loading) throw new Error('请先停止当前会话')
    validatePlans(plans)
    if (!padId || !PRESETS[initialState] || !['sine', 'triangle'].includes(timbre)) throw new Error('请检查素材和音色参数')
    const token = ++this.generation
    this.events = []; this.loading = true; this.target = initialState; this.active = initialState; this.timbre = timbre; this.plans = plans; this.volume = .15
    this.origin = 0; this.abort = new AbortController()
    try {
      this.ctx = this.contextFactory()
      const context = this.ctx
      // Resume synchronously from the user's click before network awaits.
      await context.resume()
      if (token !== this.generation) return
      const pad = await this.loadTrack(padId, this.abort.signal)
      if (token !== this.generation) return
      const texture = textureId ? await this.loadTrack(textureId, this.abort.signal) : null
      if (token !== this.generation) return
      this.graph(); this.origin = context.currentTime + .2; this.duration = pad.audio.duration
      this.metadata = { schema_version: 1, source: 'MANUAL', started_at: new Date().toISOString(), pad_id: padId, pad_sha256: pad.sha, texture_id: textureId || null, texture_sha256: texture?.sha || null, texture_duration_s: texture?.audio.duration || null, duration_s: this.duration, sample_rate_hz: context.sampleRate, seed, transpose, variation, timbre, bpm: 60, phrase_beats: 16, fade_seconds: 5, presets: PRESETS, plans, synthesis: 'oscillator preview; pad MIDI notes omitted in favor of Suno bed; no EEG input' }
      this.currentGains = { pad: 0, melody: 0, bass: 0, texture: 0 }
      this.sources = []; this.transitions = []; this.nextPhrase = 0
      this.startBuffer(pad.audio, 'pad'); if (texture) this.startBuffer(texture.audio, 'texture')
      this.log('start', { pad_id: padId, texture_id: textureId || null })
      if (record) this.startRecording()
      this.running = true; this.loading = false
      this.ctx.onstatechange = () => { if (this.running && this.ctx.state !== 'running') this.stop('audio-context-suspended') }
      this.tick(); this.timer = setInterval(() => this.tick(), 25)
    } catch (error) {
      if (token !== this.generation) return
      this.stop('error'); throw error
    }
  }
  graph() {
    const c = this.ctx
    this.bus = c.createGain(); this.filter = c.createBiquadFilter(); this.filter.type = 'lowpass'; this.filter.Q.value = .5
    this.wet = c.createGain(); this.delay = c.createDelay(1); this.delay.delayTime.value = .18
    this.feedback = c.createGain(); this.feedback.gain.value = .22
    this.compressor = c.createDynamicsCompressor(); this.compressor.threshold.value = -18; this.compressor.knee.value = 12; this.compressor.ratio.value = 8; this.compressor.attack.value = .003; this.compressor.release.value = .25
    this.master = c.createGain(); this.master.gain.value = 0
    this.outputVolume = c.createGain(); this.outputVolume.gain.value = this.volume
    this.bus.connect(this.filter); this.filter.connect(this.compressor)
    // Short feedback delay is a lightweight reverberation preview, not a room model.
    this.filter.connect(this.delay); this.delay.connect(this.feedback); this.feedback.connect(this.delay); this.delay.connect(this.wet); this.wet.connect(this.compressor)
    this.compressor.connect(this.master); this.master.connect(this.outputVolume); this.outputVolume.connect(c.destination)
    this.layers = {}; this.pans = {}; this.trims = {}
    for (const name of Object.keys(PRESETS.M1.gains)) {
      const gain = c.createGain(); gain.gain.value = 0; gain.connect(this.bus); this.layers[name] = gain
      const trim = c.createGain(); trim.gain.value = 1; trim.connect(gain); this.trims[name] = trim
      const pan = c.createStereoPanner(); pan.connect(trim); this.pans[name] = pan
    }
  }
  startBuffer(buffer, layer) {
    const source = this.ctx.createBufferSource(); source.buffer = buffer; source.loop = false
    source.connect(this.pans[layer]); source.start(this.origin); this.sources.push(source)
    this.log('audio-scheduled', { layer, start_s: 0, duration_s: buffer.duration, loop: false })
  }
  ramp(param, value, time, duration = 5) {
    if (param.cancelAndHoldAtTime) param.cancelAndHoldAtTime(time)
    else { param.cancelScheduledValues(time); param.setValueAtTime(param.value, time) }
    param.linearRampToValueAtTime(value, time + duration)
  }
  applyState(state, time) {
    const preset = PRESETS[state]
    for (const [layer, gain] of Object.entries(preset.gains)) this.ramp(this.layers[layer].gain, gain, time)
    this.ramp(this.filter.frequency, 300 + 6000 * preset.brightness, time)
    this.ramp(this.wet.gain, preset.reverb, time)
    this.ramp(this.pans.melody.pan, -.45 * preset.width, time); this.ramp(this.pans.texture.pan, .45 * preset.width, time)
    this.ramp(this.master.gain, preset.master, time)
  }
  note(note, time, phrase) {
    if (!['melody', 'bass'].includes(note.voice)) return // Keep Suno as the pad; do not double its harmony.
    const oscillator = this.ctx.createOscillator(), envelope = this.ctx.createGain()
    oscillator.type = note.voice === 'bass' ? 'sine' : this.timbre; oscillator.frequency.value = frequency(note.midi_note)
    const end = time + note.duration_beats, level = note.velocity / 127 * (note.voice === 'bass' ? .16 : .12)
    envelope.gain.setValueAtTime(0, time); envelope.gain.linearRampToValueAtTime(level, time + Math.min(.08, note.duration_beats / 3)); envelope.gain.setValueAtTime(level, end); envelope.gain.linearRampToValueAtTime(0, end + .4)
    oscillator.connect(envelope); envelope.connect(this.pans[note.voice]); oscillator.start(time); oscillator.stop(end + .45)
    oscillator.onended = () => { oscillator.disconnect(); envelope.disconnect() }
    this.log('midi-note-scheduled', { ...note, phrase, motif_phrase: note.phrase, start_s: time - this.origin })
  }
  tick() {
    if (!this.running) return
    const now = this.ctx.currentTime, elapsed = now - this.origin
    if (elapsed >= this.duration) { this.stop('pad-ended'); return }
    const boundary = this.origin + this.nextPhrase * 16
    // A missed clock deadline stops instead of bunching late notes together.
    if (now - boundary > .25) { this.stop('scheduler-underrun'); return }
    if (boundary <= now + .15) {
      const state = this.target
      this.applyState(state, boundary)
      for (const n of this.plans[state].notes) if (boundary + n.start_beat < this.origin + this.duration) this.note(n, boundary + n.start_beat, this.nextPhrase)
      this.transitions.push({ state, time: boundary }); this.log('phrase-scheduled', { phrase: this.nextPhrase, state, start_s: boundary - this.origin, parameters: PRESETS[state] }); this.nextPhrase++
    }
    while (this.transitions.length && this.transitions[0].time <= now) {
      const transition = this.transitions.shift(); this.active = transition.state; this.changedAt = transition.time
      this.log('state-applied', { state: this.active, start_s: transition.time - this.origin })
    }
    this.onUpdate({ running: true, elapsed: Math.max(0, elapsed), duration: this.duration, active: this.active, target: this.target, phrase: Math.max(0, Math.floor(elapsed / 16)) + 1, beat: Math.max(0, elapsed) % 16, progress: Math.min(1, Math.max(0, (now - (this.changedAt || this.origin)) / 5)), nextBoundary: this.nextPhrase * 16, gains: PRESETS[this.active].gains, parameters: PRESETS[this.active] })
  }
  requestState(state) {
    if (!PRESETS[state]) throw new Error('未知音乐状态')
    this.target = state; this.log('state-requested', { state, apply_at_s: this.nextPhrase * 16 })
  }
  setLayerLevel(layer, value) {
    if (!this.running || !this.trims[layer]) return
    const level = Math.max(0, Math.min(1, Number(value) || 0))
    this.ramp(this.trims[layer].gain, level, this.ctx.currentTime, 1.5)
    this.log('layer-trim', { layer, level })
  }
  setVolume(value) {
    this.volume = Math.max(0, Math.min(.4, Number(value) || 0))
    if (this.running) this.ramp(this.outputVolume.gain, this.volume, this.ctx.currentTime, 1.5)
    this.log('volume', { volume: this.volume })
  }
  startRecording() {
    if (typeof MediaRecorder === 'undefined' || !this.ctx.createMediaStreamDestination) throw new Error('浏览器不支持录音，请关闭录音选项后重试')
    const destination = this.ctx.createMediaStreamDestination(); this.outputVolume.connect(destination)
    const types = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']; const mimeType = types.find(t => MediaRecorder.isTypeSupported(t))
    if (!mimeType) throw new Error('浏览器没有可用的录音编码，请关闭录音选项')
    const recorder = new MediaRecorder(destination.stream, { mimeType }), chunks = []
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    recorder.onstop = () => { this.onRecording(new Blob(chunks, { type: mimeType })); destination.stream.getTracks().forEach(t => t.stop()) }
    recorder.start(1000); this.recorder = recorder; this.log('recording-start', { mime_type: mimeType })
  }
  stop(reason = 'user-stop') {
    this.generation++; this.abort?.abort(); clearInterval(this.timer); this.running = false; this.loading = false
    if (this.ctx) { this.log('stop', { reason }); this.ctx.onstatechange = null; if (this.master) { this.master.gain.cancelScheduledValues(this.ctx.currentTime); this.master.gain.setValueAtTime(0, this.ctx.currentTime) } }
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop()
    this.recorder = null
    for (const source of this.sources || []) { try { source.stop() } catch { /* Already ended. */ } }
    this.ctx?.close()?.catch(() => {})
    this.onUpdate({ running: false, reason })
  }
  exportLog() { return { ...this.metadata, events: this.events.slice(), limitations: 'Manual oscillator preview; scheduled events are not hardware loopback evidence. Audio recording, if enabled, is browser post-master output, not microphone/SPL. Exact replay across browsers is not guaranteed.' } }
}
