<template>
  <div class="model-view">
    <div class="page-header">
      <div>
        <h2>评分模型 / 权重确认</h2>
        <p>按“大类 - 小类”维护评分权重。新增或修改后会立即参与新地址评估，保存为模型版本用于留痕。</p>
      </div>
      <div class="header-actions">
        <el-button @click="loadRules">刷新权重</el-button>
        <el-button type="primary" @click="openRuleDialog()">新增小类</el-button>
        <el-button type="success" @click="createVersion">保存为新模型版本</el-button>
      </div>
    </div>

    <section class="section">
      <div class="section-head">
        <h3>细分权重配置</h3>
        <span class="hint">权重填写 0-100%，系统会按大类合计后自动归一化。</span>
      </div>
      <div class="dimension-list">
        <div v-for="group in groupedRules" :key="group.dimension" class="dimension-card">
          <div class="dimension-head">
            <div>
              <div class="dimension-name">{{ group.dimension_name }}</div>
              <div class="dimension-key">{{ group.dimension }}</div>
            </div>
            <el-tag type="info">大类合计 {{ percent(group.total_weight) }}</el-tag>
          </div>
          <el-table :data="group.rules" border size="small">
            <el-table-column label="小类" min-width="180">
              <template #default="{ row }">
                <div class="factor-name">{{ factorLabel(row.sub_factor) }}</div>
                <div class="factor-key">{{ row.sub_factor }}</div>
              </template>
            </el-table-column>
            <el-table-column label="基础权重" width="110">
              <template #default="{ row }">{{ percent(row.base_weight) }}</template>
            </el-table-column>
            <el-table-column label="当前权重" width="120">
              <template #default="{ row }">
                <el-tag :type="row.effective_weight !== row.base_weight ? 'warning' : 'info'">
                  {{ percent(row.effective_weight) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="update_reason" label="说明" min-width="220" show-overflow-tooltip />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRuleDialog(row)">编辑</el-button>
                <el-button link type="danger" @click="removeRule(row)">停用</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
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

    <el-dialog v-model="ruleDialogVisible" :title="editingRule?.id ? '编辑评分小类' : '新增评分小类'" width="560px">
      <el-form label-width="120px">
        <el-form-item label="评分大类">
          <el-select v-model="ruleForm.dimension" style="width:100%" @change="syncDimensionName">
            <el-option v-for="item in dimensionOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="大类名称">
          <el-input v-model="ruleForm.dimension_name" />
        </el-form-item>
        <el-form-item label="小类标识">
          <el-input v-model="ruleForm.sub_factor" placeholder="例如 metro_distance，不要和同大类已有小类重复" />
        </el-form-item>
        <el-form-item label="小类名称">
          <el-input v-model="ruleForm.update_reason" placeholder="例如 地铁距离 / 常住人口 / 夜市摊" />
        </el-form-item>
        <el-form-item label="基础权重">
          <el-input-number v-model="ruleForm.base_weight_pct" :min="0" :max="100" :step="0.5" style="width:180px" />
          <span class="unit">%</span>
        </el-form-item>
        <el-form-item label="当前权重">
          <el-input-number v-model="ruleForm.effective_weight_pct" :min="0" :max="100" :step="0.5" style="width:180px" />
          <span class="unit">%</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'ModelView' })
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const rules = ref<any[]>([])
const versions = ref<any[]>([])
const loadingRules = ref(false)
const loadingVersions = ref(false)
const ruleDialogVisible = ref(false)
const editingRule = ref<any>(null)
const ruleForm = ref<any>({
  dimension: 'traffic',
  dimension_name: '交通与人流',
  sub_factor: '',
  update_reason: '',
  base_weight_pct: 0,
  effective_weight_pct: 0,
})

const dimensionOptions = [
  { value: 'traffic', label: '交通与人流' },
  { value: 'population', label: '目标客群' },
  { value: 'competition', label: '竞品分析' },
  { value: 'rent', label: '租金成本' },
  { value: 'facility', label: '配套设施' },
  { value: 'policy', label: '政策环境' },
]

const factorLabels: Record<string, string> = {
  foot_traffic: '人流基础',
  transit_accessibility: '公共交通可达性',
  metro_distance: '地铁距离',
  bus_distance: '公交距离',
  negative_overpass: '负相关：高架桥',
  negative_interchange: '负相关：立交',
  negative_underpass: '负相关：地下隧道',
  negative_railway: '负相关：火车道',
  negative_greenbelt: '负相关：大型绿化带',
  young_density: '年轻客群密度',
  university_nearby: '大学/高校',
  resident_population: '常住人口',
  floating_population: '流动人口',
  age_18_24: '年龄段：18-24',
  age_25_34: '年龄段：25-34',
  secondary_vocational_nearby: '中职/技校',
  competitor_count: '竞品数量',
  competitor_distance: '竞品距离',
  competitor_configuration: '竞品配置',
  competitor_price: '竞品价位',
  competitor_occupancy: '竞品上座率',
  competitor_open_years: '竞品开业年限',
  competitor_area: '竞品面积',
  competitor_monthly_sales: '竞品月售',
  competitor_annual_sales: '竞品年售',
  competitor_recharge: '竞品充值信息',
  same_category_capacity: '可容纳同品类数量',
  rent_ratio: '租金成本占比',
  area_sqm: '面积',
  floor: '楼层',
  frontage_visibility: '门头可见性',
  parking_convenience: '停车便利性',
  fire_safety: '消防条件',
  property_restriction: '物业限制',
  power_capacity: '电力容量',
  hvac_exhaust: '空调/排烟',
  commercial_density: '商业配套密度',
  night_market: '夜市摊',
  food_business_hours: '餐饮营业时间',
  food_category: '餐饮品类',
  food_open_years: '餐饮开业年限',
  ktv: 'KTV',
  bar: '酒吧',
  billiards: '台球',
  escape_room: '密室',
  cinema: '电影院',
  convenience_24h: '24小时便利店',
  relocation_housing: '住宅区：回迁房',
  apartment: '住宅区：公寓',
  policy_risk: '政策风险',
  policy_redline_200m: '政策红线：200m',
}

const groupedRules = computed(() => {
  const map = new Map<string, any>()
  for (const option of dimensionOptions) {
    map.set(option.value, { dimension: option.value, dimension_name: option.label, total_weight: 0, rules: [] })
  }
  for (const rule of rules.value) {
    if (!map.has(rule.dimension)) {
      map.set(rule.dimension, { dimension: rule.dimension, dimension_name: rule.dimension_name, total_weight: 0, rules: [] })
    }
    const group = map.get(rule.dimension)
    group.dimension_name = rule.dimension_name || group.dimension_name
    group.total_weight += Number(rule.effective_weight || 0)
    group.rules.push(rule)
  }
  return Array.from(map.values()).filter(group => group.rules.length > 0)
})

function percent(v: any) {
  if (v === null || v === undefined) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function factorLabel(key: string) {
  return factorLabels[key] || key || '未命名小类'
}

function syncDimensionName() {
  const item = dimensionOptions.find(option => option.value === ruleForm.value.dimension)
  if (item) ruleForm.value.dimension_name = item.label
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

function openRuleDialog(row?: any) {
  editingRule.value = row || null
  if (row) {
    ruleForm.value = {
      dimension: row.dimension,
      dimension_name: row.dimension_name,
      sub_factor: row.sub_factor,
      update_reason: row.update_reason || factorLabel(row.sub_factor),
      base_weight_pct: Number(row.base_weight || 0) * 100,
      effective_weight_pct: Number(row.effective_weight || 0) * 100,
    }
  } else {
    ruleForm.value = {
      dimension: 'traffic',
      dimension_name: '交通与人流',
      sub_factor: '',
      update_reason: '',
      base_weight_pct: 0,
      effective_weight_pct: 0,
    }
  }
  ruleDialogVisible.value = true
}

async function saveRule() {
  const payload = {
    dimension: ruleForm.value.dimension,
    dimension_name: ruleForm.value.dimension_name,
    sub_factor: ruleForm.value.sub_factor,
    base_weight: Number(ruleForm.value.base_weight_pct || 0) / 100,
    effective_weight: Number(ruleForm.value.effective_weight_pct || 0) / 100,
    update_reason: ruleForm.value.update_reason || '用户手动调整评分权重',
  }
  if (editingRule.value?.id) {
    await api.put(`/data/scoring-rules/${editingRule.value.id}`, payload)
    ElMessage.success('评分权重已更新')
  } else {
    await api.post('/data/scoring-rules', payload)
    ElMessage.success('评分小类已新增')
  }
  ruleDialogVisible.value = false
  await Promise.all([loadRules(), loadVersions()])
}

async function removeRule(row: any) {
  await ElMessageBox.confirm(`确认停用「${factorLabel(row.sub_factor)}」？停用后不会参与后续评分。`, '停用评分小类', { type: 'warning' })
  await api.delete(`/data/scoring-rules/${row.id}`)
  ElMessage.success('评分小类已停用')
  await Promise.all([loadRules(), loadVersions()])
}

async function createVersion() {
  const name = `手动权重模型 ${new Date().toLocaleString()}`
  await api.post('/model-versions', {
    name,
    description: '由当前手动细分权重保存的模型版本',
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
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-header h2 { margin: 0 0 6px; color: #1a1a2e; }
.page-header p { margin: 0; color: #666; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.section { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.section-head h3 { margin: 0; color: #1a1a2e; }
.hint { color: #909399; font-size: 12px; }
.dimension-list { display: grid; grid-template-columns: 1fr; gap: 14px; }
.dimension-card { border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden; }
.dimension-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; background: #f7f9fc; border-bottom: 1px solid #ebeef5; }
.dimension-name { font-weight: 700; color: #1f2d3d; }
.dimension-key, .factor-key { margin-top: 3px; color: #909399; font-size: 12px; font-family: Consolas, monospace; }
.factor-name { font-weight: 600; color: #303133; }
.source-snapshot { display: flex; flex-wrap: wrap; gap: 6px; color: #666; font-size: 12px; }
.source-snapshot span { padding: 2px 6px; border-radius: 4px; background: #f5f7fa; }
.unit { margin-left: 8px; color: #606266; }
</style>
