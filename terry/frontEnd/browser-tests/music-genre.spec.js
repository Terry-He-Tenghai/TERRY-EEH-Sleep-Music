import { test, expect } from '@playwright/test'

test('optional genres submit in both workflows and fit mobile', async ({ page }) => {
  const submissions = []
  await page.route('**/api/**', route => {
    const url = route.request().url()
    if (url.endsWith('/experiments/summary')) return route.fulfill({json:{rows:[],experiment_execution_version:1}})
    if (url.endsWith('/acquisition/recording-info')) return route.fulfill({ json: { raw_recording_version: 1 } })
    if (url.endsWith('/acquisition/start') || url.endsWith('/ace/generations')) {
      submissions.push({ url, body: route.request().postDataJSON() })
      return route.fulfill({ status: 503, json: { detail: 'Test submission captured' } })
    }
    if (url.endsWith('/adaptive/status')) return route.fulfill({ json: { type: 'adaptive_music', status: 'stopped' } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/')
  await page.getByRole('button', {name:'输入受试者姓名'}).click()
  await page.getByLabel('姓名或编号', {exact:true}).fill('P001')
  await page.getByRole('button', {name:'确认',exact:true}).click()
  const genre = page.getByLabel('音乐流派（可选）').first()
  await expect(genre).toHaveValue('')
  await page.getByRole('button', { name: '开始采集', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(1)
  expect(submissions[0].body.music_genre).toBeNull()
  for (const selected of ['classical', 'jazz', 'folk', '']) {
    await genre.selectOption(selected)
    await page.getByRole('button', { name: '开始采集', exact: true }).click()
    await expect.poll(() => submissions.at(-1)?.body.music_genre).toBe(selected || null)
  }
  await genre.selectOption('classical')
  await page.getByText('高级工具 · AI 生成调试', { exact: true }).click()
  const manual = page.locator('.ace-music')
  await expect(manual.getByLabel('音乐流派（可选）')).toHaveValue('')
  await manual.getByLabel('音乐流派（可选）').selectOption('jazz')
  await manual.getByRole('button', { name: '生成音乐', exact: true }).click()
  await expect.poll(() => submissions.at(-1)?.body.music_genre).toBe('jazz')
  expect(submissions.at(-1).body.style).toBe('ambient')
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('en')
  await expect(page.getByLabel('Music Genre (optional)').first()).toHaveValue('classical')
  await page.screenshot({ path: '/tmp/terry-genre-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/terry-genre-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
