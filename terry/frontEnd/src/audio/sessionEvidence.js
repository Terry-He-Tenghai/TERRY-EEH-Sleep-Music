const api = (import.meta.env?.VITE_API_BASE || '').replace(/\/$/, '')
let active = null
export function beginEvidence(metadata) {
  active = { metadata, started_at_s: Date.now()/1000, events: [], chunks: [], bytes: 0,
    recording_status: 'waiting_for_audio', id: null, finished: false }
}
export function bindEvidence(id) { if (active && !active.finished) active.id = id }
export function logEvidence(type, fields = {}) {
  if (!active || active.finished) return
  if (active.events.length >= 100000) { active.telemetry_truncated = true; return }
  active.events.push({ type, browser_at_s: Date.now()/1000, ...fields })
}
export async function recordOutput(context, output, engine) {
  const session = active
  if (!session || session.finished) return
  try {
    await context.audioWorklet.addModule('/finalMixRecorder.js')
    if (session !== active || session.finished || context.state === 'closed') return
    const node = new AudioWorkletNode(context, 'final-mix-recorder', { channelCount: 2 })
    const mute = context.createGain(); mute.gain.value = 0
    session.context = context; session.node = node; session.mute = mute; session.output = output; session.rate = context.sampleRate
    session.recording_status = 'recording'; session.recording_started_at_s = Date.now()/1000
    session.recording_started_audio_s = context.currentTime
    // The recorder's output is silence. The normal speaker branch is unchanged.
    output.connect(node); node.connect(mute); mute.connect(context.destination)
    node.port.onmessage = ({ data }) => {
      if (data.flushed) { session.resolveFlush?.(); return }
      if (!data.pcm || session.finished) return
      if (session.bytes + data.pcm.byteLength > 360 * 1024 * 1024) {
        session.recording_status = 'partial_memory_limit'; output.disconnect(node); return
      }
      session.bytes += data.pcm.byteLength; session.chunks.push(data.pcm)
    }
    logEvidence('recording-started', { engine, audio_time_s: context.currentTime })
  } catch (error) { session.recording_status = 'unavailable'; session.recording_error = error.message }
}
function wav(session) {
  const header = new ArrayBuffer(44), view = new DataView(header)
  const text = (at, value) => { [...value].forEach((ch, i) => view.setUint8(at+i, ch.charCodeAt(0))) }
  text(0, 'RIFF'); view.setUint32(4, 36+session.bytes, true); text(8, 'WAVE'); text(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 3, true); view.setUint16(22, 2, true)
  view.setUint32(24, session.rate, true); view.setUint32(28, session.rate*8, true)
  view.setUint16(32, 8, true); view.setUint16(34, 32, true); text(36, 'data'); view.setUint32(40, session.bytes, true)
  return new Blob([header, ...session.chunks], { type: 'audio/wav' })
}
export async function finishEvidence(reason) {
  const session = active
  if (!session || session.finishing) return
  session.finishing = true
  if (session.node && session.context.state !== 'closed') {
    await new Promise(resolve => {
      session.resolveFlush = resolve; session.node.port.postMessage('flush'); setTimeout(resolve, 300)
    })
  }
  session.finished = true
  try { session.output?.disconnect(session.node); session.node?.disconnect(); session.mute?.disconnect() } catch { /* Context already ended. */ }
  const audio = session.bytes ? wav(session) : null
  const evidence = { metadata: session.metadata, reason, started_at_s: session.started_at_s,
    ended_at_s: Date.now()/1000, recording_status: session.recording_status,
    recording_started_at_s: session.recording_started_at_s, recording_error: session.recording_error,
    recording_started_audio_s: session.recording_started_audio_s,
    recording_ended_audio_s: session.context?.currentTime ?? null,
    recorded_seconds: session.rate ? session.bytes/(session.rate*8) : 0, events: session.events,
    telemetry_truncated: !!session.telemetry_truncated, recording_format: 'stereo float32 PCM WAV',
    tail_uncertainty_s: .25, physical_output_latency_ms: null,
    unknown_metrics: ['remote queue/inference time', 'hardware loopback latency', 'ear SPL', 'validated comfort'] }
  try {
    if (!session.id) throw new Error('No report ID received')
    const response = await fetch(`${api}/api/session-reports/${session.id}/browser`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(evidence) })
    if (!response.ok) throw new Error('Browser evidence upload failed')
    if (audio) {
      const response = await fetch(`${api}/api/session-reports/${session.id}/audio`, { method: 'PUT', body: audio })
      if (!response.ok) throw new Error('Final mix recording upload failed')
    }
    window.dispatchEvent(new CustomEvent('session-report-ready', { detail: { id: session.id } }))
  } catch (error) {
    window.dispatchEvent(new CustomEvent('session-report-ready', {
      detail: { id: session.id, error: error.message, evidence, audio } }))
  }
  session.chunks = []
}
