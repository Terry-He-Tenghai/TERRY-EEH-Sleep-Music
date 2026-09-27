import { test, expect } from '@playwright/test'
function wav() {
  const rate = 8000, frames = rate * 40, data = Buffer.alloc(44 + frames * 2)
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8); data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22); data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28); data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(frames * 2, 40)
  for (let i = 0; i < frames; i++) data.writeInt16LE(Math.round(Math.sin(i / rate * Math.PI * 2 * 130.81) * 500), 44 + i * 2)
  return data
}
async function setup(page) {
  await page.route(/^https:\/\//, route => route.abort())
  await page.routeWebSocket('**/ws/waveform', ws => ws.send(JSON.stringify({type:'status',sample_rate_hz:250,streaming:false,connected:false,samples_emitted:0})))
  await page.route('**/api/music', route => route.fulfill({ json: {status:'ready',tracks:[{id:'test-pad',title:'Synthetic test pad',available:true}]}}))
  await page.route('**/api/music/test-pad/audio', route => route.fulfill({contentType:'audio/wav',body:wav()}))
  await page.route('**/api/music-workbench/plan?*', route => {
    const state = new URL(route.request().url()).searchParams.get('state')
    route.fulfill({json:{state,notes:state==='M3'?[]:[{start_beat:0,duration_beats:state==='M1'?.5:1,midi_note:72,velocity:44,voice:'melody',phrase:0},{start_beat:0,duration_beats:4,midi_note:48,velocity:42,voice:'bass',phrase:0}]}})
  })
  await page.goto('/')
  return page.locator('#music-workbench')
}
test('real WebAudio manual mixing, phrase switch, edited MIDI and recording download', async ({page}) => {
  const errors=[];page.on('pageerror',error=>errors.push(error.message)); const panel=await setup(page)
  await panel.getByLabel('基础背景 / Pad').selectOption('test-pad')
  await panel.getByLabel('自编旋律动机').fill('72 74 76 77')
  await panel.getByRole('button',{name:'生成 / 更新 MIDI 编排'}).click()
  await expect(panel.getByRole('button',{name:'导出 M1 MIDI'})).toBeEnabled()
  const midiDownload=page.waitForEvent('download');await panel.getByRole('button',{name:'导出 M1 MIDI'}).click();expect((await midiDownload).suggestedFilename()).toBe('terry-M1-edited.mid')
  await panel.getByLabel('已调低设备音量').check();await panel.getByLabel('录制本次实际浏览器混音').check()
  await panel.getByRole('button',{name:'开始同步混音'}).click();await expect(panel.locator('.mode-badge')).toContainText('播放中').catch(async e => { console.log('Workbench diagnostic:', await panel.innerText()); throw e })
  await panel.getByRole('button',{name:'M3 · 极简'}).click();await expect(panel.locator('.state-info')).toContainText('当前 M1 → 目标 M3')
  await expect(panel.locator('.state-info')).toContainText('当前 M3 → 目标 M3',{timeout:20000})
  await panel.getByRole('button',{name:'立即停止',exact:true}).click();await expect(panel.getByRole('button',{name:'下载混音录音'})).toBeEnabled()
  const recordingDownload=page.waitForEvent('download');await panel.getByRole('button',{name:'下载混音录音'}).click();expect((await recordingDownload).suggestedFilename()).toMatch(/terry-manual-mix\./)
  const logDownload=page.waitForEvent('download');await panel.getByRole('button',{name:'导出会话日志'}).click();const stream=await (await logDownload).createReadStream();let text='';for await(const chunk of stream) text+=chunk;const log=JSON.parse(text)
  expect(log.source).toBe('MANUAL');expect(log.events.some(e=>e.type==='state-applied'&&e.state==='M3')).toBe(true);expect(log.pad_sha256).toHaveLength(64);expect(errors).toEqual([])
})
test('phone layout, invalid custom motif and player mutual exclusion',async({page})=>{
  await page.setViewportSize({width:390,height:844});const panel=await setup(page)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await panel.getByLabel('基础背景 / Pad').selectOption('test-pad');await panel.getByLabel('自编旋律动机').fill('72 73 74 76');await panel.getByRole('button',{name:'生成 / 更新 MIDI 编排'}).click();await expect(panel.getByRole('alert')).toContainText('动机')
  await panel.getByLabel('自编旋律动机').fill('72 74 76 77');await panel.getByRole('button',{name:'生成 / 更新 MIDI 编排'}).click();await panel.getByLabel('已调低设备音量').check();await panel.getByRole('button',{name:'开始同步混音'}).click();await expect(panel.locator('.mode-badge')).toContainText('播放中').catch(async e => { console.log('Workbench diagnostic:', await panel.innerText()); throw e })
  const library=page.locator('#music-library');await library.getByRole('combobox').selectOption('test-pad');await library.getByRole('button',{name:'手动播放',exact:true}).click();await expect(panel.locator('.mode-badge')).toContainText('已停止');await library.getByRole('button',{name:'立即停止',exact:true}).click()
})
