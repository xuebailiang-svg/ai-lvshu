<template>
  <div class="data-view">
    <div class="page-header">
      <h2>历史数据管理</h2>
      <p class="subtitle">上传历史运营数据，系统将自动分析并优化选址评分模型</p>
    </div>

    <el-tabs v-model="activeTab" class="data-tabs">
      <!-- 数据上传 Tab -->
      <el-tab-pane label="上传数据" name="upload">
        <div class="upload-section">
          <div class="template-cards">
            <h3>第一步：下载标准模板</h3>
            <p class="tip">请先下载对应的模板文件，按规范填写后再上传。地址字段由系统自动转换经纬度，无需手动填写。</p>
            <div class="card-grid">
              <div v-for="tpl in templates" :key="tpl.type" class="template-card">
                <div class="template-card__info">
                  <div class="template-card__name">{{ tpl.name }}</div>
                  <div class="template-card__desc">{{ tpl.description }}</div>
                </div>
                <el-button
                  type="primary"
                  size="small"
                  :loading="downloading === tpl.type"
                  @click="downloadTemplate(tpl.type)"
                >
                  下载模板
                </el-button>
              </div>
            </div>
          </div>

          <div class="upload-area-section">
            <h3>第二步：上传填写好的文件</h3>
            <div class="upload-type-selector">
              <span>数据类型：</span>
              <el-radio-group v-model="uploadType">
                <el-radio-button value="basic">基础信息</el-radio-button>
                <el-radio-button value="revenue">营收数据</el-radio-button>
                <el-radio-button value="member">会员画像</el-radio-button>
                <el-radio-button value="hardware">硬件配置</el-radio-button>
              </el-radio-group>
            </div>

            <el-upload
              class="upload-dragger"
              drag
              :auto-upload="false"
              :on-change="handleFileChange"
              :show-file-list="true"
              accept=".xlsx,.xls"
              :limit="1"
              :on-exceed="handleExceed"
            >
              <div class="upload-icon">📤</div>
              <div class="el-upload__text">将 Excel 文件拖到此处，或 <em>点击上传</em></div>
              <template #tip>
                <div class="el-upload__tip">仅支持 .xlsx / .xls 格式，文件大小不超过 10MB</div>
              </template>
            </el-upload>

            <div class="upload-actions">
              <el-button
                type="primary"
                size="large"
                :loading="uploading"
                :disabled="!selectedFile"
                @click="submitUpload"
              >
                开始上传并解析
              </el-button>
            </div>

            <el-alert
              v-if="uploadResult"
              :title="uploadResult.title"
              :type="uploadResult.type"
              :description="uploadResult.description"
              show-icon
              class="upload-result"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- 店铺列表 Tab -->
      <el-tab-pane label="我的店铺" name="stores">
        <div class="section-toolbar">
          <el-button @click="loadStores">刷新</el-button>
          <el-tag type="info">共 {{ storeTotal }} 家店铺</el-tag>
        </div>
        <el-table :data="stores" v-loading="loadingStores" stripe border>
          <el-table-column prop="name" label="店铺名称" min-width="140" />
          <el-table-column prop="address" label="地址" min-width="200" show-overflow-tooltip />
          <el-table-column label="经纬度状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.geo_status === 'success' ? 'success' : row.geo_status === 'failed' ? 'danger' : 'warning'" size="small">
                {{ geoStatusLabel[row.geo_status] || row.geo_status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="area_sqm" label="面积(㎡)" width="90" />
          <el-table-column prop="machine_count" label="机器数" width="80" />
          <el-table-column label="运营状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'operating' ? 'success' : 'info'" size="small">
                {{ storeStatusLabel[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="是否成功" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.is_success === true" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="row.is_success === false" type="danger" size="small">失败</el-tag>
              <span v-else style="color:#ccc;font-size:12px">未标注</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="storeTotal > storePageSize"
          v-model:current-page="storePage"
          :page-size="storePageSize"
          :total="storeTotal"
          layout="prev, pager, next"
          style="margin-top:16px;justify-content:flex-end"
          @current-change="loadStores"
        />
      </el-tab-pane>

      <!-- 上传记录 Tab -->
      <el-tab-pane label="上传记录" name="records">
        <div class="section-toolbar">
          <el-button @click="loadUploadRecords">刷新</el-button>
        </div>
        <el-table :data="uploadRecords" v-loading="loadingRecords" stripe border>
          <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column label="数据类型" width="100">
            <template #default="{ row }">
              <el-tag size="small">{{ uploadTypeLabel[row.upload_type] || row.upload_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="解析状态" width="100">
            <template #default="{ row }">
              <el-tag :type="parseStatusColor[row.parse_status]" size="small">
                {{ parseStatusLabel[row.parse_status] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="parsed_rows" label="成功行" width="80" />
          <el-table-column prop="failed_rows" label="失败行" width="80" />
          <el-table-column label="分析状态" width="100">
            <template #default="{ row }">
              <el-tag :type="parseStatusColor[row.analysis_status] || 'info'" size="small">
                {{ parseStatusLabel[row.analysis_status] || row.analysis_status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="权重更新" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.weight_updated" type="success" size="small">已更新</el-tag>
              <span v-else style="color:#ccc;font-size:12px">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="上传时间" width="160" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="viewSummary(row)">查看分析</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 评分权重 Tab -->
      <el-tab-pane label="评分权重" name="weights">
        <div class="weights-header">
          <div class="weights-summary">
            <div class="summary-card" :class="{ active: changedRulesCount > 0 }">
              <div class="summary-num">{{ changedRulesCount }}</div>
              <div class="summary-label">权重已调整</div>
            </div>
            <div class="summary-card">
              <div class="summary-num">{{ scoringRules.length }}</div>
              <div class="summary-label">评分因子</div>
            </div>
            <div class="summary-card">
              <div class="summary-num">{{ totalUpdateCount }}</div>
              <div class="summary-label">累计学习次数</div>
            </div>
          </div>
          <el-alert
            v-if="changedRulesCount > 0"
            :title="`系统已根据您的历史数据自动调整了 ${changedRulesCount} 项评分权重，评估结果将更符合您的实际运营经验。`"
            type="success"
            show-icon
            :closable="false"
            style="flex:1"
          />
          <el-alert
            v-else
            title="权重尚未被数据驱动调整。请上传历史门店数据（基础信息 + 会员画像），系统将自动学习并优化权重。"
            type="info"
            show-icon
            :closable="false"
            style="flex:1"
          />
        </div>

        <el-table :data="scoringRules" v-loading="loadingRules" stripe border row-class-name="weight-row">
          <el-table-column prop="dimension_name" label="评分维度" width="120">
            <template #default="{ row }">
              <span class="dim-badge" :class="'dim-' + row.dimension">{{ row.dimension_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="sub_factor" label="子因子" min-width="150" />
          <el-table-column label="基础权重" width="100" align="center">
            <template #default="{ row }">
              <span class="weight-base">{{ (row.base_weight * 100).toFixed(1) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="权重变化" width="160" align="center">
            <template #default="{ row }">
              <div v-if="row.dynamic_weight && row.dynamic_weight !== row.base_weight" class="weight-change">
                <span class="weight-old">{{ (row.base_weight * 100).toFixed(1) }}%</span>
                <span class="weight-arrow" :class="row.dynamic_weight > row.base_weight ? 'up' : 'down'">
                  {{ row.dynamic_weight > row.base_weight ? '↑' : '↓' }}
                </span>
                <span class="weight-new" :class="row.dynamic_weight > row.base_weight ? 'up' : 'down'">
                  {{ (row.dynamic_weight * 100).toFixed(1) }}%
                </span>
              </div>
              <span v-else style="color:#ccc;font-size:12px">未变化</span>
            </template>
          </el-table-column>
          <el-table-column label="生效权重" width="100" align="center">
            <template #default="{ row }">
              <strong :class="row.dynamic_weight && row.dynamic_weight !== row.base_weight ? 'weight-effective-changed' : ''">
                {{ (row.effective_weight * 100).toFixed(1) }}%
              </strong>
            </template>
          </el-table-column>
          <el-table-column label="学习次数" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.update_count > 0" type="warning" size="small" round>
                {{ row.update_count }}次
              </el-tag>
              <span v-else style="color:#ccc;font-size:12px">-</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="row.last_updated_by === 'data_analysis' ? 'success' : 'info'" size="small">
                {{ updatedByLabel[row.last_updated_by] || row.last_updated_by }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="调整原因" min-width="220">
            <template #default="{ row }">
              <div v-if="row.update_reason" class="update-reason">
                <span class="reason-icon">💡</span>
                <span>{{ row.update_reason }}</span>
              </div>
              <span v-else style="color:#ccc;font-size:12px">使用系统默认权重</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 分析摘要对话框 -->
    <el-dialog v-model="summaryDialogVisible" title="数据分析摘要" width="600px">
      <pre style="white-space:pre-wrap;word-break:break-all;font-family:'Microsoft YaHei',sans-serif;font-size:14px;line-height:1.8;color:#333;background:#f8f9fa;padding:16px;border-radius:6px">{{ currentSummary }}</pre>
      <template #footer>
        <el-button @click="summaryDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const activeTab = ref('upload')
const uploadType = ref('basic')
const selectedFile = ref<File | null>(null)
const uploading = ref(false)
const downloading = ref<string | null>(null)
const uploadResult = ref<any>(null)

const stores = ref<any[]>([])
const storeTotal = ref(0)
const storePage = ref(1)
const storePageSize = ref(20)
const loadingStores = ref(false)

const uploadRecords = ref<any[]>([])
const loadingRecords = ref(false)

const scoringRules = ref<any[]>([])
const loadingRules = ref(false)

const summaryDialogVisible = ref(false)
const currentSummary = ref('')

// 权重可视化计算属性
const changedRulesCount = computed(() =>
  scoringRules.value.filter(r => r.dynamic_weight && Math.abs(r.dynamic_weight - r.base_weight) > 0.001).length
)
const totalUpdateCount = computed(() =>
  scoringRules.value.reduce((sum, r) => sum + (r.update_count || 0), 0)
)

const templates = [
  { type: 'basic',    name: '基础信息模板', description: '店铺名称、地址、面积、机器数等（其他模板的前置依赖）' },
  { type: 'revenue',  name: '营收数据模板', description: '月度/年度营收、成本、净利润、客流量数据' },
  { type: 'member',   name: '会员画像模板', description: '年龄分布、性别、职业、消费行为及各年龄段营收贡献' },
  { type: 'hardware', name: '硬件配置模板', description: '显卡型号分布、座位分类、外设品牌、网络带宽' }
]

const geoStatusLabel: Record<string, string> = { pending: '待转换', success: '已转换', failed: '转换失败' }
const storeStatusLabel: Record<string, string> = { operating: '运营中', closed: '已关店', planned: '规划中' }
const uploadTypeLabel: Record<string, string> = { basic: '基础信息', revenue: '营收数据', member: '会员画像', hardware: '硬件配置' }
const parseStatusLabel: Record<string, string> = { pending: '待处理', processing: '处理中', success: '成功', failed: '失败' }
const parseStatusColor: Record<string, string> = { pending: 'info', processing: 'warning', success: 'success', failed: 'danger' }
const updatedByLabel: Record<string, string> = { system: '系统默认', data_analysis: '数据驱动', manual: '手动调整' }

async function downloadTemplate(type: string) {
  downloading.value = type
  try {
    // 直接使用 fetch 绕过 axios 响应拦截器
    // （axios 拦截器会解包 response.data，导致二进制 blob 数据丢失）
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/data/templates/${type}`, {
      method: 'GET',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!response.ok) {
      const errText = await response.text().catch(() => `HTTP ${response.status}`)
      throw new Error(errText || `HTTP ${response.status}`)
    }
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const names: Record<string, string> = { basic: '基础信息模板', revenue: '营收数据模板', member: '会员画像模板', hardware: '硬件配置模板' }
    link.setAttribute('download', `${names[type] || type}.xlsx`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
    ElMessage.success('模板下载成功')
  } catch (e: any) {
    ElMessage.error('模板下载失败：' + (e.message || '未知错误'))
  } finally {
    downloading.value = null
  }
}

function handleFileChange(file: any) {
  selectedFile.value = file.raw
  uploadResult.value = null
}

function handleExceed() {
  ElMessage.warning('每次只能上传一个文件')
}

async function submitUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  uploadResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('upload_type', uploadType.value)
    const res = await api.post('/data/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    const data: any = (res as any)?.data ?? res
    uploadResult.value = {
      type: data.parse_status === 'success' ? 'success' : 'warning',
      title: data.parse_status === 'success' ? '上传解析成功' : '上传完成（有失败行）',
      description: `${data.message}。系统正在后台进行数据分析和评分权重优化，请稍后在"上传记录"中查看分析结果。`
    }
    loadStores(); loadUploadRecords(); loadScoringRules()
  } catch (e: any) {
    uploadResult.value = { type: 'error', title: '上传失败', description: e.response?.data?.detail || '请检查文件格式' }
  } finally {
    uploading.value = false
  }
}

async function loadStores() {
  loadingStores.value = true
  try {
    const res = await api.get('/data/stores', { params: { page: storePage.value, page_size: storePageSize.value } })
    const storeRes: any = res
    stores.value = storeRes?.items ?? storeRes?.data?.items ?? []
    storeTotal.value = storeRes?.total ?? storeRes?.data?.total ?? 0
  } catch { ElMessage.error('加载店铺列表失败') } finally { loadingStores.value = false }
}

async function loadUploadRecords() {
  loadingRecords.value = true
  try {
    const res = await api.get('/data/uploads')
    const recRes: any = res
    uploadRecords.value = recRes?.items ?? recRes?.data?.items ?? []
  } catch { ElMessage.error('加载上传记录失败') } finally { loadingRecords.value = false }
}

async function loadScoringRules() {
  loadingRules.value = true
  try {
    const res = await api.get('/data/scoring-rules')
    const rulesRes: any = res
    scoringRules.value = Array.isArray(rulesRes) ? rulesRes : (rulesRes?.data ?? [])
  } catch { ElMessage.error('加载评分规则失败') } finally { loadingRules.value = false }
}

function viewSummary(row: any) {
  currentSummary.value = row.analysis_summary || '暂无分析结果，请等待后台分析完成。'
  summaryDialogVisible.value = true
}

onMounted(() => { loadStores(); loadUploadRecords(); loadScoringRules() })
</script>

<style scoped>
.data-view { padding: 0; }
.page-header { margin-bottom: 24px; }
.page-header h2 { font-size: 22px; font-weight: 600; color: #1a1a2e; margin: 0 0 6px 0; }
.subtitle { color: #666; font-size: 14px; margin: 0; }
.data-tabs { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.template-cards h3, .upload-area-section h3 { font-size: 15px; font-weight: 600; color: #333; margin: 0 0 8px 0; }
.tip { color: #888; font-size: 13px; margin-bottom: 16px; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-bottom: 32px; }
.template-card { display: flex; align-items: center; gap: 12px; padding: 16px; border: 1px solid #e8e8e8; border-radius: 8px; background: #fafafa; }
.template-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.template-card__info { flex: 1; min-width: 0; }
.template-card__name { font-weight: 600; font-size: 14px; color: #333; margin-bottom: 4px; }
.template-card__desc { font-size: 12px; color: #888; line-height: 1.4; }
.upload-type-selector { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; font-size: 14px; color: #555; }
.upload-dragger { width: 100%; }
.upload-icon { font-size: 48px; margin-bottom: 8px; }
.upload-actions { margin-top: 16px; }
.upload-result { margin-top: 16px; }
.section-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }

/* 权重可视化样式 */
.weights-header { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.weights-summary { display: flex; gap: 12px; }
.summary-card { min-width: 90px; padding: 12px 16px; background: #f8f9fa; border: 1px solid #e8e8e8; border-radius: 8px; text-align: center; }
.summary-card.active { background: #f0faf0; border-color: #67c23a; }
.summary-num { font-size: 24px; font-weight: 700; color: #1a1a2e; line-height: 1.2; }
.summary-card.active .summary-num { color: #67c23a; }
.summary-label { font-size: 12px; color: #888; margin-top: 4px; }
.dim-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: #f0f2f5; color: #555; }
.dim-badge.dim-traffic { background: #e8f4fd; color: #1890ff; }
.dim-badge.dim-competition { background: #fff7e6; color: #fa8c16; }
.dim-badge.dim-population { background: #f6ffed; color: #52c41a; }
.dim-badge.dim-rent { background: #fff1f0; color: #f5222d; }
.dim-badge.dim-facility { background: #f9f0ff; color: #722ed1; }
.dim-badge.dim-policy { background: #e6fffb; color: #13c2c2; }
.weight-base { color: #888; font-size: 13px; }
.weight-change { display: flex; align-items: center; gap: 4px; justify-content: center; }
.weight-old { color: #aaa; font-size: 12px; text-decoration: line-through; }
.weight-arrow { font-size: 16px; font-weight: 700; }
.weight-arrow.up { color: #52c41a; }
.weight-arrow.down { color: #f5222d; }
.weight-new { font-size: 14px; font-weight: 700; }
.weight-new.up { color: #52c41a; }
.weight-new.down { color: #f5222d; }
.weight-effective-changed { color: #1890ff; }
.update-reason { display: flex; align-items: flex-start; gap: 6px; font-size: 13px; color: #555; line-height: 1.5; }
.reason-icon { flex-shrink: 0; }
</style>
