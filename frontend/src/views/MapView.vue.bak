<template>
  <div class="map-view">
    <!-- 左侧控制面板 -->
    <div class="control-panel" :class="{ collapsed: panelCollapsed }">
      <div class="panel-header">
        <span class="panel-title">🎮 电竞馆选址助手</span>
        <el-button :icon="panelCollapsed ? ArrowRight : ArrowLeft" circle size="small" @click="panelCollapsed = !panelCollapsed" />
      </div>

      <div v-show="!panelCollapsed" class="panel-body">
        <!-- 评估输入 -->
        <div class="panel-section">
          <div class="section-title">📍 单点地址评估</div>
          <el-input v-model="evaluateAddress" placeholder="输入详细地址，如：西安市雁塔区小寨路88号" :rows="2" type="textarea" class="address-input" />
          <el-input v-model="evaluateCity" placeholder="城市（可选，如：西安）" size="small" style="margin-top:8px" />
          <div class="radius-row">
            <span>评估半径</span>
            <el-slider v-model="evaluateRadius" :min="500" :max="5000" :step="500" style="flex:1;margin:0 12px" />
            <span>{{ evaluateRadius }}m</span>
          </div>
          <el-button type="primary" :loading="evaluating" :icon="Search" @click="startEvaluation" style="width:100%;margin-top:12px">
            {{ evaluating ? '评估中...' : '开始评估' }}
          </el-button>
        </div>

        <!-- 地图工具 -->
        <div class="panel-section">
          <div class="section-title">🗺️ 地图工具</div>
          <div class="tool-buttons">
            <el-button :type="mapTool === 'click' ? 'primary' : 'default'" size="small" @click="setMapTool('click')">点击选址</el-button>
            <el-button :type="mapTool === 'rectangle' ? 'primary' : 'default'" size="small" @click="setMapTool('rectangle')">框选区域</el-button>
          </div>
          <el-button size="small" style="width:100%;margin-top:8px" @click="clearMapOverlays">清除标记</el-button>
        </div>

        <!-- 图层控制 -->
        <div class="panel-section">
          <div class="section-title">📊 图层显示</div>
          <div class="layer-controls">
            <el-checkbox v-model="showChainStores" @change="toggleChainStores">连锁门店（含辐射圈）</el-checkbox>
            <el-checkbox v-model="showCompetitors" @change="toggleCompetitors">竞品分布</el-checkbox>
          </div>
        </div>

        <!-- 评估结果摘要 -->
        <div v-if="evaluationResult" class="panel-section result-section">
          <div class="section-title">📋 评估结果</div>
          <div class="score-display">
            <div class="score-circle" :style="{ borderColor: evaluationResult.grade_color }">
              <div class="score-number" :style="{ color: evaluationResult.grade_color }">{{ evaluationResult.total_score }}</div>
              <div class="score-grade">{{ evaluationResult.grade }}</div>
            </div>
            <div class="score-info">
              <div class="grade-label" :style="{ color: evaluationResult.grade_color }">{{ evaluationResult.grade_label }}</div>
              <div class="score-address">{{ evaluationResult.address }}</div>
            </div>
          </div>
          <div class="radar-container">
            <canvas ref="radarCanvas" width="220" height="200"></canvas>
          </div>
          <div class="dimension-list">
            <div v-for="(dim, key) in evaluationResult.dimensions" :key="key" class="dimension-item">
              <span class="dim-name">{{ dimensionNames[String(key)] }}</span>
              <el-progress :percentage="dim.score" :color="getScoreColor(dim.score)" :stroke-width="8" style="flex:1;margin:0 8px" />
              <span class="dim-score">{{ dim.score }}</span>
            </div>
          </div>
          <el-button type="success" size="small" style="width:100%;margin-top:8px" @click="showFullReport = true">查看完整报告</el-button>
        </div>
      </div>
    </div>

    <!-- 地图容器 -->
    <div id="amap-container" class="map-container">
      <div v-if="!mapLoaded" class="map-loading">
        <el-icon class="loading-icon"><Loading /></el-icon>
        <span>地图加载中，请配置高德 API Key...</span>
      </div>
    </div>

    <!-- 工作流日志面板（Dify 风格） -->
    <div v-if="showWorkflowLog" class="workflow-panel">
      <div class="workflow-header">
        <span>⚡ Agent 工作流日志</span>
        <el-button :icon="Close" circle size="small" @click="showWorkflowLog = false" />
      </div>
      <div class="workflow-steps" ref="workflowStepsRef">
        <div v-for="(step, idx) in workflowSteps" :key="idx" class="workflow-step" :class="`step-${step.type}`">
          <span class="step-icon">{{ stepIcons[step.type] || '•' }}</span>
          <div class="step-content">
            <span class="step-name">[{{ step.step }}]</span>
            <span class="step-message">{{ step.message }}</span>
          </div>
        </div>
        <div v-if="evaluating" class="workflow-step step-thinking">
          <span class="step-icon">⏳</span>
          <div class="step-content"><span class="step-message">处理中...</span></div>
        </div>
      </div>
    </div>

    <!-- 完整报告对话框 -->
    <el-dialog v-model="showFullReport" title="📊 智能选址评估报告" width="700px" :close-on-click-modal="false">
      <div v-if="evaluationResult" class="full-report">
        <div class="report-header">
          <div class="report-address">📍 {{ evaluationResult.address }}</div>
          <div class="report-score" :style="{ color: evaluationResult.grade_color }">
            综合评分：{{ evaluationResult.total_score }} 分（{{ evaluationResult.grade_label }}）
          </div>
        </div>
        <el-divider />
        <div class="report-dimensions">
          <h4>各维度评分详情</h4>
          <el-table :data="reportDimensionData" border stripe size="small">
            <el-table-column prop="name" label="评分维度" width="100" />
            <el-table-column label="得分" width="80">
              <template #default="{ row }">
                <span :style="{ color: getScoreColor(row.score), fontWeight: 'bold' }">{{ row.score }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="weight" label="权重" width="70" />
            <el-table-column prop="detail" label="详情说明" />
          </el-table>
        </div>
        <el-divider />
        <div class="report-workflow">
          <h4>评估工作流日志</h4>
          <div class="workflow-log-full">
            <div v-for="(step, idx) in evaluationResult.log_steps" :key="idx" class="log-entry" :class="`log-${step.type}`">
              <span class="log-icon">{{ stepIcons[step.type] || '•' }}</span>
              <span class="log-step">[{{ step.step }}]</span>
              <span class="log-msg">{{ step.message }}</span>
            </div>
          </div>
        </div>
        <div v-if="!evaluationResult.has_amap_key" class="report-warning">
          <el-alert title="提示：当前使用模拟数据" type="warning" description="请在系统配置中填写高德 API Key，以获取真实的周边数据和更准确的评估结果。" show-icon :closable="false" />
        </div>
      </div>
      <template #footer>
        <el-button @click="showFullReport = false">关闭</el-button>
        <el-button type="primary" @click="exportReport">导出报告</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, ArrowLeft, ArrowRight, Close, Loading } from '@element-plus/icons-vue'
import api from '@/api'

const panelCollapsed = ref(false)
const evaluateAddress = ref('')
const evaluateCity = ref('')
const evaluateRadius = ref(1500)
const evaluating = ref(false)
const evaluationResult = ref<any>(null)
const showFullReport = ref(false)
const showWorkflowLog = ref(false)
const workflowSteps = ref<any[]>([])
const workflowStepsRef = ref<HTMLElement | null>(null)
const radarCanvas = ref<HTMLCanvasElement | null>(null)
const mapLoaded = ref(false)

const mapTool = ref('click')
const showChainStores = ref(true)
const showCompetitors = ref(false)

let mapInstance: any = null
let chainStoreMarkers: any[] = []
let evaluateMarker: any = null
let drawingManager: any = null
let currentOverlay: any = null

const dimensionNames: Record<string, string> = {
  traffic: '交通人流', competition: '竞品分析', population: '目标客群',
  rent: '租金成本', facility: '配套设施', policy: '政策环境'
}

const stepIcons: Record<string, string> = {
  thinking: '💭', executing: '⚙️', result: '✅', warning: '⚠️', error: '❌', final: '🎯'
}

const reportDimensionData = computed(() => {
  if (!evaluationResult.value) return []
  return Object.entries(evaluationResult.value.dimensions).map(([key, dim]: [string, any]) => ({
    name: dimensionNames[key] || key,
    score: dim.score,
    weight: `${dim.weight}%`,
    detail: dim.detail
  }))
})

async function getAmapKey(): Promise<string> {
  try {
    const res = await api.get('/system/config/amap_api_key')
    return res.data?.config_value || ''
  } catch {
    return ''
  }
}

async function initMap() {
  const amapKey = await getAmapKey()
  if (!amapKey) {
    ElMessage.warning('未配置高德 API Key，地图功能受限。请在系统配置中填写。')
    return
  }

  await new Promise<void>((resolve) => {
    if ((window as any).AMap) { resolve(); return }
    const script = document.createElement('script')
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${amapKey}&plugin=AMap.Scale,AMap.ToolBar,AMap.MouseTool,AMap.Geocoder`
    script.onload = () => resolve()
    script.onerror = () => { ElMessage.error('高德地图 JS API 加载失败'); resolve() }
    document.head.appendChild(script)
  })

  const AMap = (window as any).AMap
  if (!AMap) return

  mapInstance = new AMap.Map('amap-container', {
    zoom: 14,
    center: [108.9398, 34.3416],
    mapStyle: 'amap://styles/dark',
    resizeEnable: true
  })

  AMap.plugin(['AMap.ToolBar', 'AMap.Scale', 'AMap.MouseTool'], () => {
    mapInstance.addControl(new AMap.ToolBar({ position: 'RB' }))
    mapInstance.addControl(new AMap.Scale())
    drawingManager = new AMap.MouseTool(mapInstance)
  })

  mapInstance.on('click', (e: any) => {
    if (mapTool.value === 'click') {
      handleMapClick(e.lnglat.lng, e.lnglat.lat)
    }
  })

  mapLoaded.value = true
  if (showChainStores.value) await loadChainStores()
}

async function loadChainStores() {
  try {
    const res = await api.get('/evaluate/stores')
    const { stores } = res.data
    chainStoreMarkers.forEach(m => mapInstance?.remove(m))
    chainStoreMarkers = []
    if (!mapInstance || !(window as any).AMap) return
    const AMap = (window as any).AMap

    stores.forEach((store: any) => {
      const marker = new AMap.Marker({
        position: [store.longitude, store.latitude],
        title: store.name,
        icon: new AMap.Icon({
          size: new AMap.Size(32, 32),
          image: store.is_success === false
            ? 'https://webapi.amap.com/theme/v1.3/markers/n/mark_r.png'
            : 'https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png',
          imageSize: new AMap.Size(32, 32)
        })
      })
      const circle = new AMap.Circle({
        center: [store.longitude, store.latitude],
        radius: 1500,
        fillColor: store.is_success === false ? '#f56c6c' : '#409eff',
        fillOpacity: 0.08,
        strokeColor: store.is_success === false ? '#f56c6c' : '#409eff',
        strokeOpacity: 0.4,
        strokeWeight: 1,
        strokeStyle: 'dashed'
      })
      marker.on('click', () => {
        const info = new AMap.InfoWindow({
          content: `<div style="padding:12px;min-width:200px"><div style="font-weight:bold;font-size:15px;margin-bottom:8px">${store.name}</div><div style="color:#666;font-size:13px">${store.address}</div><div style="margin-top:8px;font-size:13px">面积：${store.area_sqm || '-'} ㎡ &nbsp; 机器数：${store.machine_count || '-'} 台</div><div style="margin-top:4px"><span style="color:${store.is_success === false ? '#f56c6c' : '#67c23a'};font-weight:bold">${store.is_success === false ? '❌ 已关店/失败' : store.is_success === true ? '✅ 运营成功' : '🔵 运营中'}</span></div></div>`,
          offset: new AMap.Pixel(0, -30)
        })
        info.open(mapInstance, [store.longitude, store.latitude])
      })
      mapInstance.add([marker, circle])
      chainStoreMarkers.push(marker, circle)
    })
    if (stores.length > 0) ElMessage.success(`已加载 ${stores.length} 家连锁门店`)
  } catch (e) { console.error('加载连锁门店失败', e) }
}

function setMapTool(tool: string) {
  mapTool.value = tool
  if (!drawingManager) return
  drawingManager.close(false)
  if (tool === 'rectangle') {
    drawingManager.rectangle({ fillColor: '#409eff', fillOpacity: 0.15, strokeColor: '#409eff', strokeWeight: 2 })
    drawingManager.on('draw', (e: any) => {
      currentOverlay = e.obj
      const bounds = e.obj.getBounds()
      const center = bounds.getCenter()
      handleMapClick(center.lng, center.lat)
    })
  }
}

function clearMapOverlays() {
  if (evaluateMarker) { mapInstance?.remove(evaluateMarker); evaluateMarker = null }
  if (currentOverlay) { mapInstance?.remove(currentOverlay); currentOverlay = null }
  evaluationResult.value = null
  workflowSteps.value = []
}

function toggleChainStores(val: boolean) {
  if (val) loadChainStores()
  else { chainStoreMarkers.forEach(m => mapInstance?.remove(m)); chainStoreMarkers = [] }
}

function toggleCompetitors(val: boolean) {
  ElMessage.info(val ? '竞品数据将在评估时自动显示' : '已隐藏竞品标记')
}

async function handleMapClick(lng: number, lat: number) {
  if (!mapInstance || !(window as any).AMap) return
  const AMap = (window as any).AMap
  if (evaluateMarker) mapInstance.remove(evaluateMarker)
  evaluateMarker = new AMap.Marker({
    position: [lng, lat],
    icon: new AMap.Icon({ size: new AMap.Size(36, 36), image: 'https://webapi.amap.com/theme/v1.3/markers/n/mark_g.png', imageSize: new AMap.Size(36, 36) }),
    animation: 'AMAP_ANIMATION_DROP'
  })
  mapInstance.add(evaluateMarker)
  AMap.plugin('AMap.Geocoder', () => {
    const geocoder = new AMap.Geocoder()
    geocoder.getAddress([lng, lat], (status: string, result: any) => {
      if (status === 'complete' && result.regeocode) {
        evaluateAddress.value = result.regeocode.formattedAddress
        evaluateCity.value = result.regeocode.addressComponent?.city || ''
      }
    })
  })
}

async function startEvaluation() {
  if (!evaluateAddress.value.trim()) { ElMessage.warning('请输入评估地址或在地图上点击选址'); return }
  evaluating.value = true
  showWorkflowLog.value = true
  workflowSteps.value = []
  evaluationResult.value = null

  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/evaluate/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ address: evaluateAddress.value, city: evaluateCity.value || undefined, radius: evaluateRadius.value })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)

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
          const data = line.slice(6).trim()
          if (data === '[DONE]') { evaluating.value = false; break }
          try {
            const step = JSON.parse(data)
            if (step.type === 'final') {
              evaluationResult.value = step
              await nextTick()
              drawRadarChart()
              if (step.longitude && step.latitude && mapInstance) mapInstance.setCenter([step.longitude, step.latitude])
            } else {
              workflowSteps.value.push(step)
              await nextTick()
              if (workflowStepsRef.value) workflowStepsRef.value.scrollTop = workflowStepsRef.value.scrollHeight
            }
          } catch {}
        }
      }
    }
  } catch (e: any) {
    ElMessage.error('评估请求失败：' + (e.message || '未知错误'))
  } finally {
    evaluating.value = false
  }
}

function drawRadarChart() {
  if (!radarCanvas.value || !evaluationResult.value) return
  const ctx = radarCanvas.value.getContext('2d')
  if (!ctx) return
  const dims = evaluationResult.value.dimensions
  const labels = Object.keys(dims).map((k: string) => dimensionNames[k] || k)
  const scores = Object.values(dims).map((d: any) => d.score / 100)
  const cx = 110, cy = 100, r = 75, n = labels.length
  const angleStep = (Math.PI * 2) / n
  ctx.clearRect(0, 0, 220, 200)
  for (let level = 1; level <= 5; level++) {
    const lr = (r * level) / 5
    ctx.beginPath()
    for (let i = 0; i < n; i++) {
      const angle = i * angleStep - Math.PI / 2
      i === 0 ? ctx.moveTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle)) : ctx.lineTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle))
    }
    ctx.closePath(); ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.stroke()
  }
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle))
    ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.stroke()
  }
  ctx.beginPath()
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    const val = scores[i] * r
    i === 0 ? ctx.moveTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle)) : ctx.lineTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle))
  }
  ctx.closePath(); ctx.fillStyle = 'rgba(64,158,255,0.35)'; ctx.fill()
  ctx.strokeStyle = '#409eff'; ctx.lineWidth = 2; ctx.stroke()
  ctx.fillStyle = '#ccc'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    ctx.fillText(labels[i], cx + (r + 16) * Math.cos(angle), cy + (r + 16) * Math.sin(angle) + 4)
  }
}

function getScoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#409eff'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

function exportReport() {
  if (!evaluationResult.value) return
  const blob = new Blob([JSON.stringify(evaluationResult.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `选址评估报告_${evaluationResult.value.address}_${new Date().toLocaleDateString()}.json`
  a.click(); URL.revokeObjectURL(url)
}

onMounted(async () => { await nextTick(); await initMap() })
onUnmounted(() => { mapInstance?.destroy() })
watch(evaluationResult, (val) => { if (val) nextTick(() => drawRadarChart()) })
</script>

<style scoped>
.map-view { position: relative; width: 100%; height: calc(100vh - 60px); display: flex; overflow: hidden; }
.map-container { flex: 1; height: 100%; position: relative; }
.map-loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #0a0a1e; color: #888; gap: 12px; font-size: 14px; }
.loading-icon { font-size: 32px; animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.control-panel { width: 320px; height: 100%; background: rgba(15,15,30,0.97); border-right: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; transition: width 0.3s; overflow: hidden; z-index: 100; }
.control-panel.collapsed { width: 40px; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 12px 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.1); flex-shrink: 0; }
.panel-title { font-size: 14px; font-weight: 600; color: #e0e0ff; white-space: nowrap; }
.panel-body { flex: 1; overflow-y: auto; padding: 12px; }
.panel-section { margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); }
.section-title { font-size: 11px; font-weight: 600; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
.address-input :deep(.el-textarea__inner) { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.15); color: #e0e0ff; font-size: 13px; }
.radius-row { display: flex; align-items: center; margin-top: 10px; font-size: 12px; color: #888; }
.tool-buttons { display: flex; gap: 6px; flex-wrap: wrap; }
.layer-controls { display: flex; flex-direction: column; gap: 8px; }
.layer-controls :deep(.el-checkbox__label) { color: #ccc; font-size: 13px; }
.result-section { border-bottom: none; }
.score-display { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.score-circle { width: 64px; height: 64px; border-radius: 50%; border: 3px solid; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; background: rgba(0,0,0,0.3); }
.score-number { font-size: 20px; font-weight: 700; line-height: 1; }
.score-grade { font-size: 12px; color: #888; margin-top: 2px; }
.score-info { flex: 1; min-width: 0; }
.grade-label { font-size: 16px; font-weight: 700; }
.score-address { font-size: 11px; color: #888; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.radar-container { display: flex; justify-content: center; margin: 8px 0; background: rgba(255,255,255,0.03); border-radius: 8px; padding: 8px; }
.dimension-list { display: flex; flex-direction: column; gap: 6px; }
.dimension-item { display: flex; align-items: center; gap: 4px; }
.dim-name { font-size: 11px; color: #888; width: 52px; flex-shrink: 0; }
.dim-score { font-size: 12px; color: #ccc; width: 28px; text-align: right; flex-shrink: 0; }
.workflow-panel { position: absolute; bottom: 20px; right: 20px; width: 400px; max-height: 300px; background: rgba(10,10,25,0.97); border: 1px solid rgba(64,158,255,0.3); border-radius: 10px; display: flex; flex-direction: column; z-index: 200; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }
.workflow-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.08); font-size: 13px; font-weight: 600; color: #409eff; }
.workflow-steps { flex: 1; overflow-y: auto; padding: 8px 12px; }
.workflow-step { display: flex; align-items: flex-start; gap: 8px; padding: 4px 0; font-size: 12px; line-height: 1.5; border-bottom: 1px solid rgba(255,255,255,0.04); }
.step-icon { flex-shrink: 0; width: 18px; }
.step-content { flex: 1; min-width: 0; }
.step-name { color: #888; margin-right: 6px; }
.step-thinking .step-message { color: #e6a23c; }
.step-executing .step-message { color: #409eff; }
.step-result .step-message { color: #67c23a; }
.step-warning .step-message { color: #e6a23c; }
.step-error .step-message { color: #f56c6c; }
.report-header { margin-bottom: 12px; }
.report-address { font-size: 14px; color: #666; margin-bottom: 6px; }
.report-score { font-size: 20px; font-weight: 700; }
.workflow-log-full { max-height: 200px; overflow-y: auto; background: #f8f9fa; border-radius: 6px; padding: 10px; }
.log-entry { display: flex; gap: 6px; font-size: 12px; line-height: 1.6; padding: 2px 0; }
.log-icon { flex-shrink: 0; }
.log-step { color: #888; flex-shrink: 0; }
.log-thinking .log-msg { color: #e6a23c; }
.log-executing .log-msg { color: #409eff; }
.log-result .log-msg { color: #67c23a; }
.log-warning .log-msg { color: #e6a23c; }
.log-error .log-msg { color: #f56c6c; }
.report-warning { margin-top: 12px; }
</style>
