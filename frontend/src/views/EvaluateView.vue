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

    <!-- 主对话区域（ChatGPT 风格居中布局） -->
    <div class="chat-main">
      <!-- 顶部工具栏 -->
      <div class="chat-toolbar">
        <div class="toolbar-left">
          <span class="chat-title">电竞馆智能选址顾问</span>
          <el-tag size="small" type="success" style="margin-left:8px">连续对话</el-tag>
        </div>
        <div class="toolbar-right">
          <el-button size="small" @click="showPreferences = true">偏好设置</el-button>
          <el-button size="small" @click="showWorkflowLog = !showWorkflowLog">
            {{ showWorkflowLog ? '隐藏' : '显示' }}工作流
          </el-button>
        </div>
      </div>

      <!-- 居中内容容器 -->
      <div class="center-container">
        <!-- 消息列表 -->
        <div class="message-list" ref="messageListRef">
          <!-- 欢迎消息 -->
          <div v-if="messages.length === 0" class="welcome-screen">
            <div class="welcome-icon">AI</div>
            <div class="welcome-title">电竞馆智能选址顾问</div>
            <div class="welcome-desc">输入地址、商圈或经营问题，我会结合历史数据、周边客群、竞品和成本因素连续分析，并在每轮回答后推荐 3 个后续问题。</div>
            <div class="quick-questions">
              <div class="quick-title">可以这样开始</div>
              <div class="quick-grid">
                <div v-for="q in quickQuestions" :key="q" class="quick-item" @click="sendQuickQuestion(q)">{{ q }}</div>
              </div>
            </div>
          </div>

          <!-- 消息气泡 -->
          <div v-for="(msg, idx) in messages" :key="idx" class="message-wrapper" :class="`role-${msg.role}`">
            <div class="message-avatar">
              <span v-if="msg.role === 'user'">{{ userInitial }}</span>
              <span v-else>AI</span>
            </div>
            <div class="message-content">
              <div class="message-bubble" :class="msg.role">
                <div v-if="msg.role === 'assistant'" class="message-text markdown-body" v-html="renderMarkdown(msg.content)"></div>
                <div v-else class="message-text">{{ msg.content }}</div>
              </div>
              <!-- 推荐追问问题（AI 消息气泡下方） -->
              <div v-if="msg.role === 'assistant' && msg.suggestions && msg.suggestions.length > 0" class="suggestions-area">
                <div class="suggestions-label">后续可以继续问</div>
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
            <div class="message-avatar"><span>AI</span></div>
            <div class="message-content">
              <div class="message-bubble assistant">
                <div class="message-text generating-text markdown-body">
                  <span v-if="streamingContent" v-html="renderMarkdown(streamingContent)"></span>
                  <span v-else class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域（居中固定底部） -->
        <div class="input-area">
          <!-- 动态推荐问题（输入框上方，根据最后一条用户消息动态生成） -->
          <div v-if="dynamicSuggestions.length > 0 && !generating" class="dynamic-suggestions">
            <div class="dynamic-suggestions-label">基于当前问题推荐</div>
            <div class="dynamic-suggestions-chips">
              <div
                v-for="q in dynamicSuggestions"
                :key="q"
                class="dynamic-chip"
                @click="sendSuggestion(q)"
              >{{ q }}</div>
            </div>
          </div>

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
defineOptions({ name: 'EvaluateView' })
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Location, Promotion, Close } from '@element-plus/icons-vue'
import api from '@/api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useAuthStore } from '@/stores/auth'

// 配置 marked
marked.setOptions({ breaks: true, gfm: true })

// 从 sessionStorage 读取地图评估结果（MapView 跳转时写入）
const _storedResult = sessionStorage.getItem('lastEvaluationResult')
const cachedEvalResult = _storedResult ? (() => { try { return JSON.parse(_storedResult) } catch { return null } })() : null

// 接收外部传入的评估结果（从 MapView 或评估页传入）
const props = defineProps<{
  evaluationResult?: {
    address?: string
    total_score?: number
    grade?: string
    grade_label?: string
    dimensions?: Record<string, { score: number; weight: number; detail: string }>
  } | null
}>()

const sessions = ref<any[]>([])
const currentSessionId = ref<string | null>(null)
const messages = ref<any[]>([])
const inputMessage = ref('')
const generating = ref(false)
const streamingContent = ref('')
const showWorkflowLog = ref(false)
const workflowSteps = ref<any[]>([])
const workflowRef = ref<HTMLElement | null>(null)
const messageListRef = ref<HTMLElement | null>(null)
const showPreferences = ref(false)
const preferences = ref<any[]>([])
const showAddressInput = ref(false)
const evaluateAddress = ref('')
const addressMode = ref(false)
const newPref = ref({ description: '', value: '', priority: 5 })
const authStore = useAuthStore()
const userInitial = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

// 动态推荐问题（根据最后一条用户消息动态生成，最多 3 条）
const dynamicSuggestions = ref<string[]>([])

const stepIcons: Record<string, string> = {
  thinking: '🤔', executing: '⚡', result: '✅', warning: '⚠️', error: '❌', final: '🎯'
}

const quickQuestions = [
  '西安小寨路附近适合开电竞馆吗？',
  '如何评估一个地址的竞品压力？',
  '电竞馆选址最重要的三个因素是什么？',
]

/**
 * 根据用户最新提问，生成 3 条相关追问建议
 * 使用关键词匹配策略，无需额外 API 调用
 */
function generateDynamicSuggestions(userMessage: string): string[] {
  const msg = userMessage.toLowerCase()

  // 地址/选址类
  if (msg.includes('适合') || msg.includes('选址') || msg.includes('哪里') || msg.includes('地址') || msg.includes('位置')) {
    return [
      '这个地址的竞品压力如何？',
      '周边目标客群（18-28岁）密度怎么样？',
      '预计月租金和营收比是否合理？',
    ]
  }
  // 竞品/竞争类
  if (msg.includes('竞品') || msg.includes('竞争') || msg.includes('对手') || msg.includes('同行')) {
    return [
      '如何分析竞品的定价策略？',
      '竞品密度高的区域还值得进入吗？',
      '如何通过差异化竞争突围？',
    ]
  }
  // 客群/人群类
  if (msg.includes('客群') || msg.includes('人群') || msg.includes('用户') || msg.includes('消费')) {
    return [
      '电竞馆的核心目标客群画像是什么？',
      '如何判断周边消费能力是否足够？',
      '大学城和商业区的客群有何差异？',
    ]
  }
  // 租金/成本类
  if (msg.includes('租金') || msg.includes('成本') || msg.includes('费用') || msg.includes('投入') || msg.includes('资金')) {
    return [
      '电竞馆的合理回本周期是多久？',
      '如何控制初期装修和设备成本？',
      '租金占营收多少比例是健康的？',
    ]
  }
  // 门店/历史数据类
  if (msg.includes('门店') || msg.includes('历史') || msg.includes('案例') || msg.includes('经验') || msg.includes('数据')) {
    return [
      '历史上哪些选址因素最影响门店成败？',
      '成功门店和失败门店的核心差异是什么？',
      '能推荐几个类似条件的参考案例吗？',
    ]
  }
  // 评分/评估类
  if (msg.includes('评分') || msg.includes('评估') || msg.includes('得分') || msg.includes('分析')) {
    return [
      '评分最低的维度如何改善？',
      '综合评分多少分以上才值得开店？',
      '各维度权重是如何设定的？',
    ]
  }
  // 政策/法规类
  if (msg.includes('政策') || msg.includes('法规') || msg.includes('审批') || msg.includes('证件') || msg.includes('营业执照')) {
    return [
      '开电竞馆需要哪些资质和证件？',
      '未成年人保护政策对电竞馆有何影响？',
      '如何了解当地商业区政策优惠？',
    ]
  }
  // 交通/配套类
  if (msg.includes('交通') || msg.includes('地铁') || msg.includes('公交') || msg.includes('停车') || msg.includes('配套')) {
    return [
      '地铁口附近选址有哪些优劣势？',
      '停车位是否影响电竞馆客流？',
      '商场内和街边店哪种更适合？',
    ]
  }
  // 默认通用推荐
  return [
    '能帮我分析一个具体地址吗？',
    '电竞馆选址最容易踩的坑有哪些？',
    '如何用数据验证选址决策是否正确？',
  ]
}

// 监听消息列表变化，当用户发送新消息后更新动态推荐问题
watch(messages, (newMsgs) => {
  const userMsgs = newMsgs.filter(m => m.role === 'user')
  if (userMsgs.length > 0) {
    const lastUserMsg = userMsgs[userMsgs.length - 1].content || ''
    dynamicSuggestions.value = generateDynamicSuggestions(lastUserMsg)
  } else {
    dynamicSuggestions.value = []
  }
}, { deep: true })

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
    dynamicSuggestions.value = []
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
  // 发送时立即更新动态推荐问题（基于当前提问）
  dynamicSuggestions.value = generateDynamicSuggestions(userMsg)
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
        address: addressMode.value ? evaluateAddress.value : (cachedEvalResult?.address || props.evaluationResult?.address || undefined),
        // 将当前评估结果注入对话上下文，让 AI 真正基于数据回答（优先 sessionStorage 缓存）
        evaluation_context: cachedEvalResult || props.evaluationResult || undefined,
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let assistantContent = ''
    let pendingSuggestions: string[] = []

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
            pendingSuggestions = event.questions || []
            const lastAssistant = messages.value.filter(m => m.role === 'assistant').slice(-1)[0]
            if (lastAssistant) {
              lastAssistant.suggestions = pendingSuggestions
              pendingSuggestions = []
            }
          } else if (event.type === 'done') {
            // 将流式内容写入消息列表
            const existingMsg = messages.value.find(m => m.role === 'assistant' && m.content === assistantContent)
            if (!existingMsg) {
              messages.value.push({
                role: 'assistant',
                content: assistantContent,
                created_at: new Date().toISOString(),
                suggestions: pendingSuggestions,
              })
              pendingSuggestions = []
            } else if (pendingSuggestions.length > 0) {
              existingMsg.suggestions = pendingSuggestions
              pendingSuggestions = []
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
/* ===== 整体布局 ===== */
.evaluate-view {
  display: flex;
  height: calc(100vh - 60px);
  background: #0a0a1e;
  overflow: hidden;
}

/* ===== 左侧会话列表 ===== */
.session-sidebar {
  width: 220px;
  background: rgba(15,15,35,0.98);
  border-right: 1px solid rgba(255,255,255,0.08);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.sidebar-title { font-size: 13px; font-weight: 600; color: #e0e0ff; }
.session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.2s;
}
.session-item:hover { background: rgba(255,255,255,0.06); }
.session-item.active {
  background: rgba(64,158,255,0.15);
  border: 1px solid rgba(64,158,255,0.3);
}
.session-title { font-size: 13px; color: #ddd; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-meta { font-size: 11px; color: #666; margin-top: 3px; }

/* ===== 主对话区域（居中） ===== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  background: rgba(15,15,35,0.8);
  flex-shrink: 0;
}
.toolbar-left { display: flex; align-items: center; }
.chat-title { font-size: 15px; font-weight: 600; color: #e0e0ff; }
.toolbar-right { display: flex; gap: 8px; }

/* 居中容器：限制最大宽度，水平居中 */
.center-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
  min-height: 0;
  padding: 0 16px;
}

/* ===== 消息列表 ===== */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 欢迎屏 */
.welcome-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  text-align: center;
  padding: 40px 20px;
}
.welcome-icon { font-size: 56px; margin-bottom: 16px; }
.welcome-title { font-size: 22px; font-weight: 700; color: #e0e0ff; margin-bottom: 10px; }
.welcome-desc { font-size: 14px; color: #888; max-width: 480px; line-height: 1.7; margin-bottom: 32px; }
.quick-questions { width: 100%; max-width: 560px; }
.quick-title { font-size: 12px; color: #666; margin-bottom: 12px; }
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.quick-item {
  padding: 12px 16px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  font-size: 13px;
  color: #ccc;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}
.quick-item:hover { background: rgba(64,158,255,0.15); border-color: rgba(64,158,255,0.4); color: #409eff; }

/* 消息气泡 */
.message-wrapper { display: flex; gap: 12px; align-items: flex-start; }
.message-wrapper.role-user { flex-direction: row-reverse; }
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(255,255,255,0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.message-content { max-width: 75%; }
.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
}
.message-bubble.user {
  background: rgba(64,158,255,0.2);
  border: 1px solid rgba(64,158,255,0.3);
  color: #e0e0ff;
  border-top-right-radius: 4px;
}
.message-bubble.assistant {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  color: #ddd;
  border-top-left-radius: 4px;
}

/* Markdown 渲染 */
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

/* AI 消息下方推荐追问 */
.suggestions-area { margin-top: 8px; }
.suggestions-label { font-size: 11px; color: #555; margin-bottom: 6px; }
.suggestions-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.suggestion-chip {
  padding: 4px 12px;
  background: rgba(108,99,255,0.1);
  border: 1px solid rgba(108,99,255,0.25);
  border-radius: 20px;
  font-size: 12px;
  color: #a0a0cc;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
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

/* ===== 输入区域 ===== */
.input-area {
  padding: 10px 0 16px;
  border-top: 1px solid rgba(255,255,255,0.08);
  background: transparent;
  flex-shrink: 0;
}

/* 动态推荐问题（输入框上方） */
.dynamic-suggestions {
  margin-bottom: 10px;
  animation: fadeInUp 0.3s ease;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.dynamic-suggestions-label {
  font-size: 11px;
  color: #555;
  margin-bottom: 7px;
}
.dynamic-suggestions-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dynamic-chip {
  padding: 6px 14px;
  background: rgba(64,158,255,0.08);
  border: 1px solid rgba(64,158,255,0.2);
  border-radius: 20px;
  font-size: 12px;
  color: #7ab8f5;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dynamic-chip:hover {
  background: rgba(64,158,255,0.18);
  border-color: rgba(64,158,255,0.45);
  color: #a8d4ff;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(64,158,255,0.15);
}

.address-hint { margin-bottom: 8px; }
.input-row { display: flex; gap: 8px; align-items: flex-end; }
.input-row :deep(.el-textarea__inner) {
  background: rgba(255,255,255,0.05);
  border-color: rgba(255,255,255,0.15);
  color: #e0e0ff;
  font-size: 14px;
  resize: none;
}
.address-input-row { display: flex; gap: 8px; margin-top: 8px; }
.input-hint { font-size: 11px; color: #444; margin-top: 6px; text-align: center; }

/* ===== 右侧工作流日志 ===== */
.workflow-sidebar {
  width: 280px;
  background: rgba(10,10,25,0.98);
  border-left: 1px solid rgba(64,158,255,0.2);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.workflow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
}
.workflow-steps { flex: 1; overflow-y: auto; padding: 8px 12px; }
.workflow-step {
  display: flex;
  gap: 8px;
  padding: 5px 0;
  font-size: 12px;
  line-height: 1.5;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.step-icon { flex-shrink: 0; width: 18px; }
.step-body { flex: 1; min-width: 0; }
.step-name { color: #666; margin-right: 4px; }
.step-thinking .step-msg { color: #e6a23c; }
.step-executing .step-msg { color: #409eff; }
.step-result .step-msg { color: #67c23a; }
.step-warning .step-msg { color: #e6a23c; }
.step-error .step-msg { color: #f56c6c; }
.step-final .step-msg { color: #67c23a; font-weight: 600; }

/* ===== 偏好设置 ===== */
.pref-item { padding: 10px 12px; background: rgba(64,158,255,0.08); border-radius: 8px; margin-bottom: 8px; }
.pref-key { font-size: 12px; color: #888; margin-bottom: 4px; }
.pref-value { font-size: 13px; color: #ccc; }
.add-pref-title { font-size: 13px; font-weight: 600; color: #e0e0ff; margin-bottom: 12px; }

/* ===== ChatGPT 风格覆盖样式 ===== */
.evaluate-view {
  height: calc(100vh - 64px);
  background: #f7f7f8;
  color: #1f2328;
}

.session-sidebar {
  width: 260px;
  background: #f1f2f4;
  border-right: 1px solid #e0e3e7;
}

.sidebar-header {
  padding: 14px;
  border-bottom: 1px solid #e0e3e7;
}

.sidebar-title {
  color: #24292f;
  font-size: 14px;
}

.session-list {
  padding: 10px;
}

.session-item {
  border-radius: 8px;
  padding: 10px 12px;
}

.session-item:hover {
  background: #e7e9ec;
}

.session-item.active {
  background: #ffffff;
  border: 1px solid #d8dee4;
  box-shadow: 0 1px 2px rgba(31, 35, 40, 0.06);
}

.session-title {
  color: #24292f;
}

.session-meta,
.no-sessions {
  color: #6e7781;
}

.chat-main {
  background: #ffffff;
}

.chat-toolbar {
  height: 56px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid #eaeef2;
  backdrop-filter: blur(10px);
}

.chat-title {
  color: #24292f;
  font-size: 15px;
  font-weight: 650;
}

.center-container {
  max-width: 860px;
  padding: 0 20px;
}

.message-list {
  gap: 0;
  padding: 24px 0 18px;
}

.welcome-screen {
  min-height: 100%;
  justify-content: center;
  padding-bottom: 96px;
}

.welcome-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: #111827;
  color: #ffffff;
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 18px;
}

.welcome-title {
  color: #1f2328;
  font-size: 26px;
  margin-bottom: 10px;
}

.welcome-desc {
  color: #57606a;
  max-width: 620px;
  font-size: 14px;
  margin-bottom: 28px;
}

.quick-questions {
  max-width: 720px;
}

.quick-title {
  color: #6e7781;
  text-align: left;
  margin-bottom: 10px;
}

.quick-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.quick-item {
  min-height: 82px;
  background: #ffffff;
  border: 1px solid #d8dee4;
  color: #24292f;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(31, 35, 40, 0.04);
}

.quick-item:hover {
  background: #f6f8fa;
  border-color: #8c959f;
  color: #0969da;
  transform: translateY(-1px);
}

.message-wrapper {
  gap: 14px;
  padding: 18px 0;
  border-bottom: 1px solid #f0f2f4;
}

.message-wrapper.role-user {
  flex-direction: row;
  justify-content: flex-end;
  border-bottom: none;
}

.message-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #111827;
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  margin-top: 3px;
}

.role-user .message-avatar {
  display: none;
}

.message-content {
  max-width: min(720px, 100%);
}

.role-user .message-content {
  max-width: min(620px, 86%);
}

.message-bubble {
  padding: 0;
  font-size: 15px;
  line-height: 1.75;
  border-radius: 0;
}

.message-bubble.assistant {
  background: transparent;
  border: none;
  color: #24292f;
}

.message-bubble.user {
  background: #f4f4f4;
  border: 1px solid #e6e8eb;
  color: #24292f;
  padding: 10px 14px;
  border-radius: 18px;
}

.message-meta {
  margin-top: 6px;
}

.message-time,
.copy-btn,
.suggestions-label,
.dynamic-suggestions-label {
  color: #8c959f;
}

.copy-btn:hover {
  background: #f1f2f4;
  color: #57606a;
}

.suggestions-area {
  margin-top: 14px;
}

.suggestions-chips,
.dynamic-suggestions-chips {
  gap: 8px;
}

.suggestion-chip,
.dynamic-chip {
  background: #ffffff;
  border: 1px solid #d8dee4;
  color: #57606a;
  border-radius: 999px;
  padding: 7px 12px;
  max-width: 100%;
  white-space: normal;
}

.suggestion-chip:hover,
.dynamic-chip:hover {
  background: #f6f8fa;
  border-color: #0969da;
  color: #0969da;
  box-shadow: none;
}

.input-area {
  position: sticky;
  bottom: 0;
  padding: 12px 0 18px;
  border-top: none;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), #ffffff 22%);
}

.input-row {
  align-items: flex-end;
  gap: 8px;
  padding: 10px;
  background: #ffffff;
  border: 1px solid #d8dee4;
  border-radius: 18px;
  box-shadow: 0 8px 26px rgba(31, 35, 40, 0.12);
}

.input-row :deep(.el-textarea__inner) {
  min-height: 38px !important;
  background: transparent;
  border: none;
  box-shadow: none;
  color: #24292f;
  font-size: 15px;
  line-height: 1.6;
  padding: 8px 4px;
}

.input-row :deep(.el-textarea__inner::placeholder) {
  color: #8c959f;
}

.address-input-row {
  background: #ffffff;
  border: 1px solid #d8dee4;
  border-radius: 12px;
  padding: 8px;
}

.input-hint {
  color: #8c959f;
}

.dynamic-suggestions {
  margin-bottom: 10px;
}

.workflow-sidebar {
  background: #ffffff;
  border-left: 1px solid #d8dee4;
}

.workflow-header {
  color: #0969da;
  border-bottom: 1px solid #eaeef2;
}

.workflow-step {
  border-bottom: 1px solid #f0f2f4;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  color: #24292f;
}

.markdown-body :deep(h2) {
  border-bottom: 1px solid #d8dee4;
}

.markdown-body :deep(strong) {
  color: #111827;
}

.markdown-body :deep(code) {
  background: #f6f8fa;
  border: 1px solid #d8dee4;
  color: #24292f;
}

.markdown-body :deep(pre) {
  background: #f6f8fa;
  border: 1px solid #d8dee4;
}

.markdown-body :deep(th) {
  background: #f6f8fa;
  color: #24292f;
  border: 1px solid #d8dee4;
}

.markdown-body :deep(td) {
  color: #24292f;
  border: 1px solid #d8dee4;
}

.markdown-body :deep(blockquote) {
  background: #f6f8fa;
  border-left-color: #8c959f;
  color: #57606a;
}

@media (max-width: 1024px) {
  .session-sidebar {
    display: none;
  }

  .center-container {
    max-width: 100%;
  }

  .quick-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .chat-toolbar {
    padding: 0 12px;
  }

  .toolbar-right {
    gap: 4px;
  }

  .toolbar-right .el-button {
    padding: 6px 8px;
  }

  .center-container {
    padding: 0 12px;
  }

  .message-content,
  .role-user .message-content {
    max-width: 100%;
  }

  .message-wrapper {
    padding: 14px 0;
  }

  .workflow-sidebar {
    display: none;
  }
}
</style>
