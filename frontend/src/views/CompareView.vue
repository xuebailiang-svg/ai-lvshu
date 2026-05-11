<template>
  <div class="compare-view">
    <div class="page-header">
      <h2>多地址对比评估</h2>
      <p class="subtitle">同时评估 2-3 个候选地址，AI 输出对比分析和最终推荐排序</p>
    </div>

    <!-- 地址输入区 -->
    <div class="address-input-section">
      <div class="input-header">
        <span class="input-title">候选地址（2-3 个）</span>
        <el-button
          v-if="addresses.length < 3"
          type="primary"
          size="small"
          plain
          @click="addAddress"
        >
          + 添加地址
        </el-button>
      </div>
      <div class="address-list">
        <div v-for="(addr, idx) in addresses" :key="idx" class="address-item">
          <div class="addr-label">候选 {{ ['A', 'B', 'C'][idx] }}</div>
          <el-input
            v-model="addresses[idx]"
            :placeholder="`输入第 ${idx + 1} 个候选地址，如：西安市雁塔区小寨路88号`"
            clearable
            class="addr-input"
          />
          <el-button
            v-if="addresses.length > 2"
            text
            type="danger"
            size="small"
            @click="removeAddress(idx)"
          >
            删除
          </el-button>
        </div>
      </div>
      <div class="radius-row">
        <span class="radius-label">评估半径</span>
        <el-slider v-model="evaluateRadius" :min="500" :max="5000" :step="500" style="flex:1;margin:0 16px" />
        <span class="radius-val">{{ evaluateRadius }}m</span>
      </div>
      <el-button
        type="primary"
        size="large"
        class="compare-btn"
        :loading="comparing"
        :disabled="addresses.filter(a => a.trim()).length < 2"
        @click="startCompare"
      >
        <el-icon v-if="!comparing"><DataAnalysis /></el-icon>
        {{ comparing ? '对比评估中...' : '开始对比评估' }}
      </el-button>
    </div>

    <!-- 工作流日志 -->
    <div class="workflow-section" v-if="workflowSteps.length > 0 || comparing">
      <div class="workflow-header" @click="workflowExpanded = !workflowExpanded">
        <div class="wf-title">
          <span class="wf-dot" :class="{ active: comparing }"></span>
          <span>Agent 工作流</span>
          <el-tag size="small" type="info" style="margin-left:8px">{{ workflowSteps.length }} 步</el-tag>
        </div>
        <el-icon><ArrowUp v-if="workflowExpanded" /><ArrowDown v-else /></el-icon>
      </div>
      <div class="workflow-body" v-show="workflowExpanded" ref="workflowBodyRef">
        <div v-for="(step, idx) in workflowSteps" :key="idx" class="wf-step" :class="'wf-' + step.type">
          <span class="wf-icon">{{ stepIcons[step.type] || '•' }}</span>
          <div class="wf-content">
            <span class="wf-name">[{{ step.step }}]</span>
            <span class="wf-msg">{{ step.message }}</span>
          </div>
        </div>
        <div v-if="comparing" class="wf-step wf-thinking">
          <span class="wf-icon">⏳</span>
          <div class="wf-content"><span class="wf-msg">处理中...</span></div>
        </div>
      </div>
    </div>

    <!-- 对比结果 -->
    <div class="compare-results" v-if="results.length > 0">
      <!-- 推荐排名 -->
      <div class="rank-section">
        <div class="section-title">🏆 AI 推荐排名</div>
        <div class="rank-cards">
          <div
            v-for="(r, idx) in sortedResults"
            :key="idx"
            class="rank-card"
            :class="'rank-' + (idx + 1)"
          >
            <div class="rank-badge">{{ ['🥇', '🥈', '🥉'][idx] }}</div>
            <div class="rank-label">候选 {{ r.label }}</div>
            <div class="rank-score">{{ r.total_score }} 分</div>
            <div class="rank-grade" :class="'grade-' + r.grade">{{ r.grade_label }}</div>
            <div class="rank-address">{{ r.address }}</div>
          </div>
        </div>
      </div>

      <!-- 维度对比表格 -->
      <div class="compare-table-section">
        <div class="section-title">📊 维度得分对比</div>
        <el-table :data="dimensionTableData" border stripe>
          <el-table-column prop="dimension" label="评分维度" width="120" />
          <el-table-column
            v-for="(r, idx) in results"
            :key="idx"
            :label="`候选 ${r.label}`"
            align="center"
            min-width="120"
          >
            <template #default="{ row }">
              <div class="score-cell">
                <span
                  class="score-val"
                  :style="{ color: getScoreColor(row['score_' + idx]) }"
                >
                  {{ row['score_' + idx] }}
                </span>
                <span class="score-winner" v-if="isWinner(row, idx)">👑</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 雷达图对比 -->
      <div class="radar-section">
        <div class="section-title">🕸️ 六维雷达图对比</div>
        <div class="radar-container">
          <canvas ref="radarCanvas" width="500" height="360"></canvas>
          <div class="radar-legend">
            <div v-for="(r, idx) in results" :key="idx" class="legend-item">
              <span class="legend-dot" :style="{ background: radarColors[idx] }"></span>
              <span>候选 {{ r.label }}（{{ r.total_score }}分）</span>
            </div>
          </div>
        </div>
      </div>

      <!-- AI 综合分析 -->
      <div class="ai-analysis-section" v-if="aiAnalysis || comparing">
        <div class="section-title">🤖 AI 综合对比分析</div>
        <div v-if="comparing && !aiAnalysis" class="ai-generating">
          <span class="ai-cursor">▇</span> AI 正在生成对比分析报告...
        </div>
        <div
          v-if="aiAnalysis"
          class="ai-text markdown-body"
          v-html="renderMarkdown(aiAnalysis)"
        ></div>
      </div>

      <!-- 导出按钮 -->
      <div class="export-actions">
        <el-button type="primary" @click="exportCompareReport">导出对比报告</el-button>
        <el-button @click="resetCompare">重新对比</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import api from '@/api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

const addresses = ref<string[]>(['', ''])
const evaluateRadius = ref(1500)
const comparing = ref(false)
const results = ref<any[]>([])
const aiAnalysis = ref('')
const workflowSteps = ref<any[]>([])
const workflowExpanded = ref(true)
const workflowBodyRef = ref<HTMLElement | null>(null)
const radarCanvas = ref<HTMLCanvasElement | null>(null)

const radarColors = ['#6c63ff', '#ff6b6b', '#ffd93d']
const stepIcons: Record<string, string> = {
  thinking: '🤔', executing: '⚡', result: '✅', warning: '⚠️', error: '❌', final: '🎯'
}

const dimensionNames: Record<string, string> = {
  traffic: '交通便利', competition: '竞品分析', population: '客群密度',
  rent: '租金成本', facility: '配套设施', policy: '政策环境'
}

function addAddress() {
  if (addresses.value.length < 3) addresses.value.push('')
}

function removeAddress(idx: number) {
  if (addresses.value.length > 2) addresses.value.splice(idx, 1)
}

const sortedResults = computed(() => {
  return [...results.value].sort((a, b) => b.total_score - a.total_score)
})

const dimensionTableData = computed(() => {
  if (results.value.length === 0) return []
  const dims = results.value[0]?.dimensions || {}
  return Object.keys(dims).map(key => {
    const row: any = { dimension: dimensionNames[key] || key }
    results.value.forEach((r, idx) => {
      row['score_' + idx] = r.dimensions?.[key]?.score ?? '-'
    })
    return row
  })
})

function isWinner(row: any, idx: number): boolean {
  const scores = results.value.map((_, i) => Number(row['score_' + i]) || 0)
  const max = Math.max(...scores)
  return Number(row['score_' + idx]) === max && max > 0
}

function getScoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#e6a23c'
  return '#f56c6c'
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return DOMPurify.sanitize(marked.parse(text) as string)
  } catch {
    return text.replace(/\n/g, '<br>')
  }
}

async function startCompare() {
  const validAddresses = addresses.value.filter(a => a.trim())
  if (validAddresses.length < 2) {
    ElMessage.warning('请至少输入 2 个候选地址')
    return
  }

  comparing.value = true
  results.value = []
  aiAnalysis.value = ''
  workflowSteps.value = []

  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/evaluate/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ addresses: validAddresses, radius: evaluateRadius.value })
    })
    if (!response.ok) throw new Error('HTTP ' + response.status)

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') { comparing.value = false; break }
          try {
            const step = JSON.parse(raw)
            if (step.type === 'compare_result') {
              results.value = step.results || []
              await nextTick()
              drawCompareRadar()
            } else if (step.type === 'llm' && step.data?.content) {
              aiAnalysis.value += step.data.content
            } else {
              workflowSteps.value.push(step)
              await nextTick()
              if (workflowBodyRef.value) workflowBodyRef.value.scrollTop = workflowBodyRef.value.scrollHeight
            }
          } catch { /* ignore */ }
        }
      }
    }
  } catch (e: any) {
    ElMessage.error('对比评估失败：' + (e.message || '未知错误'))
  } finally {
    comparing.value = false
  }
}

function drawCompareRadar() {
  if (!radarCanvas.value || results.value.length === 0) return
  const ctx = radarCanvas.value.getContext('2d')
  if (!ctx) return

  const dims = Object.keys(results.value[0]?.dimensions || {})
  const n = dims.length
  const W = 500, H = 360, cx = W / 2, cy = H / 2, r = 120
  const angleStep = (Math.PI * 2) / n

  ctx.clearRect(0, 0, W, H)

  // 背景网格
  for (let level = 1; level <= 5; level++) {
    const lr = (r * level) / 5
    ctx.beginPath()
    for (let i = 0; i < n; i++) {
      const angle = i * angleStep - Math.PI / 2
      i === 0 ? ctx.moveTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle))
               : ctx.lineTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle))
    }
    ctx.closePath()
    ctx.strokeStyle = 'rgba(0,0,0,0.1)'
    ctx.lineWidth = 1
    ctx.stroke()
  }

  // 轴线和标签
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    ctx.beginPath(); ctx.moveTo(cx, cy)
    ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle))
    ctx.strokeStyle = 'rgba(0,0,0,0.15)'; ctx.stroke()
    ctx.fillStyle = '#555'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText(dimensionNames[dims[i]] || dims[i], cx + (r + 22) * Math.cos(angle), cy + (r + 22) * Math.sin(angle) + 4)
  }

  // 各候选地址的雷达多边形
  results.value.forEach((result, ri) => {
    const color = radarColors[ri]
    ctx.beginPath()
    dims.forEach((key, i) => {
      const score = (result.dimensions?.[key]?.score || 0) / 100
      const angle = i * angleStep - Math.PI / 2
      const val = score * r
      i === 0 ? ctx.moveTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle))
               : ctx.lineTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle))
    })
    ctx.closePath()
    ctx.fillStyle = color + '30'
    ctx.fill()
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.stroke()

    // 数据点
    dims.forEach((key, i) => {
      const score = (result.dimensions?.[key]?.score || 0) / 100
      const angle = i * angleStep - Math.PI / 2
      const val = score * r
      ctx.beginPath()
      ctx.arc(cx + val * Math.cos(angle), cy + val * Math.sin(angle), 4, 0, Math.PI * 2)
      ctx.fillStyle = color; ctx.fill()
    })
  })
}

function exportCompareReport() {
  if (results.value.length === 0) return
  let content = '# 多地址对比评估报告\n\n'
  content += `生成时间：${new Date().toLocaleString()}\n\n`
  content += '## 推荐排名\n\n'
  sortedResults.value.forEach((r, idx) => {
    content += `${idx + 1}. **候选 ${r.label}**（${r.address}）- ${r.total_score}分 ${r.grade_label}\n`
  })
  content += '\n## 维度得分对比\n\n'
  content += '| 维度 | ' + results.value.map(r => `候选 ${r.label}`).join(' | ') + ' |\n'
  content += '|------|' + results.value.map(() => '------').join('|') + '|\n'
  dimensionTableData.value.forEach(row => {
    content += `| ${row.dimension} | ` + results.value.map((_, i) => row['score_' + i]).join(' | ') + ' |\n'
  })
  if (aiAnalysis.value) {
    content += '\n## AI 综合分析\n\n' + aiAnalysis.value
  }
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `对比评估报告_${new Date().toLocaleDateString()}.md`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('报告已导出')
}

function resetCompare() {
  results.value = []
  aiAnalysis.value = ''
  workflowSteps.value = []
  addresses.value = ['', '']
}
</script>

<style scoped>
.compare-view { padding: 0; }
.page-header { margin-bottom: 24px; }
.page-header h2 { font-size: 22px; font-weight: 600; color: #1a1a2e; margin: 0 0 6px 0; }
.subtitle { color: #666; font-size: 14px; margin: 0; }

.address-input-section { background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; }
.input-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.input-title { font-size: 15px; font-weight: 600; color: #333; }
.address-list { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }
.address-item { display: flex; align-items: center; gap: 10px; }
.addr-label { font-size: 13px; font-weight: 700; color: #6c63ff; min-width: 50px; }
.addr-input { flex: 1; }
.radius-row { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; font-size: 13px; color: #555; }
.radius-val { min-width: 50px; color: #6c63ff; font-weight: 600; }
.compare-btn { width: 100%; }

.workflow-section { background: #fff; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
.workflow-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; cursor: pointer; border-bottom: 1px solid #f0f0f0; }
.wf-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: #333; }
.wf-dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
.wf-dot.active { background: #6c63ff; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
.workflow-body { max-height: 200px; overflow-y: auto; padding: 6px 0; }
.wf-step { display: flex; align-items: flex-start; gap: 8px; padding: 6px 16px; font-size: 13px; border-bottom: 1px solid #f8f8f8; }
.wf-icon { flex-shrink: 0; }
.wf-content { display: flex; gap: 6px; flex-wrap: wrap; }
.wf-name { color: #aaa; }
.wf-msg { color: #555; }
.wf-result .wf-msg { color: #67c23a; }
.wf-error .wf-msg { color: #f56c6c; }
.wf-thinking .wf-msg { color: #6c63ff; }

.compare-results { display: flex; flex-direction: column; gap: 20px; }
.section-title { font-size: 15px; font-weight: 600; color: #1a1a2e; margin-bottom: 14px; }

.rank-section { background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.rank-cards { display: flex; gap: 16px; }
.rank-card { flex: 1; padding: 16px; border-radius: 10px; border: 2px solid #e8e8e8; text-align: center; }
.rank-1 { border-color: #ffd700; background: #fffdf0; }
.rank-2 { border-color: #c0c0c0; background: #fafafa; }
.rank-3 { border-color: #cd7f32; background: #fdf8f5; }
.rank-badge { font-size: 28px; margin-bottom: 6px; }
.rank-label { font-size: 13px; color: #888; margin-bottom: 4px; }
.rank-score { font-size: 28px; font-weight: 700; color: #1a1a2e; }
.rank-grade { font-size: 13px; font-weight: 600; margin: 4px 0; }
.rank-address { font-size: 12px; color: #888; margin-top: 6px; }
.grade-A { color: #67c23a; }
.grade-B { color: #409eff; }
.grade-C { color: #e6a23c; }
.grade-D { color: #f56c6c; }

.compare-table-section { background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.score-cell { display: flex; align-items: center; justify-content: center; gap: 4px; }
.score-val { font-size: 15px; font-weight: 600; }
.score-winner { font-size: 14px; }

.radar-section { background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.radar-container { display: flex; align-items: center; gap: 24px; }
.radar-legend { display: flex; flex-direction: column; gap: 10px; }
.legend-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #555; }
.legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }

.ai-analysis-section { background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.ai-generating { font-size: 14px; color: #888; display: flex; align-items: center; gap: 8px; }
.ai-cursor { animation: blink 1s infinite; }
@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0; } }
.ai-text { font-size: 14px; line-height: 1.8; color: #333; }
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { color: #1a1a2e; margin: 12px 0 6px; }
.markdown-body :deep(strong) { color: #6c63ff; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 8px 0; }
.markdown-body :deep(th) { background: #f0f0ff; padding: 6px 10px; border: 1px solid #e0e0f0; }
.markdown-body :deep(td) { padding: 5px 10px; border: 1px solid #f0f0f0; }

.export-actions { display: flex; gap: 12px; padding: 4px 0; }
</style>
