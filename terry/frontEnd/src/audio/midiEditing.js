// Browser-side editing/export of the exact melody and bass used by the preview.
export function editPlans(plans, { motif = '', transpose = 0, durationScale = 1, variation = 'auto' } = {}) {
  const pitches = motif.trim() ? motif.trim().split(/[\s,，]+/).map(Number) : []
  if (pitches.length && (pitches.length < 4 || pitches.length > 8 || pitches.some(p => !Number.isInteger(p) || p < 48 || p > 96 || ![0, 2, 4, 5, 7, 9, 11].includes(p % 12)))) throw new Error('自编动机需4–8个C大调/A小调内的MIDI音高（48–96），以空格分隔')
  if (![.5, 1, 2].includes(Number(durationScale)) || ![-12, 0, 12].includes(Number(transpose))) throw new Error('音长或八度参数无效')
  return Object.fromEntries(Object.entries(plans).map(([state, plan]) => {
    let index = 0
    const reduced = variation === 'reduced' || (variation === 'auto' && state === 'M2')
    const { midi_quality: baseQuality, ...basePlan } = plan
    return [state, { ...basePlan, base_midi_quality: baseQuality, editing_applied: true, notes: plan.notes.filter(n => n.voice !== 'pad').map(note => {
      if (note.voice !== 'melody') return { ...note }
      const pitch = pitches.length ? pitches[((index++) * (reduced ? 2 : 1)) % pitches.length] + Number(transpose) : note.midi_note
      if (pitch < 36 || pitch > 108) throw new Error('移调后音高超出预览范围')
      return { ...note, midi_note: pitch, duration_beats: Math.min(16, note.duration_beats * Number(durationScale)) }
    }) }]
  }))
}
function vlq(number) {
  const bytes = [number & 127]
  while ((number >>= 7) > 0) bytes.unshift((number & 127) | 128)
  return bytes
}
export function midiBytes(plan, timbre = 'sine') {
  const events = [{ tick: 0, bytes: [255, 81, 3, 15, 66, 64] }] // 60 BPM
  // GM programs are hints only; external synthesizers will not match oscillators.
  events.push({ tick: 0, bytes: [192, timbre === 'triangle' ? 80 : 73] }, { tick: 0, bytes: [193, 32] })
  for (const n of plan.notes.filter(n => ['melody', 'bass'].includes(n.voice))) {
    const channel = n.voice === 'bass' ? 1 : 0
    events.push({ tick: Math.round(n.start_beat * 480), bytes: [144 + channel, n.midi_note, n.velocity] })
    events.push({ tick: Math.round((n.start_beat + n.duration_beats) * 480), bytes: [128 + channel, n.midi_note, 0] })
  }
  events.sort((a, b) => a.tick - b.tick || ((a.bytes[0] & 240) === 144) - ((b.bytes[0] & 240) === 144))
  let tick = 0; const track = []
  for (const event of events) { track.push(...vlq(event.tick - tick), ...event.bytes); tick = event.tick }
  track.push(0, 255, 47, 0)
  const length = track.length
  return new Uint8Array([77,84,104,100,0,0,0,6,0,0,0,1,1,224,77,84,114,107,(length>>>24)&255,(length>>>16)&255,(length>>>8)&255,length&255,...track])
}
