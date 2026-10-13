<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { text as t } from '../i18n.js'

const apiBase = import.meta.env.VITE_API_BASE || ''

const host = ref('connect.nmb2.seetacloud.com')
const port = ref(20389)
const username = ref('root')
const password = ref('')
const remotePort = ref(8001)
const localPort = ref(8001)

const status = ref({ stage: 'idle', message: '未启动', log: [], tunnel_pid: null, server_pid: null })
const starting = ref(false)
const error = ref('')

let pollTimer = null

async function startServer() {
  if (starting.value || !host.value || !username.value || !password.value) {
    error.value = t('请填写完整的 SSH 连接信息', 'Please fill in complete SSH connection info')
    return
  }
  
  error.value = ''
  starting.value = true
  
  try {
    const response = await fetch(`${apiBase}/api/ace-server/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: host.value,
        port: Number(port.value),
        username: username.value,
        password: password.value,
        remote_port: Number(remotePort.value),
        local_port: Number(localPort.value)
      })
    })
    
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail || t('启动失败', 'Start failed'))
    
    status.value = body
    startPolling()
  } catch (err) {
    error.value = err.message
    starting.value = false
  }
}

async function stopServer() {
  try {
    const response = await fetch(`${apiBase}/api/ace-server/stop`, { method: 'POST' })
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail || t('停止失败', 'Stop failed'))
    status.value = body
    stopPolling()
    starting.value = false
  } catch (err) {
    error.value = err.message
  }
}

async function refreshStatus() {
  try {
    const response = await fetch(`${apiBase}/api/ace-server/status`)
    if (!response.ok) return
    const body = await response.json()
    status.value = body
    starting.value = !['idle', 'ready', 'error'].includes(body.stage)
    
    if (body.stage === 'ready' || body.stage === 'error') {
      stopPolling()
    }
  } catch (err) {
    console.error('Failed to refresh status:', err)
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(refreshStatus, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  refreshStatus()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="ace-server-panel panel">
    <div class="panel-header">
      <h2>{{ t('ACE-Step 远程服务器启动', 'ACE-Step Remote Server') }}</h2>
      <div class="status-badge" :class="status.stage">
        {{ status.message }}
      </div>
    </div>
    
    <p class="panel-intro">
      {{ t('自动连接远程服务器、检查项目完整性、下载缺失模型、启动服务并建立本地隧道。', 
          'Automatically connect to remote server, check project integrity, download missing models, start service and establish local tunnel.') }}
    </p>
    
    <form class="server-form" @submit.prevent="startServer">
      <div class="form-row">
        <div class="form-field">
          <label for="ssh-host">{{ t('服务器地址', 'Host') }}</label>
          <input id="ssh-host" v-model="host" :disabled="starting" required />
        </div>
        <div class="form-field">
          <label for="ssh-port">{{ t('SSH 端口', 'SSH Port') }}</label>
          <input id="ssh-port" v-model.number="port" type="number" min="1" max="65535" :disabled="starting" required />
        </div>
      </div>
      
      <div class="form-row">
        <div class="form-field">
          <label for="ssh-username">{{ t('用户名', 'Username') }}</label>
          <input id="ssh-username" v-model="username" :disabled="starting" required />
        </div>
        <div class="form-field">
          <label for="ssh-password">{{ t('密码', 'Password') }}</label>
          <input id="ssh-password" v-model="password" type="password" :disabled="starting" required autocomplete="off" />
        </div>
      </div>
      
      <div class="form-row">
        <div class="form-field">
          <label for="remote-port">{{ t('远程端口', 'Remote Port') }}</label>
          <input id="remote-port" v-model.number="remotePort" type="number" min="1024" max="65535" :disabled="starting" />
        </div>
        <div class="form-field">
          <label for="local-port">{{ t('本地端口', 'Local Port') }}</label>
          <input id="local-port" v-model.number="localPort" type="number" min="1024" max="65535" :disabled="starting" />
        </div>
      </div>
      
      <div class="form-actions">
        <button v-if="status.stage === 'idle' || status.stage === 'error'" type="submit" class="primary" :disabled="starting">
          {{ starting ? t('启动中...', 'Starting...') : t('连接并启动', 'Connect & Start') }}
        </button>
        <button v-else-if="status.stage === 'ready'" type="button" class="secondary" @click="stopServer">
          {{ t('停止服务', 'Stop Service') }}
        </button>
        <button v-else type="button" class="secondary" disabled>
          {{ t('处理中...', 'Processing...') }}
        </button>
      </div>
    </form>
    
    <div v-if="status.log.length > 0" class="server-log">
      <h3>{{ t('操作日志', 'Operation Log') }}</h3>
      <div class="log-content">
        <p v-for="(line, index) in status.log" :key="index">{{ line }}</p>
      </div>
    </div>
    
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    
    <details class="server-notes">
      <summary>{{ t('使用说明', 'Usage Notes') }}</summary>
      <ul>
        <li>{{ t('首次连接新服务器会自动克隆代码并下载基础模型（Turbo、VAE、文本编码器、1.7B LM）。', 
                'First connection to a new server will automatically clone code and download base models (Turbo, VAE, text encoder, 1.7B LM).') }}</li>
        <li>{{ t('占用端口的进程会被自动终止后重新启动。', 
                'Processes occupying ports will be automatically terminated and restarted.') }}</li>
        <li>{{ t('SSH 密码仅用于本次连接，不会保存到本地。', 
                'SSH password is only used for this connection and will not be saved locally.') }}</li>
        <li>{{ t('服务启动后可在本地 http://127.0.0.1:8001 访问 ACE-Step API。', 
                'After service starts, access ACE-Step API at http://127.0.0.1:8001.') }}</li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.ace-server-panel {
  padding: 24px;
  margin: 20px 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}

.status-badge {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
}

.status-badge.idle {
  background: #e5e9e2;
  color: #738273;
}

.status-badge.connecting,
.status-badge.checking,
.status-badge.installing,
.status-badge.starting,
.status-badge.tunneling {
  background: #fff0ca;
  color: #755315;
}

.status-badge.ready {
  background: #f1f7f0;
  color: #346540;
}

.status-badge.error {
  background: #fff5f3;
  color: #a13434;
}

.panel-intro {
  color: #586955;
  font-size: 14px;
  line-height: 1.7;
  margin: 0 0 20px;
}

.server-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-field label {
  font-size: 13px;
  font-weight: 600;
  color: #30482b;
}

.form-field input {
  padding: 10px 12px;
  border: 1px solid #cddac7;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}

.form-field input:disabled {
  background: #eef1ec;
  color: #6a7665;
  cursor: not-allowed;
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.form-actions button {
  padding: 11px 18px;
  border: 1px solid #dfe5dc;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.form-actions .primary {
  background: #1c2e1e;
  color: #fff;
  border-color: #1c2e1e;
}

.form-actions .primary:hover:not(:disabled) {
  background: #2d3f2f;
}

.form-actions .secondary {
  background: #fff;
  color: #1c2e1e;
}

.form-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.server-log {
  margin-top: 24px;
  padding: 16px;
  background: #fafbf9;
  border: 1px solid #e4e9e2;
  border-radius: 12px;
}

.server-log h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 12px;
}

.log-content {
  max-height: 300px;
  overflow-y: auto;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #3d4f39;
}

.log-content p {
  margin: 4px 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.server-notes {
  margin-top: 20px;
  font-size: 13px;
}

.server-notes summary {
  cursor: pointer;
  font-weight: 600;
  color: #36582a;
  margin-bottom: 8px;
}

.server-notes ul {
  margin: 12px 0 0;
  padding-left: 20px;
  line-height: 1.8;
  color: #52634c;
}

.server-notes li + li {
  margin-top: 6px;
}

.error-message {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fff5f2;
  border: 1px solid #eccac4;
  border-radius: 10px;
  color: #a13434;
  font-size: 14px;
}

@media (max-width: 700px) {
  .ace-server-panel {
    padding: 18px;
  }
  
  .form-row {
    grid-template-columns: 1fr;
    gap: 14px;
  }
  
  .panel-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
