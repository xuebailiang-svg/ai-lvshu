<template>
  <div class="model-view">
    <div class="page-header">
      <h2>评分模型 / 权重确认</h2>
      <p>把已经确认的历史规律保存为模型版本，新地址评估会使用当前生效版本。</p>
    </div>

    <section class="section">
      <div class="section-head">
        <h3>当前权重快照</h3>
        <div>
          <el-button @click="loadRules">刷新权重</el-button>
          <el-button type="primary" @click="createVersion">保存为新模型版本</el-button>
        </div>
      </div>
      <el-table :data="rules" v-loading="loadingRules" border stripe>
        <el-table-column prop="dimension_name" label="维度" width="120" />
        <el-table-column prop="sub_factor" label="因子" min-width="170" />
        <el-table-column label="基础权重" width="110">
          <template #default="{ row }">{{ percent(row.base_weight) }}</template>
        </el-table-column>
        <el-table-column label="当前生效权重" width="130">
          <template #default="{ row }">
            <el-tag :type="row.effective_weight !== row.base_weight ? 'warning' : 'info'">{{ percent(row.effective_weight) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_updated_by" label="来源" width="120" />
        <el-table-column prop="update_reason" label="原因" min-width="240" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="section">
      <div class="section-head">
        <h3>模型版本</h3>
        <el-button @click="loadVersions">刷新</el-button>
      </div>
      <el-table :data="versions" v-loading="loadingVersions" border stripe>
        <el-table-column prop="name" label="模型名称" min-width="180" />
        <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="来源快照" min-width="220">
          <template #default="{ row }">
            <div class="source-snapshot">
              <span>规则 {{ row.source_snapshot?.rule_count || 0 }}</span>
              <span>已确认建议 {{ row.source_snapshot?.approved_analysis_insights || 0 }}</span>
              <span>反馈 {{ row.source_snapshot?.feedback_count || 0 }}</span>
              <span>待处理质量 {{ row.source_snapshot?.open_data_quality_issues || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '生效中' : '未生效' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="!row.is_active" type="primary" link @click="activate(row)">设为生效</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'ModelView' })
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const rules = ref<any[]>([])
const versions = ref<any[]>([])
const loadingRules = ref(false)
const loadingVersions = ref(false)

function percent(v: any) {
  if (v === null || v === undefined) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

async function loadRules() {
  loadingRules.value = true
  try {
    rules.value = await api.get('/data/scoring-rules')
  } finally {
    loadingRules.value = false
  }
}

async function loadVersions() {
  loadingVersions.value = true
  try {
    const res: any = await api.get('/model-versions')
    versions.value = res.items || []
  } finally {
    loadingVersions.value = false
  }
}

async function createVersion() {
  const name = `历史分析模型 ${new Date().toLocaleString()}`
  await api.post('/model-versions', {
    name,
    description: '由当前已确认权重保存的模型版本',
    activate: true,
  })
  ElMessage.success('模型版本已保存并生效')
  await Promise.all([loadRules(), loadVersions()])
}

async function activate(row: any) {
  await ElMessageBox.confirm(`确认启用模型「${row.name}」？`, '启用模型', { type: 'warning' })
  await api.post(`/model-versions/${row.id}/activate`)
  ElMessage.success('模型版本已生效')
  await Promise.all([loadRules(), loadVersions()])
}

onMounted(async () => {
  await Promise.all([loadRules(), loadVersions()])
})
</script>

<style scoped>
.model-view { display: flex; flex-direction: column; gap: 18px; }
.page-header h2 { margin: 0 0 6px; color: #1a1a2e; }
.page-header p { margin: 0; color: #666; }
.section { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-head h3 { margin: 0; color: #1a1a2e; }
.source-snapshot { display: flex; flex-wrap: wrap; gap: 6px; color: #666; font-size: 12px; }
.source-snapshot span { padding: 2px 6px; border-radius: 4px; background: #f5f7fa; }
</style>
