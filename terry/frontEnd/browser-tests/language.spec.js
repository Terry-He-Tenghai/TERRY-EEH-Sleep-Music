import { test, expect } from '@playwright/test'

test('EEG music status and recording details follow the selected language', async ({ page }) => {
  let stemRequests = 0
  await page.routeWebSocket('**/ws/waveform', () => {})
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/session-reports/experiments/summary') return route.fulfill({json:{rows:[],experiment_execution_version:1}})
    if (path === '/api/acquisition/recording-info') return route.fulfill({ json: { raw_recording_version: 1 } })
    if (path === '/api/stem-music') stemRequests += 1
    if (path === '/api/acquisition/start' || path === '/api/acquisition/stop') {
      const streaming = path.endsWith('/start')
      return route.fulfill({ json: { streaming, connected: streaming, sample_rate_hz: 250, channels: ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2'] } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('button', {name:'输入受试者姓名'}).click()
  await page.getByLabel('姓名或编号', {exact:true}).fill('P001')
  await page.getByRole('button', {name:'确认',exact:true}).click()
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

test('English translates existing LIVE quality states, advanced tools and administration', async ({ page }) => {
  let socket
  const channels = ['C3', 'C4', 'Cz', 'FC3', 'FC4', 'CP3', 'CP4', 'FCz', 'CPz', 'Fz', 'P3', 'Pz', 'P4', 'O1', 'Oz', 'O2']
  await page.routeWebSocket('**/ws/waveform', ws => { socket = ws })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/session-reports') return route.fulfill({ json: [] })
    if (path.endsWith('/experiments/summary')) return route.fulfill({ json: { rows: [], experiment_execution_version: 1 } })
    if (path.endsWith('/recording-info')) return route.fulfill({ json: { raw_recording_version: 1 } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await expect.poll(() => Boolean(socket)).toBe(true)
  socket.send(JSON.stringify({ type: 'status', streaming: true, connected: true, mode: 'brainflow',
    sample_rate_hz: 250, channels, experiment: { participant: 'P001', condition: 'closed_loop', visit: 1 } }))
  const event = { type: 'adaptive_music', source: 'LIVE', session_id: 'test-live', sequence: 1,
    emitted_at_s: Date.now()/1000, timestamp_s: 42, status: 'frozen', reason: 'invalid_or_low_quality_eeg',
    inference_mode: 'waveform_cnn', probability_origin: 'trained_waveform_cnn_experimental',
    classification_channels: 16, classification_confirmed: false, signal_quality: 0,
    waveform_model: { model: 'cap16', collected_seconds: 40, required_seconds: 40 } }
  socket.send(JSON.stringify(event))
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('en')
  const assertEnglish = async () => {
    const chinese = await page.locator('body').evaluate(body => {
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
      const found = []
      while (walker.nextNode()) {
        const node = walker.currentNode, parent = node.parentElement
        if (parent.closest('select[aria-label="Language / 语言"], script, style') || !parent.checkVisibility()) continue
        if (/[\u3400-\u9fff]/.test(node.textContent)) found.push(node.textContent.trim())
      }
      return found
    })
    expect(chinese).toEqual([])
  }
  await expect(page.locator('.ace-auto')).toContainText('Current EEG classification:')
  await assertEnglish()
  for (const summary of await page.locator('details > summary').all()) await summary.click()
  await assertEnglish()
  socket.send(JSON.stringify({ ...event, sequence: 2, status: 'ready', state: { status: 'ok' },
    playback_mode: 'adaptive', reason: 'waveform_classification_ready', signal_quality: 1,
    classification_confirmed: true, probabilities: { W: .1, N1: .2, N2: .7 }, emitted_at_s: Date.now()/1000 }))
  await expect(page.locator('.ace-auto')).toContainText('Quality accepted; generation enabled')
  await assertEnglish()
  await page.screenshot({ path: '/tmp/terry-english-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await assertEnglish()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/terry-english-mobile.png', fullPage: true })
  socket.send(JSON.stringify({ type: 'status', streaming: false, connected: false,
    sample_rate_hz: 250, channels }))
  await expect(page.locator('#music-source')).toBeEnabled()
  await page.locator('#music-source').selectOption('upload')
  await expect(page.locator('#music-upload')).toBeVisible()
  await assertEnglish()
  await page.getByRole('button', { name: 'Administration · Experiments' }).click()
  await expect(page.getByRole('heading', { name: 'Experiment Analysis', exact: true })).toBeVisible()
  await assertEnglish()
})
