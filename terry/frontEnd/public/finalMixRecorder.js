class FinalMixRecorder extends AudioWorkletProcessor {
  constructor() {
    super()
    this.frames = []
    this.length = 0
    this.port.onmessage = () => { this.flush(); this.port.postMessage({ flushed: true }) }
  }
  flush() {
    if (!this.length) return
    const pcm = new Float32Array(this.length * 2)
    let offset = 0
    for (const frame of this.frames) { pcm.set(frame, offset); offset += frame.length }
    this.port.postMessage({ pcm: pcm.buffer }, [pcm.buffer])
    this.frames = []; this.length = 0
  }
  process(inputs) {
    const channels = inputs[0]
    if (channels?.[0]) {
      const pcm = new Float32Array(channels[0].length * 2)
      for (let i = 0; i < channels[0].length; i++) {
        for (let ch = 0; ch < 2; ch++) {
          pcm[i * 2 + ch] = (channels[ch] || channels[0])[i]
        }
      }
      this.frames.push(pcm); this.length += channels[0].length
      if (this.length >= sampleRate / 4) this.flush()
    }
    return true
  }
}
registerProcessor('final-mix-recorder', FinalMixRecorder)
