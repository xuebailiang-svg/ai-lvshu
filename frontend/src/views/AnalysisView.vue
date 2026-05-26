<template>
  <div class="analysis-view">
    <div class="page-header">
      <h2>历史数据分析</h2>
      <p>从已上传的门店、营收、会员和硬件数据中提炼营收因素、成功规律和待确认权重建议。</p>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span class="num">{{ overview.samples?.stores || 0 }}</span>
        <span>历史门店</span>
      </div>
      <div class="summary-card">
        <span class="num">{{ overview.samples?.revenue_records || 0 }}</span>
        <span>营收样本</span>
      </div>
      <div class="summary-card">
        <span class="num">{{ money(overview.summary?.avg_revenue) }}</span>
        <span>平均营收</span>
      </div>
      <div class="summary-card">
        <span class="num">{{ overview.summary?.pending_insights || 0 }}</span>
        <span>待确认建议</span>
      </div>
    </div>

    <section class="section">
      <div class="section-head">
        <h3>营收影响因素排行</h3>
        <el-button :loading="loadingFactors" @click="loadFactors">重新分析</el-button>
      </div>
      <el-table :data="factors" v-loading="loadingFactors" border stripe>
        <el-table-column prop="name" label="因素" width="160" />
        <el-table-column label="影响方向" width="100">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'positive' ? 'success' : 'warning'">
              {{ row.direction === 'positive' ? '正相关' : '负相关' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="影响强度" width="120">
          <template #default="{ row }">{{ row.impact_score }}%</template>
        </el-table-column>
        <el-table-column prop="sample_count" label="样本数" width="90" />
        <el-table-column prop="evidence" label="依据" min-width="300" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="section">
      <div class="section-head">
        <h3>待确认权重建议</h3>
        <el-button @click="loadInsights">刷新</el-button>
      </div>
      <el-table :data="insights" v-loading="loadingInsights" border stripe>
        <el-table-column prop="title" label="规律/因素" min-width="150" />
        <el-table-column prop="dimension_name" label="影响维度" width="120" />
        <el-table-column label="当前权重" width="100">
          <template #default="{ row }">{{ percent(row.current_weight) }}</template>
        </el-table-column>
        <el-table-column label="建议权重" width="100">
          <template #default="{ row }">{{ percent(row.suggested_weight) }}</template>
        </el-table-column>
        <el-table-column label="置信度" width="100">
          <template #default="{ row }">{{ percent(row.confidence) }}</template>
        </el-table-column>
        <el-table-column prop="summary" label="调整依据" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" type="primary" link @click="approve(row)">确认</el-button>
            <el-button v-if="row.status === 'pending'" type="danger" link @click="reject(row)">忽略</el-button>
            <el-tag v-else size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'AnalysisView' })
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const overview = ref<any>({})
const factors = ref<any[]>([])
const insights = ref<any[]>([])
const loadingFactors = ref(false)
const loadingInsights = ref(false)

function percent(v: any) {
  if (v === null || v === undefined) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function money(v: any) {
  const n = Number(v || 0)
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return n.toFixed(0)
}

async function loadOverview() {
  overview.value = await api.get('/analysis/overview')
}

async function loadFactors() {
  loadingFactors.value = true
  try {
    const res: any = await api.get('/analysis/factors')
    factors.value = res.items || []
    await loadInsights()
  } finally {
    loadingFactors.value = false
  }
}

async function loadInsights() {
  loadingInsights.value = true
  try {
    const res: any = await api.get('/analysis/insights')
    insights.value = res.items || []
  } finally {
    loadingInsights.value = false
  }
}

async function approve(row: any) {
  await api.post(`/analysis/insights/${row.id}/approve`, { note: '用户在历史数据分析中心确认' })
  ElMessage.success('权重建议已确认')
  await Promise.all([loadInsights(), loadOverview()])
}

async function reject(row: any) {
  await api.post(`/analysis/insights/${row.id}/reject`, { note: '用户忽略该建议' })
  ElMessage.success('已忽略该建议')
  await loadInsights()
}

onMounted(async () => {
  await loadOverview()
  await loadFactors()
})
</script>

<style scoped>
.analysis-view { display: flex; flex-direction: column; gap: 18px; }
.page-header h2 { margin: 0 0 6px; color: #1a1a2e; }
.page-header p { margin: 0; color: #666; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.summary-card { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; display: flex; flex-direction: column; gap: 6px; color: #666; }
.summary-card .num { font-size: 24px; font-weight: 700; color: #1a1a2e; }
.section { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-head h3 { margin: 0; color: #1a1a2e; }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
