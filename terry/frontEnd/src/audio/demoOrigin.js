// A scripted showcase is never a model prediction or a LIVE hardware result.
export function isScriptedDemo(event) {
  return event?.source === 'DEMO' && event.playback_mode === 'demo_scripted' && event.demo_scripted === true && event.inference_mode === 'demo_scripted' && event.probability_origin === 'scripted_not_model' && event.state?.status === 'demo_scripted' && event.state.baseline_ready === false
}
export function validateDemoOrigin(event) {
  const marked = event?.playback_mode === 'demo_scripted' || event?.demo_scripted === true || event?.inference_mode === 'demo_scripted' || event?.probability_origin === 'scripted_not_model'
  if (marked && !isScriptedDemo(event)) throw new Error('动态演示必须标为DEMO预设状态，禁止冒充模型或真实脑电结果')
}
