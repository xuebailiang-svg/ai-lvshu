<template>
  <div class="evaluate-view">
    <!-- 左侧会话列表 -->
    <div class="session-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">💬 选址对话</span>
        <el-button type="primary" size="small" :icon="Plus" @click="createNewSession">新对话</el-button>
      </div>
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="session-item"
          :class="{ active: currentSessionId === session.session_id }"
          @click="loadSession(session.session_id)"
        >
          <div class="session-title">{{ session.title || '新对话' }}</div>
          <div class="session-meta">{{ session.message_count }} 条消息 · {{ formatTime(session.last_message_at) }}</div>
        </div>
        <div v-if="sessions.length === 0" class="no-sessions">
          <div style="color:#666;font-size:13px;text-align:center;padding:20px">暂无对话记录</div>
        </div>
      </div>
    </div>

    <!-- 主对话区域 -->
    <div class="chat-main">
      <!-- 顶部工具栏 -->
      <div class="chat-toolbar">
        <div class="toolbar-left">
          <span class="chat-title">🎮 电竞馆智能选址顾问</span>
          <el-tag size="small" type="success" style="margin-left:8px">AI 驱动</el-tag>
        </div>
        <div class="toolbar-right">
          <el-button size="small" @click="showPreferences = true">⚙️ 偏好设置</el-button>
          <el-button size="small" @click="showWorkflowLog = !showWorkflowLog">
            {{ showWorkflowLog ? '隐藏' : '显示' }}工作流日志
          </el-button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="message-list" ref="messageListRef">
        <!-- 欢迎消息 -->
        <div v-if="messages.length === 0" class="welcome-screen">
          <div class="welcome-icon">🏆</div>
          <div class="welcome-title">电竞馆智能选址顾问</div>
          <div class="welcome-desc">我可以帮你分析选址方案、评估地址潜力、参考历史经验，让每一次开店决策都有数据支撑。</div>
          <div class="quick-questions">
            <div class="quick-title">快速提问：</div>
            <div class="quick-grid">
              <div v-for="q in quickQuestions" :key="q" class="quick-item" @click="sendQuickQuestion(q)">{{ q }}</div>
            </div>
          </div>
        </div>

        <!-- 消息气泡 -->
        <div v-for="(msg, idx) in messages" :key="idx" class="message-wrapper" :class="`role-${msg.role}`">
          <div class="message-avatar">
            <span v-if="msg.role === 'user'">👤</span>
            <span v-else>🤖</span>
          </div>
          <div class="message-content">
            <div class="message-bubble" :class="msg.role">
              <div v-if="msg.role === 'assistant'" class="message-text markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div v-else class="message-text">{{ msg.content }}</div>
            </div>
            <!-- 推荐追问问题 -->
            <div v-if="msg.role === 'assistant' && msg.suggestions && msg.suggestions.length > 0" class="suggestions-area">
              <div class="suggestions-label">💬 您可能还想问：</div>
              <div class="suggestions-chips">
                <div
                  v-for="q in msg.suggestions"
                  :key="q"
                  class="suggestion-chip"
                  @click="sendSuggestion(q)"
                >{{ q }}</div>
              </div>
            </div>
            <div class="message-meta">
              <span class="message-time">{{ formatTime(msg.created_at) }}</span>
              <span
                v-if="msg.role === 'assistant' && msg.content"
                class="copy-btn"
                @click="copyMessage(msg.content)"
              >复制</span>
            </div>
          </div>
        </div>

        <!-- 正在生成 -->
        <div v-if="generating" class="message-wrapper role-assistant">
          <div class="message-avatar"><span>🤖</span></div>
          <div class="message-content">
            <div class="message-bubble assistant">
              <div class="message-text generating-text">
                <span v-if="streamingContent" v-html="renderMarkdown(streamingContent)"></span>
                <span v-else class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="address-hint" v-if="addressMode">
          <el-tag closable @close="addressMode = false; evaluateAddress = ''">
            📍 评估地址：{{ evaluateAddress }}
          </el-tag>
        </div>
        <div class="input-row">
          <el-button size="small" :icon="Location" @click="showAddressInput = !showAddressInput" title="指定评估地址" />
          <el-input
            v-model="inputMessage"
            :placeholder="addressMode ? `正在评估「${evaluateAddress}」，请输入你的问题...` : '输入你的选址问题，如：西安小寨附近适合开电竞馆吗？'"
            :rows="2"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            :loading="generating"
            :disabled="!inputMessage.trim()"
            @click="sendMessage"
          />
        </div>
        <div v-if="showAddressInput" class="address-input-row">
          <el-input v-model="evaluateAddress" placeholder="输入具体地址（可选）" size="small" style="flex:1" />
          <el-button size="small" type="primary" @click="applyAddress">确认地址</el-button>
        </div>
        <div class="input-hint">按 Enter 发送 · Shift+Enter 换行 · 越用越聪明，历史对话会被记忆</div>
      </div>
    </div>

    <!-- 右侧工作流日志 -->
    <div v-if="showWorkflowLog" class="workflow-sidebar">
      <div class="workflow-header">
        <span>⚡ Agent 工作流</span>
        <el-button :icon="Close" circle size="small" @click="showWorkflowLog = false" />
      </div>
      <div class="workflow-steps" ref="workflowRef">
        <div v-if="workflowSteps.length === 0" class="no-workflow">
          <div style="color:#666;font-size:12px;text-align:center;padding:20px">发送消息后，这里将显示 Agent 的思考过程</div>
        </div>
        <div v-for="(step, idx) in workflowSteps" :key="idx" class="workflow-step" :class="`step-${step.log_type}`">
          <span class="step-icon">{{ stepIcons[step.log_type] || '•' }}</span>
          <div class="step-body">
            <span class="step-name">[{{ step.step }}]</span>
            <span class="step-msg">{{ step.message }}</span>
          </div>
        </div>
        <div v-if="generating" class="workflow-step step-thinking">
          <span class="step-icon">⏳</span>
          <div class="step-body"><span class="step-msg">处理中...</span></div>
        </div>
      </div>
    </div>

    <!-- 偏好设置对话框 -->
    <el-dialog v-model="showPreferences" title="⚙️ 选址偏好设置（程序记忆）" width="500px">
      <div class="preferences-panel">
        <el-alert title="偏好设置会被永久记忆，影响每次 AI 回答的侧重点" type="info" :closable="false" style="margin-bottom:16px" />
        <div v-for="pref in preferences" :key="pref.key" class="pref-item">
          <div class="pref-key">{{ pref.description || pref.key }}</div>
          <div class="pref-value">{{ pref.value }}</div>
        </div>
        <el-divider v-if="preferences.length > 0" />
        <div class="add-pref">
          <div class="add-pref-title">添加新偏好</div>
          <el-form :model="newPref" size="small">
            <el-form-item label="偏好说明">
              <el-input v-model="newPref.description" placeholder="如：偏重大学城周边选址" />
            </el-form-item>
            <el-form-item label="偏好内容">
              <el-input v-model="newPref.value" placeholder="如：优先考虑大学城、高校聚集区域" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="优先级">
              <el-slider v-model="newPref.priority" :min="1" :max="10" show-stops />
            </el-form-item>
            <el-button type="primary" size="small" @click="addPreference">保存偏好</el-button>
          </el-form>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Location, Promotion, Close, ChatDotRound, Setting } from '@element-plus/icons-vue'
import api from '@/api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 配置 marked
marked.setOptions({ breaks: true, gfm: true })

const sessions = ref<any[]>([])
const currentSessionId = ref<string | null>(null)
const messages = ref<any[]>([])
const inputMessage = ref('')
const generating = ref(false)
const streamingContent = ref('')
const showWorkflowLog = ref(true)
const workflowSteps = ref<any[]>([])
const workflowRef = ref<HTMLElement | null>(null)
const messageListRef = ref<HTMLElement | null>(null)
const showPreferences = ref(false)
const preferences = ref<any[]>([])
const showAddressInput = ref(false)
const evaluateAddress = ref('')
const addressMode = ref(false)
const newPref = ref({ description: '', value: '', priority: 5 })

const stepIcons: Record<string, string> = {
  thinking: '🤔', executing: '⚡', result: '✅', warning: '⚠️', error: '❌', final: '🎯'
}

const quickQuestions = [
  '西安小寨路附近适合开电竞馆吗？',
  '如何评估一个地址的竞品压力？',
  '电竞馆选址最重要的三个因素是什么？',
  '什么样的商圈消费能力最强？',
  '租金和营收的合理比例是多少？',
  '我们历史上哪些门店表现最好？',
]

async function loadSessions() {
  try {
    const res: any = await api.get('/chat/sessions')
    sessions.value = Array.isArray(res) ? res : (res?.data || [])
  } catch { sessions.value = [] }
}

async function createNewSession() {
  try {
    const res: any = await api.post('/chat/sessions')
    currentSessionId.value = res?.session_id || res?.data?.session_id
    messages.value = []
    workflowSteps.value = []
    await loadSessions()
  } catch {}
}

async function loadSession(sessionId: string) {
  currentSessionId.value = sessionId
  workflowSteps.value = []
  try {
    const res: any = await api.get(`/chat/sessions/${sessionId}/messages`)
    messages.value = Array.isArray(res) ? res : (res?.data || [])
    await nextTick()
    scrollToBottom()
  } catch {}
}

async function sendMessage() {
  if (!inputMessage.value.trim() || generating.value) return
  if (!currentSessionId.value) {
    const res: any = await api.post('/chat/sessions')
    currentSessionId.value = res?.session_id || res?.data?.session_id
  }
  const userMsg = inputMessage.value.trim()
  inputMessage.value = ''
  streamingContent.value = ''
  workflowSteps.value = []
  generating.value = true
  messages.value.push({ role: 'user', content: userMsg, created_at: new Date().toISOString() })
  await nextTick()
  scrollToBottom()

  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        session_id: currentSessionId.value,
        message: userMsg,
        address: addressMode.value ? evaluateAddress.value : undefined,
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let assistantContent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6).trim()
        try {
          const event = JSON.parse(data)
          if (event.type === 'log') {
            workflowSteps.value.push(event)
            await nextTick()
            if (workflowRef.value) workflowRef.value.scrollTop = workflowRef.value.scrollHeight
          } else if (event.type === 'token') {
            assistantContent += event.content
            streamingContent.value = assistantContent
            await nextTick()
            scrollToBottom()
          } else if (event.type === 'suggestions') {
            // 将推荐问题附加到最后一条 assistant 消息
            const lastAssistant = messages.value.filter(m => m.role === 'assistant').slice(-1)[0]
            if (lastAssistant) lastAssistant.suggestions = event.questions
          } else if (event.type === 'done') {
            if (!messages.value.find(m => m.role === 'assistant' && m.content === assistantContent)) {
              messages.value.push({ role: 'assistant', content: assistantContent, created_at: new Date().toISOString(), suggestions: [] })
            }
            streamingContent.value = ''
            generating.value = false
            await loadSessions()
            await nextTick()
            scrollToBottom()
          }
        } catch {}
      }
    }
  } catch (e: any) {
    ElMessage.error('发送失败：' + (e.message || '未知错误'))
    generating.value = false
    streamingContent.value = ''
  }
}

function sendQuickQuestion(q: string) { inputMessage.value = q; sendMessage() }

async function sendSuggestion(q: string) { inputMessage.value = q; await sendMessage() }
function applyAddress() { if (evaluateAddress.value.trim()) { addressMode.value = true; showAddressInput.value = false } }

async function loadPreferences() {
  try { const res: any = await api.get('/chat/memory/preferences'); preferences.value = Array.isArray(res) ? res : (res?.data || []) } catch { preferences.value = [] }
}

async function addPreference() {
  if (!newPref.value.description || !newPref.value.value) { ElMessage.warning('请填写偏好说明和内容'); return }
  try {
    await api.post('/chat/memory/preferences', { key: `pref_${Date.now()}`, value: newPref.value.value, description: newPref.value.description, priority: newPref.value.priority })
    ElMessage.success('偏好已保存')
    newPref.value = { description: '', value: '', priority: 5 }
    await loadPreferences()
  } catch {}
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    const raw = marked.parse(text) as string
    return DOMPurify.sanitize(raw)
  } catch {
    return text.replace(/\n/g, '<br>')
  }
}

async function copyMessage(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function formatTime(timeStr: string | null): string {
  if (!timeStr) return ''
  const d = new Date(timeStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString()
}

function scrollToBottom() {
  if (messageListRef.value) messageListRef.value.scrollTop = messageListRef.value.scrollHeight
}

onMounted(async () => {
  await loadSessions()
  await loadPreferences()
  if (sessions.value.length > 0) await loadSession(sessions.value[0].session_id)
})
</script>

<style scoped>
.evaluate-view { display: flex; height: calc(100vh - 60px); background: #0a0a1e; overflow: hidden; }
.session-sidebar { width: 240px; background: rgba(15,15,35,0.98); border-right: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; flex-shrink: 0; }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 12px; border-bottom: 1px solid rgba(255,255,255,0.08); }
.sidebar-title { font-size: 13px; font-weight: 600; color: #e0e0ff; }
.session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; transition: background 0.2s; }
.session-item:hover { background: rgba(255,255,255,0.06); }
.session-item.active { background: rgba(64,158,255,0.15); border: 1px solid rgba(64,158,255,0.3); }
.session-title { font-size: 13px; color: #ddd; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-meta { font-size: 11px; color: #666; margin-top: 3px; }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.chat-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 10px 20px; border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(15,15,35,0.8); flex-shrink: 0; }
.toolbar-left { display: flex; align-items: center; }
.chat-title { font-size: 15px; font-weight: 600; color: #e0e0ff; }
.toolbar-right { display: flex; gap: 8px; }
.message-list { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.welcome-screen { display: flex; flex-direction: column; align-items: center; justify-content: center; flex: 1; text-align: center; padding: 40px 20px; }
.welcome-icon { font-size: 56px; margin-bottom: 16px; }
.welcome-title { font-size: 22px; font-weight: 700; color: #e0e0ff; margin-bottom: 10px; }
.welcome-desc { font-size: 14px; color: #888; max-width: 480px; line-height: 1.7; margin-bottom: 32px; }
.quick-questions { width: 100%; max-width: 560px; }
.quick-title { font-size: 12px; color: #666; margin-bottom: 12px; }
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.quick-item { padding: 12px 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; font-size: 13px; color: #ccc; cursor: pointer; text-align: left; transition: all 0.2s; }
.quick-item:hover { background: rgba(64,158,255,0.15); border-color: rgba(64,158,255,0.4); color: #409eff; }
.message-wrapper { display: flex; gap: 12px; align-items: flex-start; }
.message-wrapper.role-user { flex-direction: row-reverse; }
.message-avatar { width: 36px; height: 36px; border-radius: 50%; background: rgba(255,255,255,0.08); display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.message-content { max-width: 70%; }
.message-bubble { padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.7; }
.message-bubble.user { background: rgba(64,158,255,0.2); border: 1px solid rgba(64,158,255,0.3); color: #e0e0ff; border-top-right-radius: 4px; }
.message-bubble.assistant { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: #ddd; border-top-left-radius: 4px; }
/* Markdown 渲染样式 */
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { color: #c0b8ff; margin: 10px 0 5px; font-weight: 600; }
.markdown-body :deep(h2) { font-size: 15px; border-bottom: 1px solid rgba(108,99,255,0.2); padding-bottom: 4px; }
.markdown-body :deep(h3) { font-size: 14px; }
.markdown-body :deep(strong) { color: #a0d4ff; font-weight: 600; }
.markdown-body :deep(em) { color: #c0b8ff; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 20px; margin: 5px 0; }
.markdown-body :deep(li) { margin: 3px 0; }
.markdown-body :deep(p) { margin: 5px 0; }
.markdown-body :deep(code) { background: rgba(108,99,255,0.15); border: 1px solid rgba(108,99,255,0.2); padding: 1px 5px; border-radius: 4px; font-size: 12px; color: #a0d4ff; }
.markdown-body :deep(pre) { background: rgba(0,0,0,0.3); border: 1px solid rgba(108,99,255,0.2); border-radius: 6px; padding: 10px; overflow-x: auto; margin: 6px 0; }
.markdown-body :deep(pre code) { background: none; border: none; padding: 0; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 12px; }
.markdown-body :deep(th) { background: rgba(108,99,255,0.2); color: #c0b8ff; padding: 5px 8px; border: 1px solid rgba(108,99,255,0.2); text-align: left; }
.markdown-body :deep(td) { padding: 4px 8px; border: 1px solid rgba(255,255,255,0.07); color: #ccc; }
.markdown-body :deep(tr:nth-child(even) td) { background: rgba(255,255,255,0.03); }
.markdown-body :deep(blockquote) { border-left: 3px solid rgba(108,99,255,0.5); padding: 4px 10px; margin: 6px 0; color: #999; background: rgba(108,99,255,0.06); border-radius: 0 4px 4px 0; }
.markdown-body :deep(hr) { border: none; border-top: 1px solid rgba(255,255,255,0.1); margin: 8px 0; }
.markdown-body :deep(a) { color: #6c9fff; text-decoration: none; }
/* 推荐问题 */
.suggestions-area { margin-top: 8px; }
.suggestions-label { font-size: 11px; color: #555; margin-bottom: 6px; }
.suggestions-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.suggestion-chip { padding: 4px 12px; background: rgba(108,99,255,0.1); border: 1px solid rgba(108,99,255,0.25); border-radius: 20px; font-size: 12px; color: #a0a0cc; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
.suggestion-chip:hover { background: rgba(108,99,255,0.25); border-color: rgba(108,99,255,0.5); color: #c0b8ff; transform: translateY(-1px); }
/* 消息元信息 */
.message-meta { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.role-user .message-meta { justify-content: flex-end; }
.message-time { font-size: 11px; color: #555; }
.copy-btn { font-size: 11px; color: #444; cursor: pointer; padding: 1px 6px; border-radius: 4px; transition: all 0.2s; }
.copy-btn:hover { color: #888; background: rgba(255,255,255,0.06); }
.generating-text { min-height: 20px; }
.thinking-dots span { animation: blink 1.4s infinite; font-size: 20px; color: #409eff; }
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0; } 40% { opacity: 1; } }
.input-area { padding: 12px 20px 16px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(15,15,35,0.8); flex-shrink: 0; }
.address-hint { margin-bottom: 8px; }
.input-row { display: flex; gap: 8px; align-items: flex-end; }
.input-row :deep(.el-textarea__inner) { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.15); color: #e0e0ff; font-size: 14px; resize: none; }
.address-input-row { display: flex; gap: 8px; margin-top: 8px; }
.input-hint { font-size: 11px; color: #444; margin-top: 6px; text-align: center; }
.workflow-sidebar { width: 300px; background: rgba(10,10,25,0.98); border-left: 1px solid rgba(64,158,255,0.2); display: flex; flex-direction: column; flex-shrink: 0; }
.workflow-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.08); font-size: 13px; font-weight: 600; color: #409eff; }
.workflow-steps { flex: 1; overflow-y: auto; padding: 8px 12px; }
.workflow-step { display: flex; gap: 8px; padding: 5px 0; font-size: 12px; line-height: 1.5; border-bottom: 1px solid rgba(255,255,255,0.04); }
.step-icon { flex-shrink: 0; width: 18px; }
.step-body { flex: 1; min-width: 0; }
.step-name { color: #666; margin-right: 4px; }
.step-thinking .step-msg { color: #e6a23c; }
.step-executing .step-msg { color: #409eff; }
.step-result .step-msg { color: #67c23a; }
.step-warning .step-msg { color: #e6a23c; }
.step-error .step-msg { color: #f56c6c; }
.step-final .step-msg { color: #67c23a; font-weight: 600; }
.pref-item { padding: 10px 12px; background: rgba(64,158,255,0.08); border-radius: 8px; margin-bottom: 8px; }
.pref-key { font-size: 12px; color: #888; margin-bottom: 4px; }
.pref-value { font-size: 13px; color: #ccc; }
.add-pref-title { font-size: 13px; font-weight: 600; color: #e0e0ff; margin-bottom: 12px; }
</style>
