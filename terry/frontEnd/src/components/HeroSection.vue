<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const headline = "we'd love to\nhear from you!"
const displayed = ref('')
const done = ref(false)
const reducedMotion = ref(false)
const menuOpen = ref(false)
const menu = ref(null)
const menuButton = ref(null)
const video = ref(null)
const services = ['Brand', 'Digital', 'Campaign', 'Other']
const selected = ref([])
const selectedText = computed(() => selected.value.join(', '))
const links = [
  { text: 'Labs', href: '#waveform' },
  { text: 'Studio', href: '#music-library' },
  { text: 'Openings', href: '#experiment-roadmap' },
  { text: 'Shop', href: '#music-library' },
]
let timer = 0
let motionQuery
let desktop = false
let lastX = null
let seeking = false
let targetTime = 0
let disposed = false
let previousOverflow = ''

function typewriter(speed = 38, startDelay = 600) {
  window.clearTimeout(timer)
  displayed.value = reducedMotion.value ? headline : ''
  done.value = reducedMotion.value
  if (done.value) return
  let index = 0
  const type = () => {
    if (disposed) return
    displayed.value = headline.slice(0, ++index)
    done.value = index === headline.length
    if (!done.value) timer = window.setTimeout(type, speed)
  }
  timer = window.setTimeout(type, startDelay)
}
function toggleService(service) {
  selected.value = selected.value.includes(service)
    ? selected.value.filter(item => item !== service)
    : [...selected.value, service]
}
function seek() {
  const element = video.value
  if (!element || seeking || !Number.isFinite(element.duration) || element.duration <= 0) return
  const clamped = Math.max(0, Math.min(element.duration, targetTime))
  if (Math.abs(element.currentTime - clamped) < .005) return
  seeking = true
  try { element.currentTime = clamped } catch { seeking = false }
}
function onSeeked() { seeking = false; if (desktop && !reducedMotion.value) seek() }
function onMouseMove(event) {
  if (!desktop || reducedMotion.value || !video.value) return
  const delta = lastX === null ? 0 : event.clientX - lastX
  lastX = event.clientX
  const duration = video.value.duration
  if (!Number.isFinite(duration) || duration <= 0) return
  targetTime = Math.max(0, Math.min(duration, targetTime + delta / Math.max(1, window.innerWidth) * .8 * duration))
  seek()
}
function resetMouse() { lastX = null }
function configureVideo() {
  const element = video.value
  desktop = window.innerWidth >= 1024
  lastX = null
  if (window.innerWidth >= 768) menuOpen.value = false
  if (!element) return
  element.muted = true
  // Autoplay is restricted to this decorative, muted background; never audio.
  if (desktop || reducedMotion.value) {
    element.autoplay = false
    element.pause()
    targetTime = element.currentTime || 0
  } else {
    element.autoplay = true
    try { element.play()?.catch(() => {}) } catch { /* Offline and autoplay denial are harmless. */ }
  }
}
function onMotionChange() {
  reducedMotion.value = motionQuery.matches
  typewriter()
  configureVideo()
}
function closeMenu() { menuOpen.value = false }
function onKeydown(event) {
  if (!menuOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeMenu(); return }
  if (event.key !== 'Tab') return
  const focusable = [menuButton.value, ...Array.from(menu.value?.querySelectorAll('a[href]') || [])].filter(Boolean)
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(menuOpen, async open => {
  if (open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    if (menuOpen.value) menu.value?.querySelector('a')?.focus()
  } else {
    document.body.style.overflow = previousOverflow
    menuButton.value?.focus()
  }
})
onMounted(() => {
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.value = motionQuery.matches
  motionQuery.addEventListener('change', onMotionChange)
  window.addEventListener('resize', configureVideo)
  window.addEventListener('mousemove', onMouseMove)
  document.documentElement.addEventListener('mouseleave', resetMouse)
  document.addEventListener('keydown', onKeydown)
  typewriter()
  configureVideo()
})
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(timer)
  motionQuery?.removeEventListener('change', onMotionChange)
  window.removeEventListener('resize', configureVideo)
  window.removeEventListener('mousemove', onMouseMove)
  document.documentElement.removeEventListener('mouseleave', resetMouse)
  document.removeEventListener('keydown', onKeydown)
  video.value?.pause()
  if (menuOpen.value) document.body.style.overflow = previousOverflow
})
</script>

<template>
  <section class="hero-shell" :class="{ 'reduce-motion': reducedMotion }" aria-label="Mainframe introduction">
    <header class="hero-header">
      <a class="brand" href="#spade-hero" aria-label="Mainframe home" @click="closeMenu">Mainframe<sup>®</sup><span aria-hidden="true">✱</span></a>
      <nav class="desktop-navigation" aria-label="Main navigation">
        <template v-for="(link, index) in links" :key="link.text"><span v-if="index" class="separator" aria-hidden="true">,</span><a :href="link.href">{{ link.text }}</a></template>
      </nav>
      <a class="contact-link" href="#contact">Get in touch</a>
      <button ref="menuButton" type="button" class="menu-button" :class="{ 'is-open': menuOpen }" :aria-expanded="menuOpen" aria-controls="mobile-navigation" :aria-label="menuOpen ? 'Close navigation menu' : 'Open navigation menu'" @click="menuOpen = !menuOpen"><span /><span /><span /></button>
    </header>
    <Transition name="menu">
      <nav v-if="menuOpen" id="mobile-navigation" ref="menu" class="mobile-navigation" aria-label="Mobile navigation">
        <a v-for="link in links" :key="link.text" :href="link.href" @click="closeMenu">{{ link.text }}</a>
        <a href="#contact" @click="closeMenu">Get in touch</a>
      </nav>
    </Transition>
    <div class="hero-background" aria-hidden="true">
      <video ref="video" muted playsinline preload="auto" loop tabindex="-1" @loadedmetadata="configureVideo" @seeked="onSeeked" src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260601_110537_3a579fa0-7bbc-4d94-9d25-0e816c7840f5.mp4" />
    </div>
    <div class="hero-content" :inert="menuOpen || undefined">
      <main id="spade-hero" class="hero-main">
        <h1 class="intro-animate" :aria-label="headline"><span aria-hidden="true">{{ displayed }}<span v-if="!done" class="type-cursor">|</span></span></h1>
        <p class="description intro-animate">Whether you have questions, feedback, <br /> drop us a message and we'll get back to you as soon as possible.</p>
        <div class="services intro-animate">
          <div class="service-heading"><h2>What sort of service?</h2><p>Select all that apply</p></div>
          <div class="service-options" role="group" aria-label="What sort of service? Select all that apply">
            <button v-for="service in services" :key="service" type="button" :class="{ active: selected.includes(service) }" :aria-pressed="selected.includes(service)" @click="toggleService(service)">
              <Transition name="check"><svg v-if="selected.includes(service)" class="check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg></Transition>{{ service }}
            </button>
          </div>
          <div class="selection-feedback" aria-live="polite" aria-atomic="true">
            <Transition name="selection" mode="out-in">
              <div v-if="selected.length" key="selected" class="inquiry-banner"><p>Ready to inquire about: <strong>{{ selectedText }}</strong></p><a href="#contact">Let's Go <span aria-hidden="true">↗</span></a></div>
              <p v-else key="placeholder" class="selection-placeholder">Please click to select services above.</p>
            </Transition>
          </div>
        </div>
      </main>
    </div>
  </section>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
.hero-shell { --font-sans: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; position: relative; display: flex; flex-direction: column; overflow-x: hidden; background: white; color: #171717; font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
.hero-shell ::selection { background: #EAECE9; color: #1C2E1E; }
.hero-shell *, .hero-shell *::before, .hero-shell *::after { box-sizing: border-box; }
.hero-shell a { color: inherit; text-decoration: none; }
.hero-shell button { font: inherit; cursor: pointer; }
.hero-shell a:focus-visible, .hero-shell button:focus-visible { outline: 2px solid #1C2E1E; outline-offset: 6px; }
.hero-header { position: fixed; top: 0; left: 0; right: 0; z-index: 10; padding: 16px 20px; display: flex; justify-content: space-between; align-items: center; background: transparent; }
.brand { display: inline-flex; align-items: center; color: #000 !important; font-size: 21px; line-height: 26px; letter-spacing: -1px; font-weight: 500; }
.brand sup { font-size: 12px; align-self: flex-start; margin: -2px 0 0 1px; letter-spacing: 0; }
.brand > span { font-size: 29px; margin-left: 13px; }
.desktop-navigation { display: none; }
.contact-link { display: none; font-size: 23px; text-decoration: underline !important; text-underline-offset: 5px; }
.menu-button { display: flex; flex-direction: column; justify-content: center; gap: 5px; width: 44px; height: 44px; padding: 10px; background: none; border: 0; }
.menu-button span { width: 24px; height: 2px; background: #000; transition: transform .25s ease, opacity .25s ease; }
.menu-button.is-open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
.menu-button.is-open span:nth-child(2) { opacity: 0; }
.menu-button.is-open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
.mobile-navigation { position: fixed; inset: 0; z-index: 9; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 24px; background: rgb(255 255 255 / 95%); backdrop-filter: blur(12px); font-size: 32px; }
.mobile-navigation a:hover, .desktop-navigation a:hover, .contact-link:hover { opacity: .6; }
.hero-background { order: 2; position: relative; overflow: hidden; pointer-events: none; width: 100%; aspect-ratio: 1; background: #fafafa; }
.hero-background video { width: 100%; height: 100%; object-fit: cover; object-position: right; display: block; }
.hero-content { position: relative; z-index: 1; display: flex; flex-direction: column; order: 1; width: 100%; background: white; padding-bottom: 32px; }
.hero-main { max-width: 1280px; width: 100%; margin: 0 auto; padding: 120px 24px 48px; flex: 1; display: flex; flex-direction: column; justify-content: center; scroll-margin-top: 80px; }
h1 { font-size: 48px; font-weight: 400; letter-spacing: -.045em; line-height: 1.08; margin: 0 0 32px; white-space: pre-wrap; min-height: 2.16em; }
.type-cursor { display:inline-block; width:2px; height:1.1em; background:#000; vertical-align:middle; margin-left:2px; font-size:0; animation: blink 1s step-end infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.description { font-size: 18px; line-height: 1.65; color: #5A635A; margin: 0 0 56px; max-width: 672px; animation-delay: .1s !important; }
.services { width: 100%; max-width: 650px; animation-delay: .2s !important; }
.service-heading { margin-bottom:32px; }
.service-heading h2 { font-size:24px; font-weight:500; letter-spacing:-.025em; margin:0 0 8px; }
.service-heading p { font-size:14px; color:#738273; opacity:.85; margin:0; }
.service-options { display: flex; flex-wrap: wrap; gap: 10px; }
.service-options button { display: inline-flex; justify-content: center; align-items: center; gap: 9px; min-height: 48px; padding: 12px 24px; border: 1px solid #F1F3F1; border-radius: 999px; color: #1C2E1E; background: white; transition: background .2s, color .2s, box-shadow .2s, transform .2s; }
.service-options button:hover { background: #f5f6f3; transform: translateY(-2px); }
.service-options button:active { transform: scale(.97); }
.service-options button.active { background: #1C2E1E; color: white; border-color: #1C2E1E; box-shadow: 0 4px 12px rgb(28 46 30 / 12%); }
.check { height: 16px; width: 16px; flex-shrink: 0; }
.check-enter-active, .check-leave-active { transition: transform .35s cubic-bezier(.34,1.56,.64,1), opacity .2s, width .25s; }
.check-enter-from, .check-leave-to { transform: scale(0); opacity: 0; width: 0; }
.selection-feedback { margin-top: 24px; min-height: 86px; }
.selection-placeholder { font-size: 12px; font-style: italic; opacity: .5; margin: 0; padding: 18px 0; }
.inquiry-banner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; background: #FAFBF9; border: 1px solid #edf0e9; border-radius: 16px; padding: 18px 20px; }
.inquiry-banner p { margin: 0; font-size: 13px; color: #5A635A; }
.inquiry-banner strong { color: #1C2E1E; font-weight: 500; }
.inquiry-banner a { display:inline-flex; align-items:center; gap:12px; white-space:nowrap; font-size:12px; text-transform:uppercase; color:#4D6D47; padding:8px 0; }
.intro-animate { animation: intro .6s both; }
@keyframes intro { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.selection-enter-active, .selection-leave-active { transition: opacity .18s ease, transform .18s ease; }
.selection-enter-from, .selection-leave-to { opacity: 0; transform: translateY(5px); }
.menu-enter-active, .menu-leave-active { transition: opacity .2s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; }
@media (min-width: 640px) { .hero-header { padding: 20px 32px; } .brand { font-size: 26px; line-height: 32px; } .brand sup { font-size: 13px; } }
@media (min-width: 768px) { .desktop-navigation { display: flex; position: absolute; left: 50%; transform: translateX(-50%); align-items: baseline; font-size: 23px; letter-spacing: -.7px; } .separator { margin-right: 6px; } .contact-link { display: block; } .menu-button, .mobile-navigation { display: none; } .hero-background { aspect-ratio: 16 / 9; } h1 { font-size: 60px; } .description { font-size: 20px; } }
@media (min-width: 1024px) { .hero-shell { display: block; min-height: 100vh; } .hero-background { order: 0; position: absolute; inset: 0; z-index: 0; aspect-ratio: auto; height: 100%; background: transparent; } .hero-background video { object-position: right bottom; } .hero-content { order: 0; z-index: 1; min-height: 100vh; padding-bottom: 0; background: transparent; } .hero-main { padding: 120px 24px 48px; } h1 { font-size: 76px; } }
@media (prefers-reduced-motion: reduce) { .hero-shell *, .hero-shell *::before, .hero-shell *::after { animation: none !important; transition: none !important; } }
.reduce-motion *, .reduce-motion *::before, .reduce-motion *::after { animation: none !important; transition: none !important; }
</style>
