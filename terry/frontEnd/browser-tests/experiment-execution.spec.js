import { test, expect } from '@playwright/test'

const channels = ['C3','C4','Cz','FC3','FC4','CP3','CP4','FCz','CPz','Fz','P3','Pz','P4','O1','Oz','O2']
for (const [condition, label] of [['fixed','A · 固定音乐'], ['sham','B · 伪闭环'], ['closed_loop','C · 真闭环']]) {
  test(`${condition}: named subject, locked mode and correct execution request`, async ({page}) => {
    let body
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(() => {
      window.audioContextsCreated = 0
      const Original = window.AudioContext
      window.AudioContext = class extends Original { constructor(...args) { super(...args); window.audioContextsCreated++ } }
    })
    await page.routeWebSocket('**/ws/waveform', () => {})
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/experiments/summary')) return route.fulfill({json:{rows:[],experiment_execution_version:1}})
      if (path.endsWith('/recording-info')) return route.fulfill({json:{raw_recording_version:1}})
      if (path.endsWith('/adaptive/status')) return route.fulfill({json:{type:'adaptive_music',status:'stopped'}})
      if (path.endsWith('/acquisition/start')) {
        body = route.request().postDataJSON()
        return route.fulfill({json:{streaming:true,connected:true,channels,sample_rate_hz:250,experiment:body.experiment,mode:body.mode}})
      }
      if (path.endsWith('/acquisition/stop')) return route.fulfill({json:{streaming:false,channels,sample_rate_hz:250}})
      return route.fulfill({json:[]})
    })
    await page.goto('/')
    await page.getByRole('radio',{name:label,exact:true}).check()
    await page.getByRole('button',{name:'开始采集',exact:true}).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    expect(body).toBeUndefined()
    await page.getByLabel('姓名或编号',{exact:true}).fill('测试受试者甲')
    await page.getByRole('button',{name:'确认',exact:true}).click()
    await expect(page.getByRole('button',{name:'测试受试者甲',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'开始采集',exact:true}).click()
    await expect(page.getByRole('button',{name:'停止采集',exact:true})).toBeVisible()
    expect(body.experiment).toEqual({participant:'测试受试者甲',condition,visit:1})
    expect(body.experiment_duration_s).toBe(2700)
    expect(body.save_raw_data).toBe(true)
    expect(body.music_source).toBe(condition === 'fixed' ? 'external' : 'ace')
    await expect(page.getByRole('radio',{name:label,exact:true})).toBeDisabled()
    if (condition === 'fixed') {
      expect(await page.evaluate(() => window.audioContextsCreated)).toBe(0)
      await expect(page.locator('.ace-auto')).toHaveCount(0)
      expect(body.auto_songeval).toBe(false)
    }
    if (condition === 'sham') expect(body.demo_profile).toBe('model')
    await page.screenshot({path:`/tmp/terry-${condition}-desktop.png`,fullPage:true})
    await page.setViewportSize({width:390,height:844})
    for (const mode of await page.locator('.experiment-modes label').all()) {
      expect((await mode.boundingBox()).height).toBeLessThan(55)
    }
    await page.screenshot({path:`/tmp/terry-${condition}-mobile.png`,fullPage:true})
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button',{name:'停止采集',exact:true}).click()
    await expect(page.getByRole('radio',{name:label,exact:true})).toBeEnabled()
    expect(errors).toEqual([])
  })
}

test('search, condition and multiple selections constrain analysis IDs', async ({page}) => {
  const rows = [
    {id:'a'.repeat(32),participant:'测试甲',condition:'fixed',trial:1},
    {id:'b'.repeat(32),participant:'测试甲',condition:'fixed',trial:2},
    {id:'c'.repeat(32),participant:'测试甲',condition:'sham',trial:1},
    {id:'d'.repeat(32),participant:'测试乙',condition:'closed_loop',trial:1},
  ].map(r => ({...r,started_at_s:1700000000,ended:true,mode:'brainflow',execution_version:1}))
  let analyzed = []
  await page.routeWebSocket('**/ws/waveform', () => {})
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/experiments/summary')) return route.fulfill({json:{rows,storage:'/local',protocol_analysis_version:1}})
    if (url.pathname.endsWith('/experiments/analysis')) {
      analyzed = url.searchParams.getAll('ids')
      return route.fulfill({json:{participants:[],metrics:{},counts:{participants:0,complete_participants:0,sessions:analyzed.filter(Boolean).length,eligible_sessions:0,failed_sessions:0}}})
    }
    if (url.pathname.endsWith(rows[0].id)) return route.fulfill({json:{experiment:{participant:'测试甲',condition:'fixed'}}})
    return route.fulfill({json:[]})
  })
  await page.goto('/')
  await page.getByRole('combobox',{name:'Language / 语言'}).selectOption('en')
  await page.getByRole('button',{name:'Administration · Experiments'}).click()
  await expect.poll(() => analyzed.length).toBe(4)
  await page.getByLabel('Search participant',{exact:true}).fill('测试甲')
  await expect.poll(() => analyzed.length).toBe(3)
  await page.getByLabel('Condition',{exact:true}).selectOption('fixed')
  await expect.poll(() => analyzed.length).toBe(2)
  await page.getByLabel('Select record aaaaaaaa').check()
  await expect.poll(() => analyzed).toEqual([rows[0].id])
  await page.getByLabel('Select record bbbbbbbb').check()
  await expect.poll(() => analyzed).toEqual([rows[0].id,rows[1].id])
  await expect(page.locator('.record-comparison thead th')).toHaveCount(3)
  await page.getByRole('button',{name:'View / Label',exact:true}).first().click()
  await expect(page.getByLabel('Condition actually performed')).toBeDisabled()
  await page.getByLabel('Search participant',{exact:true}).fill('不存在')
  await expect.poll(() => analyzed).toEqual([''])
  await expect(page.getByText('No completed sessions match these filters')).toBeVisible()
})
