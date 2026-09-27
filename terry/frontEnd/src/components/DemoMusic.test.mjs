import test from 'node:test'
import assert from 'node:assert/strict'
import { validateStemFrame } from '../audio/stemEngine.js'
import { normalizeAdaptiveEvent, validateAdaptiveEvent } from '../audio/adaptiveEngine.js'
function frame(source='DEMO') {
  return { type:'adaptive_music',session_id:1,sequence:1,source,status:'ready',emitted_at_s:Date.now()/1000,
    playback_mode:'demo_scripted',demo_scripted:true,inference_mode:'demo_scripted',probability_origin:'scripted_not_model',demo_stage:'W',
    state:{status:'demo_scripted',baseline_ready:false},probabilities:{W:.94,N1:.04,N2:.02},signal_quality:1,
    current_music_state:'M1',target_music_state:'M1',selected_track:{id:'Track00008'},bpm:60,phrase_beats:16,notes:[],gains:{master:.18},
    stem_mix:{track_id:'Track00008',mode:'demo_scripted',control_level:.9,brightness:.7,transition_seconds:3,gains:{piano:.7,strings:.1,bass:.3,pad:.1}} }
}
test('scripted demo is explicit and accepted by both audio paths',()=>{
  assert.equal(validateStemFrame(frame(),'Track00008').mode,'demo_scripted')
  validateAdaptiveEvent(normalizeAdaptiveEvent(frame()))
})
test('scripted results can never be presented as LIVE model results',()=>{
  for(const mutate of [e=>{e.source='LIVE'},e=>{e.demo_scripted=false},e=>{e.probability_origin='model'},e=>{e.state.status='ok'}]) {
    const e=frame(); mutate(e)
    assert.throws(()=>validateStemFrame(e,'Track00008'))
    assert.throws(()=>validateAdaptiveEvent(normalizeAdaptiveEvent(e)))
  }
})
