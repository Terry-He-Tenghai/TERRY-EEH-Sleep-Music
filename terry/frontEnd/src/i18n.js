import { ref } from 'vue'

export const language = ref(localStorage.getItem('terry-language') === 'en' ? 'en' : 'zh')
export const text = (zh, en) => language.value === 'en' ? en : zh
export function setLanguage(value) {
  language.value = value === 'en' ? 'en' : 'zh'
  localStorage.setItem('terry-language', language.value)
  document.documentElement.lang = language.value === 'en' ? 'en' : 'zh-CN'
}
setLanguage(language.value)
