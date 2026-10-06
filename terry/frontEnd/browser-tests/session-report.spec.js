import { test, expect } from '@playwright/test'

test('final master output is recorded as nonempty stereo float WAV and attached to its session', async ({ page }) => {
  let telemetry, recording
  await page.route('**/api/session-reports/**', async route => {
    if (route.request().url().endsWith('/browser')) telemetry = route.request().postDataJSON()
    if (route.request().url().endsWith('/audio')) recording = route.request().postDataBuffer()
    await route.fulfill({ json: { status: 'saved' } })
  })
  await page.goto('/')
  const result = await page.evaluate(async () => {
    const evidence = await import('/src/audio/sessionEvidence.js')
    const context = new AudioContext()
    await context.resume()
    evidence.beginEvidence({ mode: 'test', music_source: 'known-oscillator' })
    evidence.bindEvidence('a'.repeat(32))
    const master = context.createGain(); master.gain.value = .1; master.connect(context.destination)
    await evidence.recordOutput(context, master, 'test')
    const source = context.createOscillator(); source.frequency.value = 440; source.connect(master); source.start()
    await new Promise(resolve => setTimeout(resolve, 1600))
    const completion = new Promise(resolve => window.addEventListener('session-report-ready', event => resolve(event.detail), { once: true }))
    await evidence.finishEvidence('manual_stop')
    source.stop(); await context.close()
    return completion
  })
  expect(result.error).toBeUndefined()
  expect(telemetry.recorded_seconds).toBeGreaterThan(.3)
  expect(telemetry.recording_status).toBe('recording')
  expect(recording.subarray(0, 4).toString()).toBe('RIFF')
  expect(recording.readUInt16LE(20)).toBe(3)
  expect(recording.readUInt16LE(22)).toBe(2)
  const values = new Float32Array(recording.buffer, recording.byteOffset + 44, (recording.length - 44)/4)
  expect(values.some(value => Math.abs(value) > .01)).toBeTruthy()
  expect(values.every(value => Number.isFinite(value) && Math.abs(value) <= .11)).toBeTruthy()
  await page.screenshot({ path: '/tmp/terry-session-report-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/terry-session-report-mobile.png', fullPage: true })
})
