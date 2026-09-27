import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
const { descriptor } = parse(readFileSync(new URL('./HeroSection.vue', import.meta.url), 'utf8'))
function harness() {
  const timers = []
  const context = vm.createContext({ref: value => ({value}), computed: fn => ({get value(){return fn()}}), watch(){}, nextTick:async()=>{}, onMounted(){}, onBeforeUnmount(){}, window:{innerWidth:1200,clearTimeout(){},setTimeout(fn){timers.push(fn);return timers.length}}, document:{body:{style:{}},activeElement:null}})
  vm.runInContext(descriptor.scriptSetup.content.replace(/^import .* from 'vue'\r?\n/m,'') + '\nglobalThis.api={selected,toggleService,displayed,done,typewriter,reducedMotion,video,onMouseMove,onSeeked,configureVideo};',context)
  return {api:context.api,timers,context}
}
test('hero Vue script and template compile',()=>{compileScript(descriptor,{id:'hero'});assert.deepEqual(compileTemplate({source:descriptor.template.content,filename:'HeroSection.vue',id:'hero'}).errors,[])})
test('service pills support multiple selections and toggle off',()=>{const {api}=harness();api.toggleService('Brand');api.toggleService('Digital');assert.equal(api.selected.value.join(','),'Brand,Digital');api.toggleService('Brand');assert.equal(api.selected.value.join(','),'Digital')})
test('typewriter completes and reduced motion shows full headline immediately',()=>{const {api,timers}=harness();api.typewriter();while(timers.length) timers.shift()();assert.equal(api.displayed.value,"we'd love to\nhear from you!");assert.equal(api.done.value,true);api.reducedMotion.value=true;api.typewriter();assert.equal(api.done.value,true);assert.equal(timers.length,0)})
test('desktop scrub clamps, mobile plays muted, reduced motion pauses',()=>{const {api,context}=harness();let plays=0;const player={duration:10,currentTime:0,muted:false,pause(){},play(){plays++;return Promise.resolve()}};api.video.value=player;api.configureVideo();api.onMouseMove({clientX:0});api.onMouseMove({clientX:600});assert.equal(player.currentTime,4);api.onSeeked();api.onMouseMove({clientX:10000});assert.equal(player.currentTime,10);context.window.innerWidth=500;api.configureVideo();assert.equal(player.muted,true);assert.equal(plays,1);api.onMouseMove({clientX:0});assert.equal(player.currentTime,10);api.reducedMotion.value=true;api.configureVideo();assert.equal(player.autoplay,false);assert.equal(plays,1)})
