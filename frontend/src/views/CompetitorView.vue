<template>
  <div class="competitor-view">
    <div class="page-header">
      <div>
        <h2>竞品档案</h2>
        <p>沉淀地图 API 获取不到的竞品配置、价位、上座率、充值活动和调研记录，用于新地址评估和商圈容量判断。</p>
      </div>
      <div class="header-actions">
        <el-input v-model="keyword" clearable placeholder="搜索竞品名称" style="width:220px" @keyup.enter="loadCompetitors" />
        <el-button @click="loadCompetitors">刷新</el-button>
        <el-button type="primary" @click="openDialog()">新增竞品</el-button>
      </div>
    </div>

    <section class="section">
      <el-table :data="competitors" v-loading="loading" border stripe>
        <el-table-column prop="name" label="竞品名称" min-width="160" fixed="left" />
        <el-table-column prop="address" label="地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="配置/规模" min-width="180">
          <template #default="{ row }">
            <div>{{ row.configuration || '待调研' }}</div>
            <div class="muted">
              <span v-if="row.machine_count">机器 {{ row.machine_count }} 台</span>
              <span v-if="row.area_sqm"> 面积 {{ row.area_sqm }} ㎡</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="价格" width="150">
          <template #default="{ row }">
            <div v-if="row.hourly_price">小时 {{ row.hourly_price }} 元</div>
            <div v-if="row.package_price">套餐 {{ row.package_price }} 元</div>
            <span v-if="!row.hourly_price && !row.package_price" class="muted">待调研</span>
          </template>
        </el-table-column>
        <el-table-column label="上座率" width="110">
          <template #default="{ row }">{{ row.occupancy_rate != null ? `${row.occupancy_rate}%` : '待采样' }}</template>
        </el-table-column>
        <el-table-column label="销售/充值" min-width="180">
          <template #default="{ row }">
            <div v-if="row.monthly_sales">月售 {{ row.monthly_sales }} 元</div>
            <div v-if="row.annual_sales">年售 {{ row.annual_sales }} 元</div>
            <div class="muted">{{ row.recharge_info || '暂无充值活动' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ sourceLabel(row.data_source) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canEditCompetitor(row)" link type="primary" @click="openDialog(row)">编辑</el-button>
            <el-button link type="success" @click="openObservation(row)">观察</el-button>
            <el-button v-if="canEditCompetitor(row)" link type="danger" @click="removeCompetitor(row)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editing?.id ? '编辑竞品档案' : '新增竞品档案'" width="760px">
      <el-form label-width="120px">
        <div class="form-grid">
          <el-form-item label="竞品名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="城市"><el-input v-model="form.city" /></el-form-item>
          <el-form-item label="地址" class="wide"><el-input v-model="form.address" /></el-form-item>
          <el-form-item label="经度"><el-input-number v-model="form.longitude" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item label="纬度"><el-input-number v-model="form.latitude" :controls="false" style="width:100%" /></el-form-item>
          <el-form-item label="机器数量（台）"><el-input-number v-model="form.machine_count" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="面积（㎡）"><el-input-number v-model="form.area_sqm" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="小时价（元）"><el-input-number v-model="form.hourly_price" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="套餐价（元）"><el-input-number v-model="form.package_price" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="上座率（%）"><el-input-number v-model="form.occupancy_rate" :min="0" :max="100" style="width:100%" /></el-form-item>
          <el-form-item label="开业年限（年）"><el-input-number v-model="form.open_years" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="月售（元）"><el-input-number v-model="form.monthly_sales" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="年售（元）"><el-input-number v-model="form.annual_sales" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="数据来源">
            <el-select v-model="form.data_source" style="width:100%">
              <el-option label="人工调研" value="manual" />
              <el-option label="地图 API" value="api" />
              <el-option label="公开合规来源" value="public" />
              <el-option label="估算" value="estimated" />
            </el-select>
          </el-form-item>
          <el-form-item label="置信度"><el-input-number v-model="form.confidence" :min="0" :max="1" :step="0.1" style="width:100%" /></el-form-item>
          <el-form-item label="硬件配置" class="wide"><el-input v-model="form.configuration" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="充值活动" class="wide"><el-input v-model="form.recharge_info" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="备注" class="wide"><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCompetitor">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="observationVisible" title="新增竞品观察记录" width="520px">
      <el-form label-width="130px">
        <el-form-item label="观察人"><el-input v-model="observationForm.observer" /></el-form-item>
        <el-form-item label="上座率（%）"><el-input-number v-model="observationForm.occupancy_rate" :min="0" :max="100" style="width:100%" /></el-form-item>
        <el-form-item label="小时价（元）"><el-input-number v-model="observationForm.hourly_price" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="套餐价（元）"><el-input-number v-model="observationForm.package_price" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="充值活动"><el-input v-model="observationForm.recharge_info" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="观察说明"><el-input v-model="observationForm.activity_note" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="observationVisible = false">取消</el-button>
        <el-button type="primary" @click="saveObservation">保存观察</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'CompetitorView' })
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const keyword = ref('')
const loading = ref(false)
const competitors = ref<any[]>([])
const dialogVisible = ref(false)
const observationVisible = ref(false)
const editing = ref<any>(null)
const observationTarget = ref<any>(null)

const emptyForm = () => ({
  name: '',
  address: '',
  city: '',
  district: '',
  longitude: undefined,
  latitude: undefined,
  machine_count: undefined,
  area_sqm: undefined,
  hourly_price: undefined,
  package_price: undefined,
  occupancy_rate: undefined,
  open_years: undefined,
  monthly_sales: undefined,
  annual_sales: undefined,
  recharge_info: '',
  configuration: '',
  notes: '',
  data_source: 'manual',
  confidence: 0.7,
})
const form = ref<any>(emptyForm())
const observationForm = ref<any>({})

function sourceLabel(value: string) {
  return ({ manual: '人工调研', api: '地图 API', public: '公开来源', estimated: '估算' } as any)[value] || value || '未知'
}

function canEditCompetitor(row: any) {
  return authStore.isSuperuser || (row?.created_by && row.created_by === authStore.user?.id)
}

async function loadCompetitors() {
  loading.value = true
  try {
    const res: any = await api.get('/data/competitors', { params: { keyword: keyword.value || undefined } })
    competitors.value = res.items || []
  } finally {
    loading.value = false
  }
}

function openDialog(row?: any) {
  editing.value = row || null
  form.value = row ? { ...row } : emptyForm()
  dialogVisible.value = true
}

async function saveCompetitor() {
  if (!form.value.name?.trim()) {
    ElMessage.warning('请填写竞品名称')
    return
  }
  if (editing.value?.id) {
    await api.put(`/data/competitors/${editing.value.id}`, form.value)
    ElMessage.success('竞品档案已更新')
  } else {
    await api.post('/data/competitors', form.value)
    ElMessage.success('竞品档案已新增')
  }
  dialogVisible.value = false
  await loadCompetitors()
}

async function removeCompetitor(row: any) {
  await ElMessageBox.confirm(`确认停用竞品“${row.name}”？`, '提示', { type: 'warning' })
  await api.delete(`/data/competitors/${row.id}`)
  ElMessage.success('已停用')
  await loadCompetitors()
}

function openObservation(row: any) {
  observationTarget.value = row
  observationForm.value = { observer: '', occupancy_rate: row.occupancy_rate, hourly_price: row.hourly_price, package_price: row.package_price, recharge_info: row.recharge_info || '', activity_note: '' }
  observationVisible.value = true
}

async function saveObservation() {
  if (!observationTarget.value?.id) return
  await api.post(`/data/competitors/${observationTarget.value.id}/observations`, observationForm.value)
  ElMessage.success('观察记录已保存')
  observationVisible.value = false
  await loadCompetitors()
}

onMounted(loadCompetitors)
</script>

<style scoped>
.competitor-view { padding: 24px; }
.page-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 20px; }
.page-header h2 { margin: 0 0 8px; font-size: 22px; color: #1f2d3d; }
.page-header p { margin: 0; color: #667085; line-height: 1.6; }
.header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.section { background: #fff; border: 1px solid #e6eaf2; border-radius: 8px; padding: 16px; }
.muted { color: #8a94a6; font-size: 12px; line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
.form-grid :deep(.wide) { grid-column: 1 / -1; }
@media (max-width: 900px) {
  .page-header { flex-direction: column; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
