import { ref } from 'vue'

export const language = ref(globalThis.localStorage?.getItem('terry-language') === 'en' ? 'en' : 'zh')
export const text = (zh, en) => language.value === 'en' ? en : zh
export function setLanguage(value) {
  language.value = value === 'en' ? 'en' : 'zh'
  globalThis.localStorage?.setItem('terry-language', language.value)
  if (globalThis.document) document.documentElement.lang = language.value === 'en' ? 'en' : 'zh-CN'
}
export function labels(zh, en) {
  return new Proxy(zh, { get: (target, key) => text(target[key], en[key] ?? target[key]) })
}
setLanguage(language.value)
