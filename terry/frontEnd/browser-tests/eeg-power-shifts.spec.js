import { test, expect } from '@playwright/test'

const measured = {
  id: '1'.repeat(32), started_at_s: 1700000000, ended: true, mode: 'brainflow',
  participant: 'P001', condition: 'closed_loop', trial: 2,
  baseline_start_s: 0, baseline_end_s: 300, intervention_start_s: 300, intervention_end_s: 3000,
  alpha_8_12_power_uv2: 10, theta_power_uv2: 7,
  alpha_8_12_baseline_uv2: 12, alpha_8_12_intervention_uv2: 8, alpha_8_12_change_uv2: -4,
  theta_baseline_uv2: 5, theta_intervention_uv2: 9, theta_change_uv2: 4,
  alpha_baseline_relative: .3, alpha_intervention_relative: .2, alpha_relative_change: -.1,
  theta_baseline_relative: .125, theta_intervention_relative: .225, theta_relative_change: .1,
}

async function openAdmin(page, rows, onSave = () => {}) {
  await page.route('**/api/session-reports**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/experiments/analysis')) return route.fulfill({ json: {
      participants: [], metrics: {}, counts: { participants: 0, complete_participants: 0, sessions: 0, eligible_sessions: 0, failed_sessions: 0 },
    } })
    if (path.endsWith('/experiments/summary')) return route.fulfill({ json: { protocol_analysis_version: 1, storage: '/local', rows } })
    if (path.endsWith('/experiment')) {
      const id = path.split('/').at(-2)
      const label = route.request().postDataJSON()
      onSave(label)
      Object.assign(rows.find(row => row.id === id), label)
      return route.fulfill({ json: { status: 'saved' } })
    }
    const row = rows.find(row => path.endsWith(row.id))
    return route.fulfill({ json: row ? { experiment: row } : [] })
  })
  await page.goto('/')
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('en')
  await page.getByRole('button', { name: 'Administration · Experiments' }).click()
}

test('EEG shifts show phase means, signed changes and percentage points for the selected records', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await openAdmin(page, [measured, { ...measured, id: '2'.repeat(32), condition: 'fixed', trial: 1 }, { ...measured, id: '3'.repeat(32), participant: 'P002' }])
  const section = page.getByRole('region', { name: 'EEG Band Power Shifts' })
  await expect(section.locator('.power-record')).toHaveCount(3)
  await page.getByLabel('Search participant', { exact: true }).fill('p001')
  await expect(section.locator('.power-record')).toHaveCount(2)
  await page.getByRole('checkbox', { name: 'Select record 11111111' }).check()
  await expect(section.locator('.power-record')).toHaveCount(1)
  await expect(section.getByText('Phase power complete', { exact: true })).toBeVisible()
  await expect(section.getByText('0.00–300.00 s', { exact: true })).toBeVisible()
  await expect(section.locator('[data-measure="alpha_8_12"] td')).toHaveText(['12.00', '8.00', '-4.00μV²'])
  await expect(section.locator('[data-measure="theta"] td')).toHaveText(['5.00', '9.00', '+4.00μV²'])
  await expect(section.locator('[data-measure="alpha_relative"] td')).toHaveText(['30.00', '20.00', '-10.00percentage points'])
  await expect(section.locator('[data-measure="theta_relative"] td')).toHaveText(['12.50', '22.50', '+10.00percentage points'])
  await expect(section.getByText('10.00 μV²', { exact: true })).toBeVisible()
  await section.screenshot({ path: '/tmp/terry-eeg-power-desktop.png' })

  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('zh')
  const chinese = page.getByRole('region', { name: '脑电频段功率偏移' })
  await expect(chinese.locator('[data-measure="theta_relative"] td').last()).toHaveText('+10.00百分点')
  await page.setViewportSize({ width: 390, height: 844 })
  await chinese.screenshot({ path: '/tmp/terry-eeg-power-mobile.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  expect(await chinese.locator('table').evaluate(table => table.scrollWidth <= table.clientWidth)).toBeTruthy()
  await page.setViewportSize({ width: 320, height: 720 })
  await page.getByRole('combobox', { name: 'Language / 语言' }).selectOption('en')
  expect(await section.locator('table').evaluate(table => table.scrollWidth <= table.clientWidth)).toBeTruthy()

  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expect(section.locator('.power-record')).toHaveCount(2)
  await page.getByRole('combobox', { name: 'Condition', exact: true }).selectOption('fixed')
  await expect(section.locator('.power-record')).toHaveCount(1)
  await expect(section.locator('.power-record')).toHaveAttribute('data-record-id', '2'.repeat(32))
  await page.getByLabel('Search participant', { exact: true }).fill('no-match')
  await expect(section.getByText('No EEG experiment records match these filters')).toBeVisible()
})

test('EEG shifts preserve missing data and legacy boundaries, distinguish demos and open phase labeling', async ({ page }) => {
  let saved
  const rows = [
    { id: '4'.repeat(32), started_at_s: 1700000000, ended: true, mode: 'brainflow', participant: 'Missing', condition: 'sham' },
    { ...measured, id: '5'.repeat(32), participant: 'Legacy', alpha_power_uv2: 99, alpha_8_12_power_uv2: null,
      alpha_8_12_baseline_uv2: null, alpha_8_12_intervention_uv2: null, alpha_8_12_change_uv2: null,
      alpha_baseline_relative: null, alpha_intervention_relative: null, alpha_relative_change: null },
    { ...measured, id: '6'.repeat(32), participant: 'Zero', theta_change_uv2: 0, theta_intervention_uv2: 5,
      theta_baseline_relative: 0, theta_intervention_relative: 0, theta_relative_change: 0 },
    { ...measured, id: '7'.repeat(32), participant: 'Demo', mode: 'demo' },
  ]
  await openAdmin(page, rows, label => { saved = label })
  const section = page.getByRole('region', { name: 'EEG Band Power Shifts' })
  const record = id => section.locator(`[data-record-id="${id.repeat(32)}"]`)
  await expect(section.locator('.power-record')).toHaveCount(3)
  await expect(record('4').locator('.data-status')).toHaveText('Baseline interval missing · Intervention interval missing · No recorded qualified band power')
  await expect(record('4').locator('tbody td')).toHaveText(Array(12).fill('Not measured'))
  await expect(record('5').locator('.data-status')).toHaveText('Incomplete phase power')
  await expect(record('5').locator('[data-measure="alpha_8_12"] td')).toHaveText(Array(3).fill('Not measured'))
  await expect(record('5')).not.toContainText('99.00')
  await expect(record('6').locator('[data-measure="theta_relative"] td')).toHaveText(['0.00', '0.00', '0.00percentage points'])
  await expect(record('6').locator('[data-measure="theta"] td').last()).toHaveText('0.00μV²')
  await page.getByLabel('Include demo / non-device records').check()
  await expect(section.locator('.power-record')).toHaveCount(4)
  await expect(record('7').locator('.data-status')).toHaveText('Demo / non-device data')

  await record('4').getByRole('button', { name: 'Label phases' }).click()
  await expect(page.getByRole('heading', { name: 'Session Labels · 44444444' })).toBeVisible()
  await page.getByLabel('Baseline start (session s)', { exact: true }).fill('0')
  await page.getByLabel('Baseline end (session s)', { exact: true }).fill('300')
  await page.getByLabel('Intervention start (session s)', { exact: true }).fill('300')
  await page.getByLabel('Intervention end (session s)', { exact: true }).fill('3000')
  await page.getByRole('button', { name: 'Save Labels', exact: true }).click()
  await expect.poll(() => saved?.baseline_start_s).toBe(0)
  expect(saved.intervention_end_s).toBe(3000)
  await expect(record('4').locator('.data-status')).toHaveText('No recorded qualified band power')
  await expect(record('4').locator('tbody td')).toHaveText(Array(12).fill('Not measured'))
})
