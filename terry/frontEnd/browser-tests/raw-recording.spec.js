import { test, expect } from '@playwright/test'

test('experiment raw recording is mandatory and saved status and failure remain visible', async ({ page }) => {
  let enabled = true
  const channels = ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2']
  let socket
  await page.routeWebSocket('**/ws/waveform', ws => { socket = ws })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/session-reports/experiments/summary') return route.fulfill({json:{rows:[],experiment_execution_version:1}})
    if (path === '/api/acquisition/recording-info') return route.fulfill({ json: { raw_recording_version: 1 } })
    if (path === '/api/acquisition/start' || path === '/api/acquisition/stop') {
      const streaming = path.endsWith('/start')
      if (streaming) enabled = route.request().postDataJSON().save_raw_data
      return route.fulfill({ json: { streaming, connected: streaming, sample_rate_hz: 250, channels,
        recording: enabled ? { path: '/Users/tenghai/Desktop/Terry_EEG_Project/new_code2/terry/backEnd/recordings/20261008_session_test',
          complete: !streaming, error: null, samples_written: streaming ? 0 : 250 } : null } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('button', {name:'输入受试者姓名'}).click()
  await page.getByLabel('姓名或编号', {exact:true}).fill('P001')
  await page.getByRole('button', {name:'确认',exact:true}).click()
  const toggle = page.getByRole('checkbox', { name: '保存原始脑电到本地' })
  await expect(toggle).toBeChecked()
  await expect(toggle).toBeDisabled()
  await page.getByRole('button', { name: '开始采集' }).click()
  await expect.poll(() => enabled).toBe(true)
  await expect(page.locator('.recording-status')).toContainText('正在保存')
  await page.screenshot({ path: 'test-results/raw-recording-desktop.png', fullPage: true })
  await page.getByRole('button', { name: '停止采集' }).click()
  await expect(page.locator('.recording-status')).toContainText('保存完成')
  await expect(toggle).toBeDisabled()
  await page.setViewportSize({ width: 390, height: 844 })
  const rect = await page.locator('.recording-status').boundingBox()
  expect(rect.x + rect.width).toBeLessThanOrEqual(390)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/raw-recording-mobile.png', fullPage: true })
  socket.send(JSON.stringify({ type: 'samples', sample_rate_hz: 250, channels,
    timestamp_s: 0, samples_uv: channels.map(() => [1]),
    recording: { path: '/tmp/test', samples_written: 0, complete: false, error: '磁盘空间不足' } }))
  await expect(page.locator('.recording-status')).toContainText('保存异常')
  await expect(page.getByRole('alert').filter({ hasText: '磁盘空间不足' })).toBeVisible()
})
