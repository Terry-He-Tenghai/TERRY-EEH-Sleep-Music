import { test, expect } from '@playwright/test'

test('real backend showcase cycles W N1 N2 and changes original stem audio controls', async ({ page }) => {
  test.skip(process.env.TERRY_STEM_INTEGRATION !== '1', 'Requires local BabySlakh and isolated backend :8011')
  test.setTimeout(100000)
  // HTTP polling uses the real backend. No injected probabilities or accelerated clock.
  await page.routeWebSocket('**/ws/waveform', () => {})
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/stem-music') || path.startsWith('/api/acquisition/') || path === '/api/adaptive/status') {
      const response = await route.fetch({ url: `http://127.0.0.1:8011${path}` })
      return route.fulfill({ response })
    }
    if (path === '/api/music/choices') return route.fulfill({ json: { styles:[{id:'all',label:'All',count:0}] } })
    return route.fulfill({ json:{tracks:[],status:'missing'} })
  })
  try {
    await page.goto('/')
    await page.selectOption('#music-source','stems')
    await expect(page.locator('#demo-profile')).toHaveValue('showcase')
    await expect(page.locator('#stem-track option')).toHaveCount(2)
    await page.getByRole('button',{name:'开始采集',exact:true}).click()
    await expect(page.locator('.stem-panel')).toContainText('同步播放中',{timeout:15000})
    await expect(page.locator('.stem-panel')).toContainText('当前预设 W')
    const first=await page.locator('.stem-grid small').allTextContents()
    await expect(page.locator('.stem-panel')).toContainText('当前预设 N1',{timeout:35000})
    await expect(page.locator('.stem-panel')).toContainText('当前预设 N2',{timeout:35000})
    await page.waitForTimeout(4000)
    const last=await page.locator('.stem-grid small').allTextContents()
    expect(first).not.toEqual(last)
    await expect(page.locator('.stem-panel')).toContainText('非机器学习预测')
    await expect(page.locator('.stem-panel')).toContainText('同步播放中')
  } finally {
    await page.request.post('http://127.0.0.1:8011/api/acquisition/stop')
  }
})
