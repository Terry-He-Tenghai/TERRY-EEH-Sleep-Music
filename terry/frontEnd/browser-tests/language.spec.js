import { test, expect } from '@playwright/test'

test('EEG music status and recording details follow the selected language', async ({ page }) => {
  let stemRequests = 0
  await page.routeWebSocket('**/ws/waveform', () => {})
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/stem-music') stemRequests += 1
    if (path === '/api/acquisition/start' || path === '/api/acquisition/stop') {
      const streaming = path.endsWith('/start')
      return route.fulfill({ json: { streaming, connected: streaming, sample_rate_hz: 250, channels: ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2'] } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await expect(page.locator('#music-source option')).toHaveCount(2)
  await expect(page.locator('#music-source')).not.toContainText('BabySlakh')
  expect(stemRequests).toBe(0)
  await page.locator('#music-source').selectOption('upload')
  await expect(page.locator('#music-upload')).toBeVisible()
  await page.locator('#music-source').selectOption('ace')

  const language = page.getByRole('combobox', { name: 'Language / 语言' })
  const music = page.locator('.ace-auto')
  const waveform = page.locator('details.workspace-details', { has: page.locator('summary', { hasText: '脑电波形与采集指标' }) })
  const notes = page.locator('details.workspace-details', { has: page.locator('summary', { hasText: '采集与播放说明' }) })
  await page.getByRole('button', { name: '开始采集' }).click()
  await page.getByRole('button', { name: '停止采集' }).click()
  await expect(music).toContainText('已停止')
  await expect(music).toContainText('分类状态：等待有效稳定分类 · 个体基线：后台收集中')
  await expect(waveform.locator('summary')).toContainText('采集 16 路 · 分类 16 路 · 可见 16 路 · 250 Hz')
  await expect(notes.locator('summary')).toHaveText('采集与播放说明')

  await language.selectOption('en')
  await expect(page.locator('#music-source')).not.toContainText('BabySlakh')
  await expect(music).toContainText('Stopped')
  await expect(music).toContainText('Classification: Waiting for stable valid classification · Personal baseline: Collecting in background')
  const waveformSummary = page.locator('details.workspace-details > summary', { hasText: 'EEG Waveform & Metrics' })
  const notesSummary = page.locator('details.workspace-details > summary', { hasText: 'Recording & Playback Notes' })
  await expect(waveformSummary).toContainText('Recorded 16 channels · Classified 16 channels · Visible 16 channels · 250 Hz')
  await expect(notesSummary).toHaveText('Recording & Playback Notes')
  for (const section of [music, waveformSummary, notesSummary]) {
    await expect(section).not.toContainText(/[\u3400-\u9fff]/)
  }

  await page.reload()
  await expect(page.locator('.ace-auto')).toContainText('Waiting for valid EEG classification')
  await expect(page.locator('details.workspace-details > summary', { hasText: 'EEG Waveform & Metrics' })).toBeVisible()
})
