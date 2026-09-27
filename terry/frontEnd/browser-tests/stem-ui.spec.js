import { test, expect } from '@playwright/test'

test('selecting stem mode sends selected ID and plays projected conservative then adaptive events', async ({ page }) => {
  test.skip(process.env.TERRY_STEM_INTEGRATION !== '1', 'Opt-in local BabySlakh backend on :8011')
  let started = false, sequence=0, selected=null, adaptive=false
  const frame=() => ({ type:'adaptive_music', session_id:777, sequence:++sequence, source:'DEMO', emitted_at_s:Date.now()/1000,
    timestamp_s:adaptive ? 320 : 6, status:started ? 'ready':'stopped', reason:'synthetic_browser_test', playback_mode:adaptive ? 'adaptive':'conservative',
    state:{status:adaptive?'ok':'warming_up',baseline_ready:adaptive}, probabilities:adaptive?{W:.8,N1:.15,N2:.05}:null, signal_quality:1,
    channel_repair:{valid_channels:['C3']}, stem_mix:{track_id:'Track00008',mode:adaptive?'adaptive':'conservative',control_level:adaptive?.8:null,
      brightness:.3,transition_seconds:1,gains:adaptive?{piano:.6,strings:.2,bass:.2,pad:.1}:{piano:.12,strings:.08,bass:.02,pad:.10}} })
  await page.routeWebSocket('**/ws/waveform', () => {})
  await page.route('**/api/**', async route => {
    const path=new URL(route.request().url()).pathname
    if(path.startsWith('/api/stem-music')) { const response=await route.fetch({url:`http://127.0.0.1:8011${path}`}); return route.fulfill({response}) }
    if(path==='/api/acquisition/start') { selected=route.request().postDataJSON(); started=true; return route.fulfill({json:{streaming:true,connected:true,sample_rate_hz:250,samples_emitted:0}}) }
    if(path==='/api/adaptive/status') return route.fulfill({json:frame()})
    if(path==='/api/music/choices') return route.fulfill({json:{styles:[{id:'all',label:'All',count:0}]}})
    return route.fulfill({json:{tracks:[],status:'missing'}})
  })
  await page.goto('/')
  await page.selectOption('#music-source','stems')
  await expect(page.locator('#stem-track option')).toHaveCount(2)
  await page.getByRole('button',{name:'开始采集',exact:true}).click()
  await expect(page.locator('.stem-panel')).toContainText('同步播放中',{timeout:20000})
  expect(selected.stem_track_id).toBe('Track00008'); expect(selected.uploaded_track_id).toBeNull()
  await expect(page.locator('.stem-panel')).toContainText('固定混音')
  adaptive=true
  await expect(page.locator('.stem-panel')).toContainText('有效脑电驱动原曲声部比例与亮度',{timeout:10000})
  await expect(page.locator('.stem-grid article')).toHaveCount(4)
  await page.getByRole('button',{name:'停止分轨声音',exact:true}).click()
  await expect(page.locator('.stem-panel')).toContainText('已停止')
})
