<template>
  <div class="settings-container">
    <div class="page-header">
      <h2>⚙️ 系统配置</h2>
      <p class="subtitle">配置大模型、向量模型、地图 API 等核心接口，所有配置保存后立即生效</p>
    </div>

    <el-tabs v-model="activeTab" type="border-card" class="settings-tabs">
      <!-- 大模型配置 -->
      <el-tab-pane label="🤖 大模型 (LLM)" name="llm">
        <div class="tab-content">
          <el-alert title="大模型用于生成选址评估报告和 AI 对话。支持本地 Ollama 模型和 OpenAI 兼容 API。" type="info" :closable="false" style="margin-bottom: 20px" />
          <el-form :model="llmForm" label-width="160px" class="config-form">
            <el-form-item label="模型类型">
              <el-radio-group v-model="llmForm.type" @change="onLlmTypeChange">
                <el-radio-button value="local">🖥️ 本地 Ollama</el-radio-button>
                <el-radio-button value="api">☁️ API 模式</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <template v-if="llmForm.type === 'local'">
              <el-form-item label="Ollama 地址">
                <el-input v-model="llmForm.local_url" placeholder="http://localhost:11434/v1"><template #prepend>URL</template></el-input>
                <div class="form-tip">Ollama OpenAI 兼容接口，默认端口 11434。如 Ollama 在其他机器上，填写该机器 IP，例如 http://192.168.1.100:11434/v1</div>
              </el-form-item>
              <el-form-item label="主推理模型">
                <el-select v-model="llmForm.model_name" filterable allow-create placeholder="选择或输入模型名称" style="width:100%">
                  <el-option v-for="m in ollamaModels" :key="m" :label="m" :value="m" />
                </el-select>
                <div class="form-tip">用于生成完整选址报告，推荐 qwen2.5:32b（高质量）</div>
              </el-form-item>
              <el-form-item label="快速推理模型">
                <el-select v-model="llmForm.fast_model" filterable allow-create placeholder="选择或输入模型名称" style="width:100%">
                  <el-option v-for="m in ollamaModels" :key="m" :label="m" :value="m" />
                </el-select>
                <div class="form-tip">用于意图分析等轻量任务，推荐 qwen2.5:14b-instruct（速度快）</div>
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="llmForm.api_key" placeholder="ollama（本地模式固定填 ollama）" />
                <div class="form-tip">本地 Ollama 模式固定填写 <code>ollama</code></div>
              </el-form-item>
            </template>
            <template v-else>
              <el-form-item label="API Base URL">
                <el-input v-model="llmForm.api_base" placeholder="https://api.openai.com/v1"><template #prepend>URL</template></el-input>
                <div class="form-tip">OpenAI 兼容 API，阿里云百炼: https://dashscope.aliyuncs.com/compatible-mode/v1</div>
              </el-form-item>
              <el-form-item label="主推理模型">
                <el-select v-model="llmForm.model_name" filterable allow-create placeholder="输入模型名称" style="width:100%">
                  <el-option-group label="OpenAI"><el-option label="gpt-4o" value="gpt-4o" /><el-option label="gpt-4o-mini" value="gpt-4o-mini" /></el-option-group>
                  <el-option-group label="阿里云百炼"><el-option label="qwen-max" value="qwen-max" /><el-option label="qwen-plus" value="qwen-plus" /><el-option label="qwen-turbo" value="qwen-turbo" /></el-option-group>
                  <el-option-group label="智谱 AI"><el-option label="glm-4" value="glm-4" /><el-option label="glm-4-flash" value="glm-4-flash" /></el-option-group>
                </el-select>
              </el-form-item>
              <el-form-item label="快速推理模型"><el-input v-model="llmForm.fast_model" placeholder="如 gpt-4o-mini 或 qwen-turbo" /></el-form-item>
              <el-form-item label="API Key"><el-input v-model="llmForm.api_key" type="password" show-password placeholder="sk-..." /></el-form-item>
            </template>
          </el-form>
          <div class="action-bar">
            <el-button type="primary" :loading="saving.llm" @click="saveConfig('llm')">💾 保存大模型配置</el-button>
            <el-button :loading="testing.llm" @click="testLLM">🔌 测试连通性</el-button>
          </div>
          <!-- 测试结果：全宽展示，错误信息完整可见 -->
          <div v-if="testResult.llm" style="margin-top: 12px">
            <el-alert
              :title="testResult.llm.ok ? '✅ 连接成功' : '❌ 连接失败'"
              :description="testResult.llm.msg"
              :type="testResult.llm.ok ? 'success' : 'error'"
              :closable="true"
              show-icon
              @close="testResult.llm = null"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- 嵌入模型配置 -->
      <el-tab-pane label="🔢 嵌入模型 (Embedding)" name="embedding">
        <div class="tab-content">
          <el-alert title="嵌入模型将历史数据文本转为向量，用于 RAG 语义检索。推荐使用已部署的 bge-m3:latest。" type="info" :closable="false" style="margin-bottom: 20px" />
          <el-form :model="embedForm" label-width="160px" class="config-form">
            <el-form-item label="模型类型">
              <el-radio-group v-model="embedForm.type">
                <el-radio-button value="local">🖥️ 本地 Ollama</el-radio-button>
                <el-radio-button value="api">☁️ API 模式</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <template v-if="embedForm.type === 'local'">
              <el-form-item label="Ollama 地址">
                <el-input v-model="embedForm.local_url" placeholder="http://localhost:11434/api/embeddings"><template #prepend>URL</template></el-input>
                <div class="form-tip">Ollama 原生 embeddings 接口（非 OpenAI 兼容接口）</div>
              </el-form-item>
              <el-form-item label="嵌入模型名称">
                <el-select v-model="embedForm.model_name" filterable allow-create style="width:100%">
                  <el-option label="bge-m3:latest（已部署，推荐）" value="bge-m3:latest" />
                  <el-option label="nomic-embed-text" value="nomic-embed-text" />
                  <el-option label="mxbai-embed-large" value="mxbai-embed-large" />
                </el-select>
                <div class="form-tip">bge-m3 支持中英文，效果优秀，已在你的 Ollama 中部署</div>
              </el-form-item>
              <el-form-item label="API Key"><el-input v-model="embedForm.api_key" placeholder="ollama" /></el-form-item>
            </template>
            <template v-else>
              <el-form-item label="API Base URL"><el-input v-model="embedForm.local_url" placeholder="https://api.openai.com/v1" /></el-form-item>
              <el-form-item label="嵌入模型名称">
                <el-select v-model="embedForm.model_name" filterable allow-create style="width:100%">
                  <el-option label="text-embedding-3-small" value="text-embedding-3-small" />
                  <el-option label="text-embedding-3-large" value="text-embedding-3-large" />
                  <el-option label="text-embedding-ada-002" value="text-embedding-ada-002" />
                </el-select>
              </el-form-item>
              <el-form-item label="API Key"><el-input v-model="embedForm.api_key" type="password" show-password placeholder="sk-..." /></el-form-item>
            </template>
          </el-form>
          <div class="action-bar">
            <el-button type="primary" :loading="saving.embed" @click="saveConfig('embed')">💾 保存嵌入模型配置</el-button>
            <el-button :loading="testing.embed" @click="testEmbed">🔌 测试连通性</el-button>
          </div>
          <div v-if="testResult.embed" style="margin-top: 12px">
            <el-alert
              :title="testResult.embed.ok ? '✅ 连接成功' : '❌ 连接失败'"
              :description="testResult.embed.msg"
              :type="testResult.embed.ok ? 'success' : 'error'"
              :closable="true"
              show-icon
              @close="testResult.embed = null"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- 重排模型配置 -->
      <el-tab-pane label="🔀 重排模型 (Reranker)" name="reranker">
        <div class="tab-content">
          <el-alert title="重排模型对多路召回结果精排，提升 RAG 准确性。当前无本地重排模型时选择「跳过」即可正常运行。" type="warning" :closable="false" style="margin-bottom: 20px" />
          <el-form :model="rerankForm" label-width="160px" class="config-form">
            <el-form-item label="重排策略">
              <el-radio-group v-model="rerankForm.type">
                <el-radio-button value="none">⏭️ 跳过重排</el-radio-button>
                <el-radio-button value="local">🖥️ 本地模型</el-radio-button>
                <el-radio-button value="api">☁️ Cohere API</el-radio-button>
              </el-radio-group>
              <div class="form-tip" v-if="rerankForm.type === 'none'">跳过重排时系统仍可正常工作，RAG 结果按向量相似度排序</div>
            </el-form-item>
            <template v-if="rerankForm.type === 'local'">
              <el-form-item label="模型服务地址"><el-input v-model="rerankForm.local_url" placeholder="http://localhost:8001/rerank" /></el-form-item>
              <el-form-item label="模型名称"><el-input v-model="rerankForm.model_name" placeholder="BAAI/bge-reranker-v2-m3" /></el-form-item>
            </template>
            <template v-if="rerankForm.type === 'api'">
              <el-form-item label="Cohere API Key"><el-input v-model="rerankForm.api_key" type="password" show-password placeholder="co-..." /></el-form-item>
              <el-form-item label="模型名称">
                <el-select v-model="rerankForm.model_name" style="width:100%">
                  <el-option label="rerank-multilingual-v3.0（支持中文）" value="rerank-multilingual-v3.0" />
                  <el-option label="rerank-english-v3.0" value="rerank-english-v3.0" />
                </el-select>
              </el-form-item>
            </template>
          </el-form>
          <div class="action-bar">
            <el-button type="primary" :loading="saving.rerank" @click="saveConfig('rerank')">💾 保存重排模型配置</el-button>
          </div>
        </div>
      </el-tab-pane>

      <!-- 地图 API 配置 -->
      <el-tab-pane label="🗺️ 地图 API" name="map">
        <div class="tab-content">
          <el-alert title="高德地图 API Key 是必填项，用于地址解析（地理编码）和周边 POI 数据查询。请在高德开放平台申请。" type="error" :closable="false" style="margin-bottom: 20px" />
          <el-form :model="mapForm" label-width="180px" class="config-form">
            <el-divider content-position="left">高德地图（必填）</el-divider>
            <el-form-item label="Web 服务 Key">
              <el-input v-model="mapForm.amap_api_key" type="password" show-password placeholder="32位字符串">
                <template #append><el-button @click="openAmapConsole">申请 Key</el-button></template>
              </el-input>
              <div class="form-tip">用于后端地址解析和 POI 查询，在高德控制台创建「Web 服务」类型应用获取</div>
            </el-form-item>
            <el-form-item label="JS API Key（前端地图）">
              <el-input v-model="mapForm.amap_js_key" type="password" show-password placeholder="32位字符串" />
              <div class="form-tip">用于前端地图显示，可与 Web 服务 Key 相同</div>
            </el-form-item>
            <el-form-item label="JS API 安全密钥">
              <el-input v-model="mapForm.amap_security_code" type="password" show-password placeholder="高德控制台 > 我的应用 > 安全密钥" />
              <div class="form-tip">⚠️ 高德地图 JS API 2.0 必须填写安全密钥，否则地图无法显示</div>
            </el-form-item>
            <el-form-item label="慧眼企业 Key（热力图）">
              <el-input v-model="mapForm.amap_huiyan_key" type="password" show-password placeholder="开通高德慧眼/商圈洞察企业权限后填写" />
              <div class="form-tip">用于真实消费热力图。未配置时，系统不会自动使用模拟热力图，需客户在地图页明确授权。</div>
            </el-form-item>
            <el-divider content-position="left">美团 API（可选）</el-divider>
            <el-form-item label="美团 API Key">
              <el-input v-model="mapForm.meituan_api_key" type="password" show-password placeholder="可选，用于获取周边餐饮娱乐数据" />
            </el-form-item>
          </el-form>
          <div class="action-bar">
            <el-button type="primary" :loading="saving.map" @click="saveConfig('map')">💾 保存地图配置</el-button>
            <el-button :loading="testing.map" @click="testAmap">🔌 测试高德 API</el-button>
          </div>
          <div v-if="testResult.map" style="margin-top: 12px">
            <el-alert
              :title="testResult.map.ok ? '✅ 高德 API 连接成功' : '❌ 高德 API 连接失败'"
              :description="testResult.map.msg"
              :type="testResult.map.ok ? 'success' : 'error'"
              :closable="true"
              show-icon
              @close="testResult.map = null"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- 评分权重 -->
      <el-tab-pane label="📊 评分权重" name="scoring">
        <div class="tab-content">
          <el-alert title="六大维度评分权重，总和为 1.0。上传历史运营数据后，系统会自动分析并调整动态权重。" type="info" :closable="false" style="margin-bottom: 20px" />
          <el-table :data="scoringRules" border stripe style="width:100%">
            <el-table-column prop="dimension_name" label="维度" width="120" />
            <el-table-column prop="sub_factor" label="评分因子" width="180" />
            <el-table-column label="基础权重" width="120">
              <template #default="{ row }"><el-tag>{{ (row.base_weight * 100).toFixed(0) }}%</el-tag></template>
            </el-table-column>
            <el-table-column label="动态权重（历史数据驱动）" width="220">
              <template #default="{ row }">
                <el-tag :type="row.effective_weight !== row.base_weight ? 'warning' : 'info'">
                  {{ (row.effective_weight * 100).toFixed(0) }}%
                  <span v-if="row.effective_weight !== row.base_weight"> ↑</span>
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_updated_by" label="最后更新" />
          </el-table>
          <div class="action-bar" style="margin-top:16px">
            <el-button @click="loadScoringRules">🔄 刷新权重</el-button>
            <span class="form-tip" style="margin-left:12px">权重由系统根据历史数据自动调整，无需手动修改</span>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const activeTab = ref('llm')
const ollamaModels = ['qwen2.5:32b', 'qwen2.5:14b-instruct', 'qwen2.5:14b', 'llama3.1:8b', 'llama3.1:70b', 'deepseek-r1:7b', 'deepseek-r1:14b']

const llmForm = reactive({ type: 'local', local_url: 'http://localhost:11434/v1', model_name: 'qwen2.5:32b', fast_model: 'qwen2.5:14b-instruct', api_key: 'ollama', api_base: '' })
const embedForm = reactive({ type: 'local', local_url: 'http://localhost:11434/api/embeddings', model_name: 'bge-m3:latest', api_key: 'ollama' })
const rerankForm = reactive({ type: 'none', local_url: '', model_name: '', api_key: '' })
const mapForm = reactive({ amap_api_key: '', amap_js_key: '', amap_security_code: '', amap_huiyan_key: '', meituan_api_key: '' })
const scoringRules = ref<any[]>([])
const saving = reactive({ llm: false, embed: false, rerank: false, map: false })
const testing = reactive({ llm: false, embed: false, map: false })
const testResult = reactive<Record<string, { ok: boolean; msg: string } | null>>({ llm: null, embed: null, map: null })

const api = axios.create({ baseURL: '/api/v1' })
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
// 响应拦截：直接返回 data，简化调用
api.interceptors.response.use(
  response => response.data,
  error => Promise.reject(error)
)

async function loadConfigs() {
  try {
    const data: any[] = await api.get('/system/config/')
    const configs: Record<string, string> = {}
    data.forEach((item: any) => { configs[item.config_key] = item.config_value || '' })
    if (configs['llm.type']) llmForm.type = configs['llm.type']
    if (configs['llm.local_url']) llmForm.local_url = configs['llm.local_url']
    if (configs['llm.model_name']) llmForm.model_name = configs['llm.model_name']
    if (configs['llm.fast_model']) llmForm.fast_model = configs['llm.fast_model']
    if (configs['llm.api_key']) llmForm.api_key = configs['llm.api_key']
    if (configs['llm.api_base']) llmForm.api_base = configs['llm.api_base']
    if (configs['embed.type']) embedForm.type = configs['embed.type']
    if (configs['embed.local_url']) embedForm.local_url = configs['embed.local_url']
    if (configs['embed.model_name']) embedForm.model_name = configs['embed.model_name']
    if (configs['embed.api_key']) embedForm.api_key = configs['embed.api_key']
    if (configs['rerank.type']) rerankForm.type = configs['rerank.type']
    if (configs['rerank.local_url']) rerankForm.local_url = configs['rerank.local_url']
    if (configs['rerank.model_name']) rerankForm.model_name = configs['rerank.model_name']
    if (configs['rerank.api_key']) rerankForm.api_key = configs['rerank.api_key']
    if (configs['amap_api_key']) mapForm.amap_api_key = configs['amap_api_key']
    if (configs['amap_js_key']) mapForm.amap_js_key = configs['amap_js_key']
    if (configs['amap_security_code']) mapForm.amap_security_code = configs['amap_security_code']
    if (configs['amap_huiyan_key']) mapForm.amap_huiyan_key = configs['amap_huiyan_key']
    if (configs['meituan.api_key']) mapForm.meituan_api_key = configs['meituan.api_key']
  } catch (e) {
    ElMessage.error('加载配置失败，请刷新页面重试')
  }
}

async function loadScoringRules() {
  try {
    const data: any[] = await api.get('/evaluate/scoring-rules')
    scoringRules.value = data
  } catch (e) { /* ignore */ }
}

async function saveConfig(type: 'llm' | 'embed' | 'rerank' | 'map') {
  saving[type] = true
  try {
    let updates: Record<string, string> = {}
    if (type === 'llm') updates = { 'llm.type': llmForm.type, 'llm.local_url': llmForm.local_url, 'llm.model_name': llmForm.model_name, 'llm.fast_model': llmForm.fast_model, 'llm.api_key': llmForm.api_key, 'llm.api_base': llmForm.api_base }
    else if (type === 'embed') updates = { 'embed.type': embedForm.type, 'embed.local_url': embedForm.local_url, 'embed.model_name': embedForm.model_name, 'embed.api_key': embedForm.api_key }
    else if (type === 'rerank') updates = { 'rerank.type': rerankForm.type, 'rerank.local_url': rerankForm.local_url, 'rerank.model_name': rerankForm.model_name, 'rerank.api_key': rerankForm.api_key }
    else if (type === 'map') updates = { 'amap_api_key': mapForm.amap_api_key, 'amap_js_key': mapForm.amap_js_key, 'amap_security_code': mapForm.amap_security_code, 'amap_huiyan_key': mapForm.amap_huiyan_key, 'meituan.api_key': mapForm.meituan_api_key }
    await api.post('/system/config/batch', { configs: updates })
    ElMessage.success('配置已保存，立即生效')
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally { saving[type] = false }
}

async function testLLM() {
  testing.llm = true
  testResult.llm = null
  try {
    const data: any = await api.post('/system/config/test', {
      type: 'llm',
      llm_type: llmForm.type,
      llm_local_url: llmForm.local_url,
      llm_api_base: llmForm.api_base,
      llm_api_key: llmForm.api_key,
      llm_model_name: llmForm.model_name
    })
    testResult.llm = {
      ok: data.success === true,
      msg: data.message || (data.success ? '连接成功' : '未知错误')
    }
  } catch (e: any) {
    const errMsg = e.response?.data?.detail || e.response?.data?.message || e.message || '请求失败'
    testResult.llm = { ok: false, msg: `请求异常: ${errMsg}` }
  } finally {
    testing.llm = false
  }
}

async function testEmbed() {
  testing.embed = true
  testResult.embed = null
  try {
    const data: any = await api.post('/system/config/test', {
      type: 'embedding',
      embed_type: embedForm.type,
      embed_local_url: embedForm.local_url,
      embed_model_name: embedForm.model_name,
      embed_api_key: embedForm.api_key
    })
    testResult.embed = {
      ok: data.success === true,
      msg: data.message || (data.success ? '连接成功' : '未知错误')
    }
  } catch (e: any) {
    const errMsg = e.response?.data?.detail || e.response?.data?.message || e.message || '请求失败'
    testResult.embed = { ok: false, msg: `请求异常: ${errMsg}` }
  } finally {
    testing.embed = false
  }
}

async function testAmap() {
  testing.map = true
  testResult.map = null
  try {
    const data: any = await api.post('/system/config/test', {
      type: 'amap',
      amap_api_key: mapForm.amap_api_key
    })
    testResult.map = {
      ok: data.success === true,
      msg: data.message || (data.success ? '连接成功' : '未知错误')
    }
  } catch (e: any) {
    const errMsg = e.response?.data?.detail || e.response?.data?.message || e.message || '请求失败'
    testResult.map = { ok: false, msg: `请求异常: ${errMsg}` }
  } finally {
    testing.map = false
  }
}

function onLlmTypeChange(val: string) {
  if (val === 'local') { llmForm.api_key = 'ollama'; llmForm.local_url = 'http://localhost:11434/v1' }
  else { llmForm.api_key = '' }
}

function openAmapConsole() { window.open('https://lbs.amap.com/dev/key/app', '_blank') }

onMounted(() => { loadConfigs(); loadScoringRules() })
</script>

<style scoped>
.settings-container { padding: 24px; max-width: 900px; margin: 0 auto; }
.page-header { margin-bottom: 24px; }
.page-header h2 { margin: 0 0 8px 0; font-size: 22px; color: #e0e0e0; }
.subtitle { color: #888; margin: 0; font-size: 14px; }
.settings-tabs { background: #1a1a2e; border-color: #333; }
.tab-content { padding: 16px 0; }
.config-form { max-width: 700px; }
.form-tip { font-size: 12px; color: #888; margin-top: 4px; line-height: 1.5; }
.form-tip a { color: #409eff; }
.form-tip code { background: #2a2a3e; padding: 1px 6px; border-radius: 3px; font-family: monospace; color: #e6db74; }
.action-bar { margin-top: 24px; display: flex; align-items: center; gap: 12px; padding-top: 16px; border-top: 1px solid #333; }
:deep(.el-tabs__header) { background: #16213e; }
:deep(.el-tabs__item) { color: #aaa; }
:deep(.el-tabs__item.is-active) { color: #409eff; }
:deep(.el-form-item__label) { color: #ccc; }
:deep(.el-divider__text) { color: #888; background: transparent; }
:deep(.el-alert__description) { font-size: 13px; line-height: 1.6; word-break: break-all; }
</style>
