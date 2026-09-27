import { test, expect } from '@playwright/test'

// Requires isolated backend on :8011; uses real local WAVs and explicit synthetic
// control events. Never starts hardware acquisition or claims physiological input.
test('real BabySlakh stems load and respond to synthetic state without restarts', async ({ page }) => {
  test.skip(process.env.TERRY_STEM_INTEGRATION !== '1', 'Opt-in: requires local BabySlakh backend on :8011')
  await page.route('**/api/stem-music**', async route => {
    const u = new URL(route.request().url())
    const response = await route.fetch({ url: `http://127.0.0.1:8011${u.pathname}` })
    await route.fulfill({ response })
  })
  await page.goto('/')
  await page.evaluate(() => {
    const button = document.createElement('button'); button.id='stem-test-start'; button.style.cssText='position:fixed;top:100px;left:20px;z-index:999999'; button.textContent='Test audio'
    button.onclick = async () => {
      const { StemEngine } = await import('/src/audio/stemEngine.js')
      const data = await (await fetch('/api/stem-music')).json()
      const engine = new StemEngine(); window.testStemEngine = engine
      await engine.arm(data.tracks.find(t => t.id==='Track00008'))
      window.stemsLoaded=true
    }
    document.body.prepend(button)
  })
  await page.click('#stem-test-start')
  await page.waitForFunction(() => window.stemsLoaded === true)
  const result = await page.evaluate(async () => {
    const e=window.testStemEngine
    const frame=(sequence, level) => ({ type:'adaptive_music', session_id:999, sequence, emitted_at_s:Date.now()/1000, source:'DEMO', status:'ready', playback_mode:'adaptive', state:{status:'ok',baseline_ready:true}, probabilities:{W:.8,N1:.15,N2:.05}, signal_quality:1,
      stem_mix:{track_id:'Track00008', mode:'adaptive',control_level:level,brightness:.15+.65*level, transition_seconds:1,
        gains:{piano:.18+.52*level,strings:.32-.20*level,bass:.04+.28*level,pad:.28-.20*level}} })
    e.consume(frame(1,1)); e.tick()
    await new Promise(r => setTimeout(r,1200))
    const first=e.stems.map(s => ({role:s.role,value:s.gain.gain.value}))
    const origin=e.origin
    e.consume(frame(2,0)); e.tick()
    await new Promise(r => setTimeout(r,1200))
    const second=e.stems.map(s => ({role:s.role,value:s.gain.gain.value}))
    const count=e.entries.size, sameOrigin=e.origin===origin
    async function render(level) {
      const { StemEngine } = await import('/src/audio/stemEngine.js')
      const ctx=new OfflineAudioContext(1,16000*8,16000), player=new StemEngine()
      player.ctx=ctx; player.duration=8; player.master=ctx.createGain(); player.master.gain.value=.18
      player.master.connect(ctx.destination)
      player.stems=e.stems.map(stem => {
        const buffer=ctx.createBuffer(1,16000*8,16000)
        buffer.copyToChannel(stem.buffer.getChannelData(0).slice(16000*30,16000*38),0)
        const gain=ctx.createGain(); gain.gain.value=frame(1,level).stem_mix.gains[stem.role]; gain.connect(player.master)
        return {...stem,buffer,gain}
      })
      player.scheduleCycle(0)
      const rendered=await ctx.startRendering(), data=rendered.getChannelData(0)
      player.ctx=null; player.dispose()
      return data
    }
    const a=await render(1), b=await render(0)
    let energy=0,difference=0,peak=0
    for(let i=0;i<a.length;i++) { energy+=a[i]*a[i]; difference+=(a[i]-b[i])**2; peak=Math.max(peak,Math.abs(a[i]),Math.abs(b[i])) }
    e.stop('test-complete')
    return { first,second,count,sameOrigin,stopped:e.entries.size,rms:Math.sqrt(energy/a.length),difference:Math.sqrt(difference/a.length),peak }
  })
  expect(result.rms).toBeGreaterThan(.00001)
  expect(result.difference).toBeGreaterThan(result.rms * .1)
  expect(result.peak).toBeLessThan(1)
  expect(result.count).toBe(4); expect(result.sameOrigin).toBe(true); expect(result.stopped).toBe(0)
  expect(result.first.find(s => s.role==='piano').value).toBeGreaterThan(result.second.find(s => s.role==='piano').value * 2)
  expect(result.second.find(s => s.role==='strings').value).toBeGreaterThan(result.first.find(s => s.role==='strings').value * 2)
})
