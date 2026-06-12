<template>
  <div class="feedback-view">
    <div class="page-header">
      <h2>评估反馈 / 数据质量</h2>
      <p>集中处理评估结果反馈、异常数据标记和历史案例排除，避免不合理数据继续进入报告和知识库。</p>
    </div>

    <section class="section">
      <div class="section-head">
        <h3>数据质量问题</h3>
        <el-button @click="loadIssues">刷新</el-button>
      </div>
      <el-table :data="issues" v-loading="loadingIssues" border stripe>
        <el-table-column prop="title" label="问题" min-width="160" />
        <el-table-column prop="issue_type" label="类型" width="170" />
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag :type="row.severity === 'error' ? 'danger' : 'warning'">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="280" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'open' ? 'danger' : 'success'">{{ row.status === 'open' ? '待处理' : '已处理' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'open'" type="primary" link @click="resolveIssue(row)">标记已处理</el-button>
            <el-button v-if="row.source_id" type="danger" link @click="exclude(row)">排除来源</el-button>
            <el-button type="danger" link @click="deleteIssue(row)">删除问题</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="section">
      <div class="section-head">
        <h3>评估历史</h3>
        <el-button @click="loadHistory">刷新</el-button>
      </div>
      <el-table :data="history" v-loading="loadingHistory" border stripe>
        <el-table-column prop="address" label="地址" min-width="240" show-overflow-tooltip />
        <el-table-column prop="total_score" label="得分" width="80" />
        <el-table-column prop="grade_label" label="结论" width="120" />
        <el-table-column label="数据质量" width="120">
          <template #default="{ row }">
            <el-tag :type="row.data_quality?.has_issues ? 'warning' : 'success'">
              {{ row.data_quality?.has_issues ? '需核验' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="评估时间" width="180" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openFeedback(row)">提交反馈</el-button>
            <el-button type="warning" link @click="markAbnormal(row)">标记不合理</el-button>
            <el-button type="danger" link @click="excludeEvaluation(row)">删除案例</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="feedbackVisible" title="提交评估反馈" width="560px">
      <el-form label-width="130px">
        <el-form-item label="准确的方面">
          <el-select v-model="feedbackForm.accurate_aspects" multiple style="width:100%">
            <el-option v-for="item in aspectOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="不准确的方面">
          <el-select v-model="feedbackForm.inaccurate_aspects" multiple style="width:100%">
            <el-option v-for="item in aspectOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="实际日均客流">
          <el-input-number v-model="feedbackForm.actual_daily_customers" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="实际月营收">
          <el-input-number v-model="feedbackForm.actual_monthly_revenue" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="实际月利润">
          <el-input-number v-model="feedbackForm.actual_monthly_profit" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="feedbackForm.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feedbackVisible = false">取消</el-button>
        <el-button type="primary" @click="submitFeedback">保存反馈</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'FeedbackQualityView' })
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const issues = ref<any[]>([])
const history = ref<any[]>([])
const loadingIssues = ref(false)
const loadingHistory = ref(false)
const feedbackVisible = ref(false)
const currentEvaluation = ref<any>(null)
const aspectOptions = ['交通人流', '竞品判断', '目标客群', '租金成本', '配套设施', '政策风险', '高校数量', '报告结论']
const feedbackForm = reactive<any>({
  accurate_aspects: [],
  inaccurate_aspects: [],
  actual_daily_customers: undefined,
  actual_monthly_revenue: undefined,
  actual_monthly_profit: undefined,
  notes: '',
})

async function loadIssues() {
  loadingIssues.value = true
  try {
    const res: any = await api.get('/data-quality/issues')
    issues.value = res.items || []
  } finally {
    loadingIssues.value = false
  }
}

async function loadHistory() {
  loadingHistory.value = true
  try {
    const res: any = await api.get('/evaluate/history', { params: { include_excluded: true } })
    history.value = res.items || []
  } finally {
    loadingHistory.value = false
  }
}

async function resolveIssue(row: any) {
  await api.post(`/data-quality/issues/${row.id}/resolve`, { note: '用户确认已处理' })
  ElMessage.success('已标记处理')
  await loadIssues()
}

async function deleteIssue(row: any) {
  await ElMessageBox.confirm(
    '删除后只移除这条数据质量问题记录，不会删除对应评估案例。如需删除案例，请使用下方“删除案例”。',
    '删除数据质量问题',
    { type: 'warning' }
  )
  await api.delete(`/data-quality/issues/${row.id}`)
  ElMessage.success('数据质量问题已删除')
  await loadIssues()
}

async function exclude(row: any) {
  await api.post(`/data-quality/sources/${row.source_id}/exclude`, {
    source_type: row.source_type === 'external_api' ? 'evaluation_result' : row.source_type,
    source_id: row.source_id,
    reason: row.description || row.title,
  })
  ElMessage.success('来源已排除')
  await Promise.all([loadIssues(), loadHistory()])
}

async function excludeEvaluation(row: any) {
  await ElMessageBox.confirm(
    '删除后会移除该评估案例、反馈、数据质量问题和知识库引用，后续不会再进入相似案例、RAG 和报告引用。',
    '删除历史案例',
    { type: 'warning' }
  )
  await api.delete(`/data-quality/sources/${row.id}`, { params: { source_type: 'evaluation_result' } })
  ElMessage.success('历史案例已删除')
  await Promise.all([loadIssues(), loadHistory()])
}

async function markAbnormal(row: any) {
  await api.post('/data-quality/issues', {
    evaluation_id: row.id,
    source_type: 'evaluation_result',
    source_id: row.id,
    issue_type: 'user_marked_abnormal',
    severity: 'warning',
    title: '用户标记评估数据不合理',
    description: `${row.address} 的评估结果被用户标记为需要人工核验。`,
    payload: row.data_quality || {},
  })
  ElMessage.success('已记录数据质量问题')
  await loadIssues()
}

function openFeedback(row: any) {
  currentEvaluation.value = row
  feedbackForm.accurate_aspects = []
  feedbackForm.inaccurate_aspects = []
  feedbackForm.actual_daily_customers = undefined
  feedbackForm.actual_monthly_revenue = undefined
  feedbackForm.actual_monthly_profit = undefined
  feedbackForm.notes = ''
  feedbackVisible.value = true
}

async function submitFeedback() {
  if (!currentEvaluation.value) return
  await api.post(`/evaluate/${currentEvaluation.value.id}/feedback`, feedbackForm)
  ElMessage.success('反馈已保存')
  feedbackVisible.value = false
}

onMounted(async () => {
  await Promise.all([loadIssues(), loadHistory()])
})
</script>

<style scoped>
.feedback-view { display: flex; flex-direction: column; gap: 18px; }
.page-header h2 { margin: 0 0 6px; color: #1a1a2e; }
.page-header p { margin: 0; color: #666; }
.section { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-head h3 { margin: 0; color: #1a1a2e; }
</style>
