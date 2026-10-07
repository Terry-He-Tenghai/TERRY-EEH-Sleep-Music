import { test, expect } from '@playwright/test'

test('experiment administration filters demos, persists labels and switches language', async ({ page }) => {
  let saved
  const row = { id: 'a'.repeat(32), started_at_s: 1700000000, ended: true, mode: 'brainflow', participant: 'P001', condition: 'fixed', duration_s: 60, qualified_window_ratio: .8, recording_status: 'recording' }
  await page.route('**/api/session-reports**', route => {
    const url = route.request().url()
    if (url.endsWith('/experiment')) {
      saved = route.request().postDataJSON()
      return route.fulfill({ json: { status: 'saved' } })
    }
    if (url.endsWith('/experiments/summary')) return route.fulfill({ json: { storage: '/local/session_reports', rows: [row, { ...row, id: 'b'.repeat(32), mode: 'demo' }, { ...row, id: 'c'.repeat(32), condition: 'closed_loop', duration_s: 80 }] } })
    if (url.endsWith(row.id)) return route.fulfill({ json: { experiment: { participant: 'P001', condition: 'fixed', trial: 1, notes: '' } } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/')
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('en')
  await page.getByRole('button', { name: 'Administration · Experiments' }).click()
  await expect(page.getByRole('heading', { name: 'Experiment Analysis' })).toBeVisible()
  await expect(page.getByText('2 completed sessions', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '20.00 (n=1)', exact: true })).toBeVisible()
  await page.getByLabel('Include demo / non-device records').check()
  await expect(page.getByText('3 completed sessions', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Label', exact: true }).first().click()
  await page.getByLabel('Anonymous ID (not a name)').fill('P002')
  await page.getByLabel('Condition actually performed').selectOption('closed_loop')
  await page.getByRole('button', { name: 'Save Labels', exact: true }).click()
  await expect.poll(() => saved?.participant).toBe('P002')
  expect(saved.condition).toBe('closed_loop')
  expect(saved.comfort).toBeNull()
  await page.screenshot({ path: '/tmp/terry-experiment-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/terry-experiment-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'EEG Music', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('zh')
  await expect(page.getByRole('heading', { name: '脑电音乐', exact: true })).toBeVisible()
})
