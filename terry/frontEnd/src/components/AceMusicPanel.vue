<script setup>
import { onBeforeUnmount, ref } from 'vue'

const api = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const styles = [
  { id: 'ambient', label: '氛围' }, { id: 'piano', label: '钢琴' },
  { id: 'nature', label: '自然' }, { id: 'strings', label: '弦乐' },
  { id: 'electronic', label: '电子' },
]
const style = ref('ambient'), duration = ref(30), description = ref('')
const status = ref(''), error = ref(''), audioUrl = ref('')
function playbackError(event) { error.value = `音频播放失败（媒体错误 ${event.target.error?.code || '未知'}），请检查后端音频接口与 SSH 隧道` }
let pollTimer, active = true, revision = 0

async function generate() {
  const current = ++revision
  clearTimeout(pollTimer)
  error.value = ''; status.value = '正在提交'; audioUrl.value = ''
  try {
    const response = await fetch(`${api}/api/ace/generations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ style: style.value, duration: Number(duration.value), description: description.value }),
    })
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail || '提交失败')
    if (active && current === revision) poll(body.task_id, current)
  } catch (cause) { if (active && current === revision) { error.value = cause.message; status.value = '' } }
}

async function poll(taskId, current) {
  try {
    const response = await fetch(`${api}/api/ace/generations/${encodeURIComponent(taskId)}`, { cache: 'no-store' })
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail || '查询失败')
    if (!active || current !== revision) return
    if (body.status === 'completed') {
      audioUrl.value = `${api}${body.audio_url}`; status.value = '生成完成'
    } else if (body.status === 'failed') {
      throw new Error(body.error || '生成失败')
    } else {
      status.value = body.progress != null ? `生成中 ${Math.round(body.progress * 100)}%` : '排队 / 生成中'
      pollTimer = setTimeout(() => poll(taskId, current), 3000)
    }
  } catch (cause) { if (active && current === revision) { error.value = cause.message; status.value = '' } }
}
onBeforeUnmount(() => { active = false; clearTimeout(pollTimer) })
</script>

<template>
  <section class="ace-music" aria-labelledby="ace-title">
    <h2 id="ace-title">AI 音乐生成</h2>
    <div class="ace-controls">
      <label>风格 <select v-model="style"><option v-for="item in styles" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
      <label>时长 <select v-model="duration"><option :value="30">30 秒</option><option :value="60">60 秒</option><option :value="120">120 秒</option></select></label>
      <label class="ace-description">补充描述 <input v-model="description" maxlength="300" placeholder="可选" /></label>
      <button type="button" class="primary" @click="generate">{{ status && !audioUrl ? '重新生成' : '生成音乐' }}</button>
    </div>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <audio v-if="audioUrl" :src="audioUrl" controls preload="metadata" @error="playbackError" />
  </section>
</template>

<style scoped>
.ace-music { margin: 14px 0; padding: 18px 20px; border-top: 1px solid #d5ded6; border-bottom: 1px solid #d5ded6; }
h2 { font-size: 18px; margin: 0 0 14px; }
.ace-controls { display: flex; align-items: end; gap: 12px; flex-wrap: wrap; }
.ace-controls label { display: grid; gap: 6px; font-size: 13px; }
.ace-description { flex: 1 1 180px; }
.ace-description input { width: 100%; }
audio { display: block; width: min(100%, 560px); margin-top: 12px; }
p { margin: 12px 0 0; font-size: 13px; }
</style>
