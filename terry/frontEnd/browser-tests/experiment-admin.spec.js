import { test, expect } from '@playwright/test'

test('SongEval requires consent and displays native scores separately', async ({page}) => {
  let evaluated = false
  const row = {id:'f'.repeat(32),ended:true,mode:'brainflow',participant:'P001',condition:'fixed',analyzed_audio_seconds:30}
  await page.route('**/api/session-reports**', route => {
    const url = new URL(route.request().url()).pathname
    if (url.endsWith('/songeval')) {
      expect(route.request().postDataJSON()).toEqual({send_audio_to_server:true})
      evaluated = true
      return route.fulfill({status:202,json:{status:'running'}})
    }
    if (url.endsWith('/experiments/analysis')) return route.fulfill({json:cohort()})
    if (url.endsWith('/experiments/summary')) return route.fulfill({json:{songeval_version:1,protocol_analysis_version:1,storage:'/local',rows:[{...row,songeval_status:evaluated?'completed':'unavailable',songeval_musicality:evaluated?3.5:null}]}})
    return route.fulfill({json:[]})
  })
  await page.goto('/')
  await page.getByRole('combobox', {name:'Language / 语言'}).selectOption('en')
  await page.getByRole('button', {name:'Administration · Experiments'}).click()
  const button = page.getByRole('button',{name:'Evaluate SongEval',exact:true})
  await expect(button).toBeDisabled()
  await page.getByLabel('Allow final-mix audio to be sent to the designated server (no EEG / questionnaires)').check()
  await button.click()
  await expect(page.getByRole('cell',{name:'completed',exact:true})).toBeVisible()
  await expect(page.getByRole('cell',{name:'3.50 (n=1)',exact:true})).toBeVisible()
  await expect(page.locator('.song-scores').getByRole('cell',{name:'3.50',exact:true})).toBeVisible()
  await page.locator('.experiment-admin').screenshot({path:'/tmp/terry-songeval-desktop.png'})
  await page.setViewportSize({width:390,height:844})
  await page.locator('.experiment-admin').screenshot({path:'/tmp/terry-songeval-mobile.png'})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

const cohort = () => {
  const conditions = ['fixed', 'sham', 'closed_loop']
  const participants = Array.from({length:10}, (_, i) => ({participant:`P${String(i+1).padStart(3,'0')}`,complete:true,
    conditions:Object.fromEntries(conditions.map((c,j) => [c,{sessions:1,eligible_sessions:1,metrics:{relaxation_vas:3+i/10+j,lseq_gts:null}}]))}))
  const metric = {label:'放松 VAS',unit:'0–10',complete_n:10,groups:Object.fromEntries(conditions.map((c,j)=>[c,{n:10,mean:3.45+j,sd:.3,median:3.45+j}])),
    friedman:{p:.0001},paired:{fixed:{n:10,mean:2,sd:0,p:.0001,p_holm:.0002},sham:{n:10,mean:1,sd:0,p:.0001,p_holm:.0002}}}
  return {participants,metrics:{relaxation_vas:metric,lseq_gts:{...metric,label:'LSEQ GTS',unit:'0–100'}},
    counts:{participants:10,complete_participants:10,sessions:30,eligible_sessions:30,failed_sessions:0}}
}

test('experiment administration filters demos, persists labels and switches language', async ({ page }) => {
  let saved
  const row = { id: 'a'.repeat(32), started_at_s: 1700000000, ended: true, mode: 'brainflow', participant: 'P001', condition: 'fixed', duration_s: 60, qualified_window_ratio: .8, recording_status: 'recording' }
  await page.route('**/api/session-reports**', route => {
    const url = new URL(route.request().url()).pathname
    if (url.endsWith('/experiments/analysis')) return route.fulfill({json:cohort()})
    if (url.endsWith('/experiment')) {
      saved = route.request().postDataJSON()
      return route.fulfill({ json: { status: 'saved' } })
    }
    if (url.endsWith('/experiments/summary')) return route.fulfill({ json: { protocol_analysis_version:1, storage: '/local/session_reports', rows: [row, { ...row, id: 'b'.repeat(32), mode: 'demo' }, { ...row, id: 'c'.repeat(32), condition: 'closed_loop', duration_s: 80 }] } })
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
  await page.getByRole('button', { name: 'View / Label', exact: true }).first().click()
  await page.getByLabel('Participant name or ID').fill('P002')
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

test('ten participant charts, individual comparison, missing outcomes and physiology import', async ({page}) => {
  let imported = ''
  const id = 'd'.repeat(32)
  await page.route('**/api/session-reports**', route => {
    const url = new URL(route.request().url()).pathname
    if (url.endsWith('/experiments/analysis')) return route.fulfill({json:cohort()})
    if (url.endsWith('/experiments/summary')) return route.fulfill({json:{protocol_analysis_version:1,storage:'/local/session_reports',rows:[{id,started_at_s:1700000000,ended:true,mode:'brainflow',participant:'P001',condition:'fixed'}]}})
    if (url.endsWith('/physiology')) {
      imported = route.request().postData()
      expect(route.request().headers()['content-type']).toBe('text/csv')
      return route.fulfill({json:{status:'saved',samples:2}})
    }
    if (url.endsWith(id)) return route.fulfill({json:{experiment:{participant:'P001',condition:'fixed'}}})
    return route.fulfill({json:[]})
  })
  await page.goto('/')
  await page.getByRole('combobox', {name:'Language / 语言'}).selectOption('en')
  await page.getByRole('button', {name:'Administration · Experiments'}).click()
  const chart = page.locator('.protocol-analysis')
  await expect(chart.locator('svg circle')).toHaveCount(30)
  await expect(chart.getByText('<0.001', {exact:true})).toHaveCount(4)
  await page.screenshot({path:'/tmp/terry-cohort-desktop.png',fullPage:true})
  await chart.getByLabel('Comparison', {exact:true}).selectOption('P003')
  await expect(chart.locator('svg circle')).toHaveCount(3)
  await expect(chart.getByRole('rowheader', {name:'P003',exact:true})).toBeVisible()
  await expect(chart.getByRole('heading', {name:/Cohort Statistics/})).toHaveCount(0)
  await chart.getByLabel('Outcome', {exact:true}).selectOption('lseq_gts')
  await expect(chart.getByText('No verified completed data for this outcome')).toBeVisible()
  await chart.getByLabel('Outcome', {exact:true}).selectOption('relaxation_vas')
  await page.getByRole('button', {name:'View / Label',exact:true}).click()
  await page.getByLabel('Import aligned motion CSV').setInputFiles({name:'motion.csv',mimeType:'text/csv',buffer:Buffer.from('time_s,motion\n0,0.1\n1,0.2')})
  await expect.poll(()=>imported).toContain('0,0.1')
  await page.setViewportSize({width:390,height:844})
  await page.screenshot({path:'/tmp/terry-cohort-mobile.png',fullPage:true})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
  expect(await chart.locator('svg').evaluate(svg=>svg.getBoundingClientRect().height)).toBeGreaterThan(100)
})

test('old backend cannot silently discard protocol labels', async ({page}) => {
  let writes = 0
  const id = 'e'.repeat(32)
  await page.route('**/api/session-reports**', route => {
    const url = new URL(route.request().url()).pathname
    if (route.request().method() === 'PUT') { writes++; return route.fulfill({json:{status:'saved'}}) }
    if (url.endsWith('/experiments/analysis')) return route.fulfill({status:404,json:{detail:'Not found'}})
    if (url.endsWith('/experiments/summary')) return route.fulfill({json:{storage:'/local',rows:[{id,started_at_s:1700000000,ended:true,mode:'brainflow',condition:'fixed'}]}})
    if (url.endsWith(id)) return route.fulfill({json:{experiment:{participant:'P001',condition:'fixed'}}})
    return route.fulfill({json:[]})
  })
  await page.goto('/')
  await page.getByRole('combobox', {name:'Language / 语言'}).selectOption('en')
  await page.getByRole('button', {name:'Administration · Experiments'}).click()
  await page.getByRole('button', {name:'View / Label',exact:true}).click()
  await page.getByRole('button', {name:'Save Labels',exact:true}).click()
  await expect(page.getByText('Backend update not loaded; restart after acquisition ends before saving')).toBeVisible()
  expect(writes).toBe(0)
})
