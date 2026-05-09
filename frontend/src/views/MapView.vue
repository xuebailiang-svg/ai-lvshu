<template>
  <div class="map-page">
    <!-- 左侧控制面板 -->
    <div class="control-panel">
      <div class="panel-header">
        <el-icon class="header-icon"><Location /></el-icon>
        <span>智能选址地图</span>
      </div>
      <div class="panel-section">
        <div class="section-title">地址评估</div>
        <el-input v-model="evaluateAddress" placeholder="输入地址，如：西安市雁塔区小寨路88号" clearable @keyup.enter="startEvaluation">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="radius-row">
          <span class="radius-label">评估半径</span>
          <el-slider v-model="evaluateRadius" :min="500" :max="5000" :step="500" style="flex:1;margin:0 10px" />
          <span class="radius-val">{{ evaluateRadius }}m</span>
        </div>
        <el-button type="primary" class="evaluate-btn" :loading="evaluating" @click="startEvaluation">
          <el-icon v-if="!evaluating"><DataAnalysis /></el-icon>
          {{ evaluating ? '评估中...' : '开始评估' }}
        </el-button>
      </div>
      <div class="panel-section">
        <div class="section-title">地图工具</div>
        <div class="tool-buttons">
          <el-button :type="mapTool === 'click' ? 'primary' : 'default'" size="small" @click="setMapTool('click')">
            <el-icon><Aim /></el-icon> 点击选址
          </el-button>
          <el-button :type="mapTool === 'rectangle' ? 'primary' : 'default'" size="small" @click="setMapTool('rectangle')">
            <el-icon><ScaleToOriginal /></el-icon> 框选
          </el-button>
        </div>
        <el-button size="small" style="width:100%;margin-top:8px" @click="clearMapOverlays">
          <el-icon><Delete /></el-icon> 清除标记
        </el-button>
      </div>
      <div class="panel-section">
        <div class="section-title">图层</div>
        <div class="layer-item">
          <el-switch v-model="showChainStores" size="small" @change="toggleChainStores" />
          <span class="layer-label">连锁门店（含辐射圈）</span>
        </div>
      </div>
      <div class="panel-section">
        <div class="section-title">图例</div>
        <div class="legend-item"><span class="legend-dot success"></span><span>运营中门店</span></div>
        <div class="legend-item"><span class="legend-dot failed"></span><span>已关闭门店</span></div>
        <div class="legend-item"><span class="legend-dot selected"></span><span>当前评估点</span></div>
      </div>
      <div class="panel-section" v-if="storeStats.total > 0">
        <div class="section-title">门店统计</div>
        <div class="store-stats">
          <div class="stat-item"><span class="stat-num">{{ storeStats.total }}</span><span class="stat-label">总门店</span></div>
          <div class="stat-item"><span class="stat-num" style="color:#67c23a">{{ storeStats.success }}</span><span class="stat-label">运营中</span></div>
          <div class="stat-item"><span class="stat-num" style="color:#f56c6c">{{ storeStats.failed }}</span><span class="stat-label">已关闭</span></div>
        </div>
      </div>
    </div>

    <!-- 地图容器 -->
    <div class="map-container">
      <div id="amap-container" ref="mapContainer"></div>
      <div v-if="!mapLoaded" class="map-placeholder">
        <div class="placeholder-inner">
          <el-icon style="font-size:56px;color:#6c63ff"><MapLocation /></el-icon>
          <p style="color:#999;margin:16px 0 8px">高德地图未加载</p>
          <p style="color:#666;font-size:13px">请前往「系统配置 → 地图 API」填写高德 JS API Key</p>
          <el-button type="primary" size="small" style="margin-top:16px" @click="$router.push('/settings')">去配置</el-button>
        </div>
      </div>
    </div>

    <!-- 右侧评估结果面板 -->
    <transition name="slide-right">
      <div class="result-panel" v-if="showResult">
        <div class="result-header">
          <div class="result-title"><el-icon><DataAnalysis /></el-icon><span>评估报告</span></div>
          <el-button text @click="showResult = false" style="color:#888"><el-icon><Close /></el-icon></el-button>
        </div>
        <div class="result-address">
          <el-icon style="flex-shrink:0;margin-top:2px"><Location /></el-icon>
          <span>{{ evaluationResult?.address || evaluateAddress }}</span>
        </div>
        <div class="score-overview" v-if="evaluationResult">
          <div class="score-circle" :class="gradeClass">
            <span class="score-num">{{ evaluationResult.total_score }}</span>
            <span class="score-unit">分</span>
          </div>
          <div class="score-meta">
            <div class="grade-text" :class="gradeClass">{{ evaluationResult.grade_label }}</div>
            <div class="grade-sub">综合选址评分</div>
            <div class="grade-badge" :class="gradeClass">{{ evaluationResult.grade }}</div>
          </div>
        </div>
        <div class="radar-section" v-if="evaluationResult && evaluationResult.dimensions">
          <div class="section-label">六维评分雷达图</div>
          <canvas ref="radarCanvas" width="268" height="210"></canvas>
        </div>
        <div class="dimension-scores" v-if="evaluationResult && evaluationResult.dimensions">
          <div class="section-label">维度详情</div>
          <div v-for="(dim, key) in evaluationResult.dimensions" :key="key" class="dim-item">
            <div class="dim-header">
              <span class="dim-name">{{ dimensionIcons[String(key)] }} {{ dimensionNames[String(key)] }}</span>
              <span class="dim-score" :style="{ color: getScoreColor(dim.score) }">{{ dim.score }}分</span>
            </div>
            <el-progress :percentage="dim.score" :color="getScoreColor(dim.score)" :stroke-width="5" :show-text="false" />
            <div class="dim-detail">{{ dim.detail }}</div>
          </div>
        </div>
        <div class="ai-section" v-if="aiContent">
          <div class="section-label">AI 选址建议</div>
          <div class="ai-text">{{ aiContent }}</div>
        </div>
        <div class="result-actions" v-if="evaluationResult">
          <el-button size="small" type="primary" @click="exportReport">导出报告</el-button>
          <el-button size="small" @click="clearMapOverlays">清除重置</el-button>
        </div>
      </div>
    </transition>

    <!-- 工作流日志面板 -->
    <transition name="slide-up">
      <div class="workflow-panel" v-if="workflowSteps.length > 0 || evaluating">
        <div class="workflow-header" @click="workflowExpanded = !workflowExpanded">
          <div class="wf-title">
            <span class="wf-dot" :class="{ active: evaluating }"></span>
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
          <div v-if="evaluating" class="wf-step wf-thinking">
            <span class="wf-icon">⏳</span>
            <div class="wf-content"><span class="wf-msg">处理中...</span></div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Location, Search, DataAnalysis, Aim, ScaleToOriginal, Delete, Close, MapLocation, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import api from '@/api'

const router = useRouter()
const mapContainer = ref<HTMLDivElement>()
const radarCanvas = ref<HTMLCanvasElement>()
const workflowBodyRef = ref<HTMLElement>()
const evaluateAddress = ref('')
const evaluateRadius = ref(1500)
const evaluating = ref(false)
const showResult = ref(false)
const showChainStores = ref(true)
const mapTool = ref('click')
const workflowExpanded = ref(true)
const mapLoaded = ref(false)
const evaluationResult = ref<any>(null)
const aiContent = ref('')
const workflowSteps = ref<any[]>([])
const storeStats = ref({ total: 0, success: 0, failed: 0 })

let mapInstance: any = null
let chainStoreMarkers: any[] = []
let evaluateMarker: any = null
let drawingManager: any = null
let currentOverlay: any = null

const dimensionNames: Record<string, string> = {
  traffic: '交通人流', competition: '竞品分析', population: '目标客群',
  rent: '租金成本', facility: '配套设施', policy: '政策环境'
}
const dimensionIcons: Record<string, string> = {
  traffic: '🚇', competition: '🏪', population: '👥',
  rent: '💰', facility: '🏢', policy: '📋'
}
const stepIcons: Record<string, string> = {
  thinking: '💭', executing: '⚙️', result: '✅', warning: '⚠️',
  error: '❌', final: '🎯', score: '📊', llm: '🤖'
}

const gradeClass = computed(() => {
  if (!evaluationResult.value) return ''
  const s = evaluationResult.value.total_score
  if (s >= 80) return 'excellent'
  if (s >= 65) return 'good'
  if (s >= 50) return 'medium'
  return 'poor'
})

function getScoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 65) return '#409eff'
  if (score >= 50) return '#e6a23c'
  return '#f56c6c'
}

async function initMap() {
  try {
    const res = await api.get('/system/config/')
    const configs = res.data as any[]
    const jsKey = configs.find((c: any) => c.config_key === 'amap_js_key')?.config_value
    const secCode = configs.find((c: any) => c.config_key === 'amap_security_code')?.config_value
    if (!jsKey || jsKey.startsWith('****')) return
    if (secCode && !secCode.startsWith('****')) {
      (window as any)._AMapSecurityConfig = { securityJsCode: secCode }
    }
    await new Promise<void>((resolve, reject) => {
      if ((window as any).AMap) { resolve(); return }
      const script = document.createElement('script')
      script.src = 'https://webapi.amap.com/maps?v=2.0&key=' + jsKey + '&plugin=AMap.Scale,AMap.ToolBar,AMap.MouseTool,AMap.Geocoder'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('高德地图脚本加载失败'))
      document.head.appendChild(script)
    })
    const AMap = (window as any).AMap
    mapInstance = new AMap.Map('amap-container', {
      zoom: 13, center: [108.9398, 34.3416], mapStyle: 'amap://styles/dark', resizeEnable: true
    })
    AMap.plugin(['AMap.ToolBar', 'AMap.Scale', 'AMap.MouseTool'], () => {
      mapInstance.addControl(new AMap.ToolBar({ position: 'RB' }))
      mapInstance.addControl(new AMap.Scale())
      drawingManager = new AMap.MouseTool(mapInstance)
    })
    mapInstance.on('click', (e: any) => {
      if (mapTool.value === 'click') handleMapClick(e.lnglat.lng, e.lnglat.lat)
    })
    mapLoaded.value = true
    if (showChainStores.value) await loadChainStores()
  } catch (e) { console.warn('地图初始化失败', e) }
}

async function loadChainStores() {
  try {
    const res = await api.get('/evaluate/stores')
    const stores = res.data.stores || []
    storeStats.value = {
      total: stores.length,
      success: stores.filter((s: any) => s.is_success !== false).length,
      failed: stores.filter((s: any) => s.is_success === false).length,
    }
    chainStoreMarkers.forEach(m => mapInstance?.remove(m))
    chainStoreMarkers = []
    if (!mapInstance || !(window as any).AMap) return
    const AMap = (window as any).AMap
    stores.forEach((store: any) => {
      const marker = new AMap.Marker({
        position: [store.longitude, store.latitude], title: store.name,
        icon: new AMap.Icon({
          size: new AMap.Size(32, 32),
          image: store.is_success === false
            ? 'https://webapi.amap.com/theme/v1.3/markers/n/mark_r.png'
            : 'https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png',
          imageSize: new AMap.Size(32, 32)
        })
      })
      const circle = new AMap.Circle({
        center: [store.longitude, store.latitude], radius: 1500,
        fillColor: store.is_success === false ? '#f56c6c' : '#409eff', fillOpacity: 0.06,
        strokeColor: store.is_success === false ? '#f56c6c' : '#409eff', strokeOpacity: 0.3,
        strokeWeight: 1, strokeStyle: 'dashed'
      })
      marker.on('click', () => {
        const info = new AMap.InfoWindow({
          content: '<div style="padding:12px;min-width:180px"><b>' + store.name + '</b><div style="color:#666;font-size:12px;margin-top:4px">' + store.address + '</div><div style="margin-top:6px;font-weight:600;color:' + (store.is_success === false ? '#f56c6c' : '#67c23a') + '">' + (store.is_success === false ? '❌ 已关店' : '✅ 运营中') + '</div></div>',
          offset: new AMap.Pixel(0, -30)
        })
        info.open(mapInstance, [store.longitude, store.latitude])
      })
      mapInstance.add([marker, circle])
      chainStoreMarkers.push(marker, circle)
    })
    if (stores.length > 0) ElMessage.success('已加载 ' + stores.length + ' 家连锁门店')
  } catch (e) { console.error('加载门店失败', e) }
}

function setMapTool(tool: string) {
  mapTool.value = tool
  if (!drawingManager) return
  drawingManager.close(false)
  if (tool === 'rectangle') {
    drawingManager.rectangle({ fillColor: '#6c63ff', fillOpacity: 0.12, strokeColor: '#6c63ff', strokeWeight: 2 })
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
  evaluationResult.value = null; aiContent.value = ''; workflowSteps.value = []
  showResult.value = false; evaluateAddress.value = ''
}

function toggleChainStores(val: boolean) {
  if (val) loadChainStores()
  else { chainStoreMarkers.forEach(m => mapInstance?.remove(m)); chainStoreMarkers = [] }
}

async function handleMapClick(lng: number, lat: number) {
  if (!mapInstance || !(window as any).AMap) return
  const AMap = (window as any).AMap
  if (evaluateMarker) mapInstance.remove(evaluateMarker)
  evaluateMarker = new AMap.Marker({
    position: [lng, lat],
    icon: new AMap.Icon({
      size: new AMap.Size(36, 36),
      image: 'https://webapi.amap.com/theme/v1.3/markers/n/mark_g.png',
      imageSize: new AMap.Size(36, 36)
    }),
    animation: 'AMAP_ANIMATION_DROP'
  })
  mapInstance.add(evaluateMarker)
  AMap.plugin('AMap.Geocoder', () => {
    const geocoder = new AMap.Geocoder()
    geocoder.getAddress([lng, lat], (status: string, result: any) => {
      if (status === 'complete' && result.regeocode) {
        evaluateAddress.value = result.regeocode.formattedAddress
      }
    })
  })
}

async function startEvaluation() {
  if (!evaluateAddress.value.trim()) { ElMessage.warning('请输入评估地址或在地图上点击选址'); return }
  evaluating.value = true; showResult.value = true; workflowSteps.value = []
  evaluationResult.value = null; aiContent.value = ''
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/evaluate/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ address: evaluateAddress.value, radius: evaluateRadius.value })
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
          if (raw === '[DONE]') { evaluating.value = false; break }
          try {
            const step = JSON.parse(raw)
            if (step.type === 'final') {
              evaluationResult.value = step
              await nextTick(); drawRadarChart()
              if (step.longitude && step.latitude && mapInstance) mapInstance.setCenter([step.longitude, step.latitude])
            } else if (step.type === 'llm' && step.data?.content) {
              aiContent.value += step.data.content
            } else {
              workflowSteps.value.push(step)
              await nextTick()
              if (workflowBodyRef.value) workflowBodyRef.value.scrollTop = workflowBodyRef.value.scrollHeight
            }
          } catch { /* ignore parse errors */ }
        }
      }
    }
  } catch (e: any) {
    ElMessage.error('评估请求失败：' + (e.message || '未知错误'))
  } finally { evaluating.value = false }
}

function drawRadarChart() {
  if (!radarCanvas.value || !evaluationResult.value?.dimensions) return
  const ctx = radarCanvas.value.getContext('2d')
  if (!ctx) return
  const dims = evaluationResult.value.dimensions
  const labels = Object.keys(dims).map((k: string) => dimensionNames[k] || k)
  const scores = Object.values(dims).map((d: any) => d.score / 100)
  const W = 268, H = 210, cx = W / 2, cy = H / 2, r = 78, n = labels.length
  const angleStep = (Math.PI * 2) / n
  ctx.clearRect(0, 0, W, H)
  for (let level = 1; level <= 5; level++) {
    const lr = (r * level) / 5
    ctx.beginPath()
    for (let i = 0; i < n; i++) {
      const angle = i * angleStep - Math.PI / 2
      i === 0 ? ctx.moveTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle))
               : ctx.lineTo(cx + lr * Math.cos(angle), cy + lr * Math.sin(angle))
    }
    ctx.closePath(); ctx.strokeStyle = 'rgba(108,99,255,0.2)'; ctx.lineWidth = 1; ctx.stroke()
  }
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    ctx.beginPath(); ctx.moveTo(cx, cy)
    ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle))
    ctx.strokeStyle = 'rgba(108,99,255,0.25)'; ctx.stroke()
  }
  ctx.beginPath()
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    const val = scores[i] * r
    i === 0 ? ctx.moveTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle))
             : ctx.lineTo(cx + val * Math.cos(angle), cy + val * Math.sin(angle))
  }
  ctx.closePath(); ctx.fillStyle = 'rgba(108,99,255,0.3)'; ctx.fill()
  ctx.strokeStyle = '#6c63ff'; ctx.lineWidth = 2; ctx.stroke()
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    const val = scores[i] * r
    ctx.beginPath(); ctx.arc(cx + val * Math.cos(angle), cy + val * Math.sin(angle), 4, 0, Math.PI * 2)
    ctx.fillStyle = '#6c63ff'; ctx.fill()
  }
  ctx.fillStyle = 'rgba(255,255,255,0.75)'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2
    ctx.fillText(labels[i], cx + (r + 18) * Math.cos(angle), cy + (r + 18) * Math.sin(angle) + 4)
  }
}

function exportReport() {
  if (!evaluationResult.value) return
  const blob = new Blob([JSON.stringify(evaluationResult.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url
  a.download = '选址报告_' + (evaluationResult.value.address || '') + '_' + new Date().toLocaleDateString() + '.json'
  a.click(); URL.revokeObjectURL(url)
}

onMounted(async () => { await nextTick(); await initMap() })
onUnmounted(() => { mapInstance?.destroy() })
watch(evaluationResult, (val) => { if (val) nextTick(() => drawRadarChart()) })
</script>

<style scoped>
.map-page { position: relative; width: 100%; height: calc(100vh - 60px); display: flex; overflow: hidden; background: #0d0d1a; }
.control-panel { width: 260px; min-width: 260px; height: 100%; background: #13132a; border-right: 1px solid rgba(108,99,255,0.15); display: flex; flex-direction: column; overflow-y: auto; z-index: 10; }
.panel-header { display: flex; align-items: center; gap: 8px; padding: 16px; font-size: 15px; font-weight: 700; color: #e0e0ff; border-bottom: 1px solid rgba(108,99,255,0.15); background: linear-gradient(135deg,#1a1a35,#13132a); flex-shrink: 0; }
.header-icon { color: #6c63ff; font-size: 18px; }
.panel-section { padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.04); }
.section-title { font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.radius-row { display: flex; align-items: center; margin-top: 10px; gap: 4px; }
.radius-label { font-size: 12px; color: rgba(255,255,255,0.5); white-space: nowrap; }
.radius-val { font-size: 12px; color: #6c63ff; white-space: nowrap; min-width: 42px; text-align: right; }
.evaluate-btn { width: 100%; margin-top: 12px; background: linear-gradient(135deg,#6c63ff,#8b5cf6); border: none; font-weight: 600; }
.tool-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.layer-item { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.layer-label { font-size: 13px; color: rgba(255,255,255,0.65); }
.legend-item { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; font-size: 13px; color: rgba(255,255,255,0.6); }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.legend-dot.success { background: #67c23a; }
.legend-dot.failed { background: #f56c6c; }
.legend-dot.selected { background: #6c63ff; }
.store-stats { display: flex; justify-content: space-around; }
.stat-item { text-align: center; }
.stat-num { display: block; font-size: 22px; font-weight: 700; color: #e0e0ff; line-height: 1.2; }
.stat-label { font-size: 11px; color: rgba(255,255,255,0.4); }
.map-container { flex: 1; height: 100%; position: relative; }
#amap-container { width: 100%; height: 100%; }
.map-placeholder { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: #0d0d1a; }
.placeholder-inner { text-align: center; }
.result-panel { width: 300px; min-width: 300px; height: 100%; background: #13132a; border-left: 1px solid rgba(108,99,255,0.15); overflow-y: auto; z-index: 10; }
.result-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid rgba(108,99,255,0.15); background: linear-gradient(135deg,#1a1a35,#13132a); flex-shrink: 0; position: sticky; top: 0; z-index: 1; }
.result-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 700; color: #e0e0ff; }
.result-address { display: flex; align-items: flex-start; gap: 6px; padding: 12px 16px; font-size: 12px; color: rgba(255,255,255,0.55); border-bottom: 1px solid rgba(255,255,255,0.04); background: rgba(108,99,255,0.05); line-height: 1.5; }
.score-overview { display: flex; align-items: center; gap: 16px; padding: 20px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.score-circle { width: 76px; height: 76px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 3px solid; flex-shrink: 0; }
.score-circle.excellent { border-color: #67c23a; background: rgba(103,194,58,0.1); }
.score-circle.good { border-color: #409eff; background: rgba(64,158,255,0.1); }
.score-circle.medium { border-color: #e6a23c; background: rgba(230,162,60,0.1); }
.score-circle.poor { border-color: #f56c6c; background: rgba(245,108,108,0.1); }
.score-num { font-size: 26px; font-weight: 800; color: #fff; line-height: 1; }
.score-unit { font-size: 12px; color: rgba(255,255,255,0.45); }
.score-meta { flex: 1; }
.grade-text { font-size: 17px; font-weight: 700; margin-bottom: 4px; }
.grade-text.excellent { color: #67c23a; }
.grade-text.good { color: #409eff; }
.grade-text.medium { color: #e6a23c; }
.grade-text.poor { color: #f56c6c; }
.grade-sub { font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 6px; }
.grade-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
.grade-badge.excellent { background: rgba(103,194,58,0.15); color: #67c23a; }
.grade-badge.good { background: rgba(64,158,255,0.15); color: #409eff; }
.grade-badge.medium { background: rgba(230,162,60,0.15); color: #e6a23c; }
.grade-badge.poor { background: rgba(245,108,108,0.15); color: #f56c6c; }
.radar-section { padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; align-items: center; }
.section-label { font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; align-self: flex-start; }
.dimension-scores { padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.dim-item { margin-bottom: 14px; }
.dim-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.dim-name { font-size: 13px; color: rgba(255,255,255,0.75); }
.dim-score { font-size: 13px; font-weight: 700; }
.dim-detail { font-size: 11px; color: rgba(255,255,255,0.3); margin-top: 4px; line-height: 1.4; }
.ai-section { padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.ai-text { font-size: 13px; color: rgba(255,255,255,0.7); line-height: 1.7; background: rgba(108,99,255,0.07); border-left: 3px solid #6c63ff; padding: 12px; border-radius: 0 8px 8px 0; }
.result-actions { padding: 14px 16px; display: flex; gap: 8px; }
.workflow-panel { position: absolute; bottom: 16px; left: 276px; right: 316px; background: rgba(13,13,26,0.96); border: 1px solid rgba(108,99,255,0.3); border-radius: 10px; backdrop-filter: blur(10px); z-index: 100; max-height: 260px; overflow: hidden; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }
.workflow-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(108,99,255,0.15); user-select: none; }
.wf-title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #e0e0ff; }
.wf-dot { width: 8px; height: 8px; border-radius: 50%; background: #4b5563; flex-shrink: 0; }
.wf-dot.active { background: #6c63ff; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity:1;transform:scale(1); } 50% { opacity:0.5;transform:scale(0.8); } }
.workflow-body { max-height: 180px; overflow-y: auto; padding: 6px 0; }
.wf-step { display: flex; align-items: flex-start; gap: 8px; padding: 5px 14px; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.03); }
.wf-step:hover { background: rgba(108,99,255,0.06); }
.wf-icon { font-size: 13px; flex-shrink: 0; margin-top: 1px; }
.wf-content { display: flex; gap: 6px; flex-wrap: wrap; align-items: baseline; }
.wf-name { color: rgba(255,255,255,0.45); flex-shrink: 0; }
.wf-msg { color: rgba(255,255,255,0.75); line-height: 1.4; }
.wf-result .wf-msg { color: #67c23a; }
.wf-error .wf-msg { color: #f56c6c; }
.wf-warning .wf-msg { color: #e6a23c; }
.wf-thinking .wf-msg { color: #6c63ff; }
.wf-final .wf-msg { color: #67c23a; font-weight: 600; }
.slide-right-enter-active,.slide-right-leave-active { transition: all 0.3s cubic-bezier(0.4,0,0.2,1); }
.slide-right-enter-from,.slide-right-leave-to { transform: translateX(100%); opacity: 0; }
.slide-up-enter-active,.slide-up-leave-active { transition: all 0.3s cubic-bezier(0.4,0,0.2,1); }
.slide-up-enter-from,.slide-up-leave-to { transform: translateY(20px); opacity: 0; }
</style>
