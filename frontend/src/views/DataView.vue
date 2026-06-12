<template>
  <div class="data-view">
    <div class="page-header">
      <h2>历史数据管理</h2>
      <p class="subtitle">上传结构化运营数据和经验文档，系统将用于 RAG 检索、报告生成和待确认的权重优化建议。</p>
    </div>

    <el-tabs v-model="activeTab" class="data-tabs">
      <el-tab-pane label="上传数据" name="upload">
        <div class="upload-section">
          <section class="template-cards">
            <h3>第一步：下载标准模板</h3>
            <p class="tip">结构化数据仍按标准模板上传。基础信息需要先上传，后续营收、会员、硬件数据会按店铺名称关联。</p>
            <div class="card-grid">
              <div v-for="tpl in templates" :key="tpl.type" class="template-card">
                <div class="template-card__info">
                  <div class="template-card__name">{{ tpl.name }}</div>
                  <div class="template-card__desc">{{ tpl.description }}</div>
                </div>
                <el-button type="primary" size="small" :loading="downloading === tpl.type" @click="downloadTemplate(tpl.type)">
                  下载模板
                </el-button>
              </div>
            </div>
          </section>

          <section class="upload-area-section">
            <h3>第二步：上传填写好的 Excel</h3>
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
              <div class="upload-icon">↑</div>
              <div class="el-upload__text">将 Excel 文件拖到此处，或 <em>点击上传</em></div>
              <template #tip>
                <div class="el-upload__tip">仅支持 .xlsx / .xls，文件大小不超过 10MB</div>
              </template>
            </el-upload>

            <div class="upload-actions">
              <el-button type="primary" size="large" :loading="uploading" :disabled="!selectedFile" @click="submitUpload">
                开始上传并解析
              </el-button>
            </div>

            <el-alert v-if="uploadResult" :title="uploadResult.title" :type="uploadResult.type" :description="uploadResult.description" show-icon class="upload-result" />
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="历史数据分析" name="analysis">
        <AnalysisView />
      </el-tab-pane>

      <el-tab-pane label="经验文档" name="documents">
        <section class="document-upload">
          <h3>上传经验文档 / 调研报告</h3>
          <p class="tip">支持 TXT、Word、PDF。上传后会解析文本、写入知识库，并生成待确认的评分权重建议。</p>

          <div class="document-form">
            <div class="form-row">
              <span class="form-label">归属范围</span>
              <el-radio-group v-model="docScopeType">
                <el-radio-button value="brand">品牌通用</el-radio-button>
                <el-radio-button value="store">绑定门店</el-radio-button>
                <el-radio-button value="candidate">候选地址</el-radio-button>
              </el-radio-group>
            </div>

            <div v-if="docScopeType === 'store'" class="form-row">
              <span class="form-label">选择门店</span>
              <el-select v-model="docStoreId" placeholder="选择已有门店" filterable style="width: 320px">
                <el-option v-for="store in stores" :key="store.id" :label="store.name" :value="store.id" />
              </el-select>
            </div>

            <div v-if="docScopeType === 'candidate'" class="form-row">
              <span class="form-label">候选地址</span>
              <el-input v-model="docCandidateAddress" placeholder="填写候选地址或商圈名称" style="max-width: 520px" />
            </div>
          </div>

          <el-upload
            class="upload-dragger"
            drag
            :auto-upload="false"
            :on-change="handleDocumentFileChange"
            :show-file-list="true"
            accept=".txt,.docx,.pdf"
            :limit="1"
            :on-exceed="handleExceed"
          >
            <div class="upload-icon">↑</div>
            <div class="el-upload__text">将经验文档拖到此处，或 <em>点击上传</em></div>
            <template #tip>
              <div class="el-upload__tip">首版不做 OCR，扫描版 PDF 需要先转成可复制文本</div>
            </template>
          </el-upload>

          <div class="upload-actions">
            <el-button type="primary" size="large" :loading="documentUploading" :disabled="!selectedDocumentFile" @click="submitDocumentUpload">
              上传并进入知识库
            </el-button>
          </div>

          <el-alert v-if="documentUploadResult" :title="documentUploadResult.title" :type="documentUploadResult.type" :description="documentUploadResult.description" show-icon class="upload-result" />
        </section>

        <section class="section-block">
          <div class="section-toolbar">
            <h3>文档知识库</h3>
            <el-button @click="loadDocuments">刷新</el-button>
          </div>
          <el-table :data="documents" v-loading="loadingDocuments" stripe border>
            <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
            <el-table-column label="归属" width="120">
              <template #default="{ row }">{{ scopeLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="解析状态" width="100">
              <template #default="{ row }">
                <el-tag :type="parseStatusColor[row.parse_status]" size="small">{{ parseStatusLabel[row.parse_status] || row.parse_status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="知识库" width="100">
              <template #default="{ row }">
                <el-tag :type="vectorStatusColor[row.vector_status] || 'info'" size="small">{{ vectorStatusLabel[row.vector_status] || row.vector_status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="文本块" width="80" />
            <el-table-column prop="pending_insight_count" label="待确认建议" width="110" />
            <el-table-column prop="created_at" label="上传时间" width="160" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="viewDocument(row)">查看</el-button>
                <el-button type="danger" link size="small" @click="deleteDocument(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="知识库内容" name="knowledge">
        <section class="section-block">
          <div class="section-toolbar">
            <h3>RAG 知识库</h3>
            <el-select v-model="knowledgeSourceType" clearable placeholder="全部来源" style="width: 180px" @change="loadKnowledgeVectors">
              <el-option label="历史门店经验" value="store_experience" />
              <el-option label="经验文档" value="document_experience" />
              <el-option label="评估案例" value="evaluation_result" />
              <el-option label="历史分析结论" value="analysis_insight" />
            </el-select>
            <el-button @click="loadKnowledgeVectors">刷新</el-button>
            <el-tag type="info">共 {{ knowledgeTotal }} 条</el-tag>
          </div>
          <el-alert
            v-if="knowledgeWarning"
            :title="knowledgeWarning"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 12px"
          />
          <el-table :data="knowledgeVectors" v-loading="loadingKnowledge" stripe border>
            <el-table-column prop="source_type_label" label="来源类型" width="130" />
            <el-table-column prop="source_name" label="来源名称" width="180" show-overflow-tooltip />
            <el-table-column prop="content_preview" label="内容预览" min-width="320" show-overflow-tooltip />
            <el-table-column prop="updated_at" label="更新时间" width="160">
              <template #default="{ row }">{{ row.updated_at || row.created_at }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="danger" link size="small" @click="deleteKnowledgeVector(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

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
              <span v-else class="muted">未标注</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button type="danger" link size="small" @click="deleteStore(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

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
              <el-tag :type="parseStatusColor[row.parse_status]" size="small">{{ parseStatusLabel[row.parse_status] || row.parse_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="parsed_rows" label="成功行" width="80" />
          <el-table-column prop="failed_rows" label="失败行" width="80" />
          <el-table-column label="分析状态" width="100">
            <template #default="{ row }">
              <el-tag :type="parseStatusColor[row.analysis_status] || 'info'" size="small">{{ parseStatusLabel[row.analysis_status] || row.analysis_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="权重更新" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.weight_updated" type="success" size="small">已更新</el-tag>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="上传时间" width="160" />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="viewSummary(row)">查看分析</el-button>
              <el-button type="danger" link size="small" @click="deleteUploadRecord(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="评分模型" name="model">
        <div class="model-panel">
          <div class="model-header">
            <div>
              <h3>评分模型配置</h3>
              <p>按“大类 - 小类”维护评分权重。新增或修改后会立即参与新地址评估，保存为模型版本用于留痕。</p>
            </div>
            <div class="model-actions">
              <el-button @click="loadScoringRules">刷新权重</el-button>
              <el-button type="primary" @click="openRuleDialog()">新增小类</el-button>
              <el-button type="success" @click="createVersion">保存为新模型版本</el-button>
            </div>
          </div>

          <section class="model-section">
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
                      <div class="factor-desc">{{ factorDescription(row) }}</div>
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

          <section class="model-section">
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
      </el-tab-pane>
    </el-tabs>

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

    <el-dialog v-model="summaryDialogVisible" title="数据分析摘要" width="600px">
      <pre class="dialog-pre">{{ currentSummary }}</pre>
      <template #footer>
        <el-button @click="summaryDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="documentDialogVisible" title="经验文档详情" width="760px">
      <div v-if="currentDocument" class="document-detail">
        <div class="detail-summary">
          <strong>{{ currentDocument.filename }}</strong>
          <span>{{ currentDocument.summary || '暂无摘要' }}</span>
        </div>
        <h4>待确认建议</h4>
        <el-table :data="currentDocument.insights || []" border stripe>
          <el-table-column prop="dimension_name" label="影响维度" width="110" />
          <el-table-column prop="insight" label="建议" min-width="220" show-overflow-tooltip />
          <el-table-column label="建议权重" width="100">
            <template #default="{ row }">{{ row.suggested_weight ? percent(row.suggested_weight) : '-' }}</template>
          </el-table-column>
          <el-table-column label="置信度" width="80">
            <template #default="{ row }">{{ percent(row.confidence) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="insightStatusColor[row.status] || 'info'" size="small">{{ insightStatusLabel[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" type="primary" link size="small" @click="approveInsight(row)">确认</el-button>
              <el-button v-if="row.status === 'pending'" type="danger" link size="small" @click="rejectInsight(row)">忽略</el-button>
            </template>
          </el-table-column>
        </el-table>
        <h4>文本块预览</h4>
        <div class="chunk-list">
          <div v-for="chunk in (currentDocument.chunks || []).slice(0, 5)" :key="chunk.index" class="chunk-item">
            {{ chunk.content }}
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import AnalysisView from './AnalysisView.vue'

const route = useRoute()
const activeTab = ref(String(route.query.tab || 'upload'))
const uploadType = ref('basic')
const selectedFile = ref<File | null>(null)
const uploading = ref(false)
const downloading = ref<string | null>(null)
const uploadResult = ref<any>(null)

const selectedDocumentFile = ref<File | null>(null)
const docScopeType = ref('brand')
const docStoreId = ref<number | null>(null)
const docCandidateAddress = ref('')
const documentUploading = ref(false)
const documentUploadResult = ref<any>(null)
const documents = ref<any[]>([])
const loadingDocuments = ref(false)
const documentDialogVisible = ref(false)
const currentDocument = ref<any>(null)

const knowledgeVectors = ref<any[]>([])
const knowledgeTotal = ref(0)
const knowledgeSourceType = ref('')
const knowledgeWarning = ref('')
const loadingKnowledge = ref(false)

const stores = ref<any[]>([])
const storeTotal = ref(0)
const storePage = ref(1)
const storePageSize = ref(20)
const loadingStores = ref(false)

const uploadRecords = ref<any[]>([])
const loadingRecords = ref(false)

const scoringRules = ref<any[]>([])
const loadingRules = ref(false)
const versions = ref<any[]>([])
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

const summaryDialogVisible = ref(false)
const currentSummary = ref('')

const changedRulesCount = computed(() =>
  scoringRules.value.filter(r => r.dynamic_weight && Math.abs(r.dynamic_weight - r.base_weight) > 0.001).length
)
const totalUpdateCount = computed(() =>
  scoringRules.value.reduce((sum, r) => sum + (r.update_count || 0), 0)
)
const groupedRules = computed(() => {
  const map = new Map<string, any>()
  for (const option of dimensionOptions) {
    map.set(option.value, { dimension: option.value, dimension_name: option.label, total_weight: 0, rules: [] })
  }
  for (const rule of scoringRules.value) {
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

const templates = [
  { type: 'basic', name: '基础信息模板', description: '店铺名称、地址、面积、机器数等，其他模板的前置依赖' },
  { type: 'revenue', name: '营收数据模板', description: '月度营收、成本、净利润、客流量数据' },
  { type: 'member', name: '会员画像模板', description: '年龄、职业、消费行为及营收贡献' },
  { type: 'hardware', name: '硬件配置模板', description: '显卡、座位、外设、带宽等配置' }
]

const geoStatusLabel: Record<string, string> = { pending: '待转换', success: '已转换', failed: '转换失败' }
const storeStatusLabel: Record<string, string> = { operating: '运营中', closed: '已关店', planned: '规划中' }
const uploadTypeLabel: Record<string, string> = { basic: '基础信息', revenue: '营收数据', member: '会员画像', hardware: '硬件配置' }
const parseStatusLabel: Record<string, string> = { pending: '待处理', processing: '处理中', success: '成功', failed: '失败' }
const parseStatusColor: Record<string, string> = { pending: 'info', processing: 'warning', success: 'success', failed: 'danger' }
const vectorStatusLabel: Record<string, string> = { pending: '待入库', success: '已入库', partial: '部分入库', failed: '失败' }
const vectorStatusColor: Record<string, string> = { pending: 'info', success: 'success', partial: 'warning', failed: 'danger' }
const insightStatusLabel: Record<string, string> = { pending: '待确认', approved: '已生效', rejected: '已忽略' }
const insightStatusColor: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'info' }
const updatedByLabel: Record<string, string> = { system: '系统默认', data_analysis: '数据驱动', document_review: '文档确认', manual: '手动调整' }
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
  negative_overpass: '高架桥',
  negative_interchange: '立交桥',
  negative_underpass: '地下隧道',
  negative_railway: '火车道',
  negative_greenbelt: '大型绿化带',
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

const factorDescriptions: Record<string, string> = {
  foot_traffic: '衡量候选点周边基础人流和商业活跃度，通常来自商圈、POI 密度、道路可达性等综合判断。',
  transit_accessibility: '衡量公交、地铁等公共交通到达便利程度，越方便越利于扩大自然到店客群。',
  metro_distance: '候选点到最近地铁站的距离，距离越近通常越加分，但需要结合实际步行路径。',
  bus_distance: '候选点到公交站的距离和线路覆盖，反映低成本到达便利性。',
  negative_overpass: '附近高架桥可能割裂人流、遮挡门头或降低步行到达体验，属于减分因素。',
  negative_interchange: '立交桥会增加绕行和过街难度，可能削弱同一商圈内的自然客流。',
  negative_underpass: '地下隧道会影响可见性、动线和安全感，通常作为阻隔因素扣分。',
  negative_railway: '火车道或铁路会割裂生活圈和商业动线，影响实际可达客群。',
  negative_greenbelt: '大型绿化带、公园隔离带可能阻断步行路径，降低周边客群转化。',
  young_density: '18-35 岁主力电竞消费人群的密度，是判断潜在需求的核心因素。',
  university_nearby: '周边大学、高职院校带来的年轻客群，但需过滤小学、培训机构、停车场等误匹配。',
  resident_population: '周边稳定居住人口规模，决定基础复购和日常客流。',
  floating_population: '商圈流动人群规模，反映工作日、周末和夜间的外来消费机会。',
  age_18_24: '18-24 岁年轻用户占比，通常与电竞、夜间娱乐消费相关性更强。',
  age_25_34: '25-34 岁用户占比，反映稳定消费能力、会员充值和高客单潜力。',
  secondary_vocational_nearby: '中职、技校、高职等年轻客群来源，需结合政策限制和消费能力判断。',
  competitor_count: '周边有效电竞馆、网咖等竞品数量；过少可能需求不足，过多可能市场饱和。',
  competitor_distance: '竞品与候选点的距离，过近会直接分流，适度距离可证明商圈需求存在。',
  competitor_configuration: '竞品机器配置、显卡、显示器、座位等硬件水平，用于判断竞争强度。',
  competitor_price: '竞品小时价、包夜价、套餐价等价格信息，用于判断价格带和利润空间。',
  competitor_occupancy: '竞品上座率或分时段客流，反映真实需求和竞争压力。',
  competitor_open_years: '竞品经营年限，开业越久且稳定，说明商圈需求可能更成熟。',
  competitor_area: '竞品面积和机器规模，用于估算区域供给能力。',
  competitor_monthly_sales: '竞品月售或月营收估算，通常需要人工调研或合规外部数据补充。',
  competitor_annual_sales: '竞品年销售表现，用于趋势判断，通常不能完全依赖地图 API。',
  competitor_recharge: '竞品会员充值、活动力度、优惠策略，用于判断竞争强度和价格战风险。',
  same_category_capacity: '根据有效客群、消费频次、客单价和健康月营收估算该商圈还能容纳几家同品类店。',
  rent_ratio: '租金与预期营收的匹配程度，租金过高会压缩利润，是电竞馆选址核心成本项。',
  area_sqm: '可经营面积，影响机器数量、包间、休息区、消防通道和盈利上限。',
  floor: '楼层位置，一层或低楼层通常更利于可见性和到达，高楼层需更强导流。',
  frontage_visibility: '门头是否容易被看到，影响自然客流、品牌曝光和获客成本。',
  parking_convenience: '停车便利程度，大店、郊区店、夜间消费场景更需要关注。',
  fire_safety: '消防条件是否满足电竞馆/网吧类业态要求，不满足应作为高风险。',
  property_restriction: '物业、合同、业态限制、未成年人限制等，可能直接影响能否开店。',
  power_capacity: '电力容量是否能支撑大量电脑、空调和网络设备，影响改造成本和安全。',
  hvac_exhaust: '空调、新风、排烟条件，影响用户体验和消防/物业合规。',
  commercial_density: '周边餐饮、便利店、娱乐、停车等配套密度，反映消费氛围。',
  night_market: '夜市摊和夜间经济活跃度，能提升电竞馆夜间客流和停留时间。',
  food_business_hours: '餐饮是否营业到凌晨或 24 小时，决定夜间消费配套强度。',
  food_category: '烧烤、烤肉、小吃、快餐等品类与电竞客群匹配度。',
  food_open_years: '餐饮开业年限，越稳定越能证明周边消费环境成熟。',
  ktv: 'KTV 等娱乐业态能证明夜间娱乐消费氛围和年轻客群聚集。',
  bar: '酒吧反映夜间经济活跃度，但也需关注客群是否与电竞馆匹配。',
  billiards: '台球厅与电竞馆客群有重叠，可作为年轻娱乐消费的加分项。',
  escape_room: '密室/剧本杀等年轻娱乐业态，反映周边年轻消费氛围。',
  cinema: '电影院带来年轻客群和夜间消费场景，可增强商圈吸引力。',
  convenience_24h: '24 小时便利店反映夜间服务能力，对包夜和晚间客流有帮助。',
  relocation_housing: '回迁房可能带来年轻、价格敏感、近距离消费客群，需要结合消费能力判断。',
  apartment: '公寓通常聚集年轻租住人群，对电竞馆会员和夜间消费有潜力。',
  policy_risk: '证照、消防、物业、经营时间等政策合规风险，风险高时应明显扣分。',
  policy_redline_200m: '小学、幼儿园、中学、政府机构 200m 红线，命中后应作为强风险提示。',
}

function percent(value: number) {
  return `${((value || 0) * 100).toFixed(1)}%`
}

function factorLabel(key: string) {
  return factorLabels[key] || key || '未命名小类'
}

function factorDescription(row: any) {
  return factorDescriptions[row?.sub_factor] || row?.update_reason || '自定义评分小类，请在编辑时补充说明，便于后续模型复盘。'
}

function syncDimensionName() {
  const item = dimensionOptions.find(option => option.value === ruleForm.value.dimension)
  if (item) ruleForm.value.dimension_name = item.label
}

function scopeLabel(row: any) {
  if (row.scope_type === 'store') return row.store_name || '绑定门店'
  if (row.scope_type === 'candidate') return row.candidate_address || '候选地址'
  return '品牌通用'
}

async function downloadTemplate(type: string) {
  downloading.value = type
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/data/templates/${type}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` }
    })
    if (!response.ok) throw new Error(await response.text())
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
    ElMessage.error(`模板下载失败：${e.message || '未知错误'}`)
  } finally {
    downloading.value = null
  }
}

function handleFileChange(file: any) {
  selectedFile.value = file.raw
  uploadResult.value = null
}

function handleDocumentFileChange(file: any) {
  selectedDocumentFile.value = file.raw
  documentUploadResult.value = null
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
      description: `${data.message}。系统会在后台进行数据分析和评分权重优化。`
    }
    loadStores(); loadUploadRecords(); loadScoringRules()
  } catch (e: any) {
    uploadResult.value = { type: 'error', title: '上传失败', description: e.response?.data?.detail || '请检查文件格式' }
  } finally {
    uploading.value = false
  }
}

async function submitDocumentUpload() {
  if (!selectedDocumentFile.value) return
  if (docScopeType.value === 'store' && !docStoreId.value) {
    ElMessage.warning('请选择要绑定的门店')
    return
  }
  if (docScopeType.value === 'candidate' && !docCandidateAddress.value.trim()) {
    ElMessage.warning('请填写候选地址')
    return
  }
  documentUploading.value = true
  documentUploadResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', selectedDocumentFile.value)
    formData.append('scope_type', docScopeType.value)
    if (docStoreId.value) formData.append('store_id', String(docStoreId.value))
    if (docCandidateAddress.value.trim()) formData.append('candidate_address', docCandidateAddress.value.trim())
    const res = await api.post('/data/documents/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    const data: any = (res as any)?.data ?? res
    documentUploadResult.value = {
      type: data.parse_status === 'success' ? 'success' : 'warning',
      title: data.parse_status === 'success' ? '文档已进入知识库' : '文档处理未完成',
      description: `${data.parse_message || ''} ${data.vector_message || ''}，待确认建议 ${data.pending_insight_count || 0} 条。`
    }
    await loadDocuments()
  } catch (e: any) {
    documentUploadResult.value = { type: 'error', title: '文档上传失败', description: e.response?.data?.detail || '请检查文件格式和内容' }
  } finally {
    documentUploading.value = false
  }
}

async function loadStores() {
  loadingStores.value = true
  try {
    const res = await api.get('/data/stores', { params: { page: storePage.value, page_size: storePageSize.value } })
    const data: any = res
    stores.value = data?.items ?? data?.data?.items ?? []
    storeTotal.value = data?.total ?? data?.data?.total ?? 0
  } catch {
    ElMessage.error('加载店铺列表失败')
  } finally {
    loadingStores.value = false
  }
}

async function loadUploadRecords() {
  loadingRecords.value = true
  try {
    const res = await api.get('/data/uploads')
    const data: any = res
    uploadRecords.value = data?.items ?? data?.data?.items ?? []
  } catch {
    ElMessage.error('加载上传记录失败')
  } finally {
    loadingRecords.value = false
  }
}

async function loadDocuments() {
  loadingDocuments.value = true
  try {
    const res = await api.get('/data/documents')
    const data: any = res
    documents.value = data?.items ?? data?.data?.items ?? []
  } catch {
    ElMessage.error('加载文档知识库失败')
  } finally {
    loadingDocuments.value = false
  }
}

async function loadKnowledgeVectors() {
  loadingKnowledge.value = true
  knowledgeWarning.value = ''
  try {
    const params: any = { page: 1, page_size: 50 }
    if (knowledgeSourceType.value) params.source_type = knowledgeSourceType.value
    const res = await api.get('/data/knowledge-vectors', { params })
    const data: any = res
    knowledgeVectors.value = data?.items ?? data?.data?.items ?? []
    knowledgeTotal.value = data?.total ?? data?.data?.total ?? 0
    knowledgeWarning.value = data?.warning ?? data?.data?.warning ?? ''
  } catch {
    ElMessage.error('加载知识库内容失败')
  } finally {
    loadingKnowledge.value = false
  }
}

async function loadScoringRules() {
  loadingRules.value = true
  try {
    const res = await api.get('/data/scoring-rules')
    const data: any = res
    scoringRules.value = Array.isArray(data) ? data : (data?.data ?? [])
  } catch {
    ElMessage.error('加载评分规则失败')
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
  await Promise.all([loadScoringRules(), loadVersions()])
}

async function removeRule(row: any) {
  await ElMessageBox.confirm(`确认停用「${factorLabel(row.sub_factor)}」？停用后不会参与后续评分。`, '停用评分小类', { type: 'warning' })
  await api.delete(`/data/scoring-rules/${row.id}`)
  ElMessage.success('评分小类已停用')
  await Promise.all([loadScoringRules(), loadVersions()])
}

async function createVersion() {
  const name = `手动权重模型 ${new Date().toLocaleString()}`
  await api.post('/model-versions', {
    name,
    description: '由当前手动细分权重保存的模型版本',
    activate: true,
  })
  ElMessage.success('模型版本已保存并生效')
  await Promise.all([loadScoringRules(), loadVersions()])
}

async function activate(row: any) {
  await ElMessageBox.confirm(`确认启用模型「${row.name}」？`, '启用模型', { type: 'warning' })
  await api.post(`/model-versions/${row.id}/activate`)
  ElMessage.success('模型版本已生效')
  await Promise.all([loadScoringRules(), loadVersions()])
}

async function deleteKnowledgeVector(row: any) {
  await ElMessageBox.confirm(
    `确认删除这条知识库内容？删除后不会再被 RAG 检索、相似案例和报告引用。`,
    '删除知识库内容',
    { type: 'warning' }
  )
  await api.delete(`/data/knowledge-vectors/${row.id}`)
  ElMessage.success('知识库内容已删除')
  await loadKnowledgeVectors()
}

async function viewDocument(row: any) {
  try {
    const res = await api.get(`/data/documents/${row.id}`)
    currentDocument.value = (res as any)?.data ?? res
    documentDialogVisible.value = true
  } catch {
    ElMessage.error('加载文档详情失败')
  }
}

async function deleteDocument(row: any) {
  await ElMessageBox.confirm(
    `确认删除文档「${row.filename}」？删除后会移除文档记录、提炼建议和知识库向量。`,
    '删除经验文档',
    { type: 'warning' }
  )
  await api.delete(`/data/documents/${row.id}`)
  ElMessage.success('文档已删除')
  if (currentDocument.value?.id === row.id) {
    documentDialogVisible.value = false
    currentDocument.value = null
  }
  await loadDocuments()
  await loadKnowledgeVectors()
  await loadScoringRules()
}

async function approveInsight(row: any) {
  try {
    await api.post(`/data/document-insights/${row.id}/approve`)
    ElMessage.success('建议已确认生效')
    await loadDocuments()
    await loadScoringRules()
    if (currentDocument.value) await viewDocument(currentDocument.value)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '确认失败')
  }
}

async function rejectInsight(row: any) {
  try {
    await api.post(`/data/document-insights/${row.id}/reject`, { note: '' })
    ElMessage.success('建议已忽略')
    await loadDocuments()
    if (currentDocument.value) await viewDocument(currentDocument.value)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '忽略失败')
  }
}

function viewSummary(row: any) {
  currentSummary.value = row.analysis_summary || '暂无分析结果，请等待后台分析完成。'
  summaryDialogVisible.value = true
}

async function deleteUploadRecord(row: any) {
  await ElMessageBox.confirm(
    `确认删除上传记录「${row.filename}」？营收/会员/硬件上传会同步删除本次解析出的明细数据；基础信息上传不会自动删除门店本体。`,
    '删除上传记录',
    { type: 'warning' }
  )
  await api.delete(`/data/uploads/${row.id}`)
  ElMessage.success('上传记录已删除')
  await Promise.all([loadUploadRecords(), loadStores(), loadScoringRules(), loadKnowledgeVectors()])
}

async function deleteStore(row: any) {
  await ElMessageBox.confirm(
    `确认删除店铺「${row.name}」？该店铺的营收、会员、硬件明细和门店经验知识库内容也会被删除。`,
    '删除店铺',
    { type: 'warning' }
  )
  await api.delete(`/data/stores/${row.id}`)
  ElMessage.success('店铺已删除')
  await Promise.all([loadStores(), loadUploadRecords(), loadKnowledgeVectors(), loadScoringRules()])
}

onMounted(() => {
  loadStores()
  loadUploadRecords()
  loadDocuments()
  loadKnowledgeVectors()
  loadScoringRules()
  loadVersions()
})
</script>

<style scoped>
.data-view { padding: 0; }
.page-header { margin-bottom: 24px; }
.page-header h2 { font-size: 22px; font-weight: 600; color: #1a1a2e; margin: 0 0 6px; }
.subtitle { color: #666; font-size: 14px; margin: 0; }
.data-tabs { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.template-cards h3, .upload-area-section h3, .document-upload h3, .section-block h3 { font-size: 15px; font-weight: 600; color: #333; margin: 0 0 8px; }
.tip { color: #777; font-size: 13px; margin: 0 0 16px; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-bottom: 32px; }
.template-card { display: flex; align-items: center; gap: 12px; padding: 16px; border: 1px solid #e8e8e8; border-radius: 8px; background: #fafafa; }
.template-card__info { flex: 1; min-width: 0; }
.template-card__name { font-weight: 600; font-size: 14px; color: #333; margin-bottom: 4px; }
.template-card__desc { font-size: 12px; color: #777; line-height: 1.4; }
.upload-type-selector, .form-row { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; font-size: 14px; color: #555; flex-wrap: wrap; }
.form-label { width: 72px; color: #555; }
.upload-dragger { width: 100%; }
.upload-icon { font-size: 42px; line-height: 1; margin-bottom: 8px; color: #409eff; }
.upload-actions { margin-top: 16px; }
.upload-result { margin-top: 16px; }
.document-upload { margin-bottom: 28px; }
.document-form { margin: 8px 0 12px; }
.section-block { margin-top: 24px; }
.section-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.section-toolbar h3 { margin-right: auto; }
.muted { color: #aaa; font-size: 12px; }
.weights-header { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.weights-summary { display: flex; gap: 12px; }
.summary-card { min-width: 90px; padding: 12px 16px; background: #f8f9fa; border: 1px solid #e8e8e8; border-radius: 8px; text-align: center; }
.summary-card.active { background: #f0faf0; border-color: #67c23a; }
.summary-num { font-size: 24px; font-weight: 700; color: #1a1a2e; line-height: 1.2; }
.summary-card.active .summary-num { color: #67c23a; }
.summary-label { font-size: 12px; color: #777; margin-top: 4px; }
.dim-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: #f0f2f5; color: #555; }
.dim-badge.dim-traffic { background: #e8f4fd; color: #1890ff; }
.dim-badge.dim-competition { background: #fff7e6; color: #fa8c16; }
.dim-badge.dim-population { background: #f6ffed; color: #52c41a; }
.dim-badge.dim-rent { background: #fff1f0; color: #f5222d; }
.dim-badge.dim-facility { background: #f9f0ff; color: #722ed1; }
.dim-badge.dim-policy { background: #e6fffb; color: #13c2c2; }
.weight-base { color: #777; font-size: 13px; }
.dialog-pre { white-space: pre-wrap; word-break: break-all; font-family: "Microsoft YaHei", sans-serif; font-size: 14px; line-height: 1.8; color: #333; background: #f8f9fa; padding: 16px; border-radius: 6px; }
.document-detail { display: flex; flex-direction: column; gap: 14px; }
.detail-summary { display: flex; flex-direction: column; gap: 8px; color: #444; line-height: 1.6; }
.document-detail h4 { margin: 4px 0 0; font-size: 14px; color: #333; }
.chunk-list { display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow: auto; }
.chunk-item { padding: 10px 12px; background: #f8f9fa; border: 1px solid #ebeef5; border-radius: 6px; color: #555; font-size: 13px; line-height: 1.6; }
.model-panel { display: flex; flex-direction: column; gap: 18px; }
.model-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.model-header h3 { margin: 0 0 6px; color: #1a1a2e; }
.model-header p { margin: 0; color: #666; line-height: 1.6; }
.model-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.model-section { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 16px; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.section-head h3 { margin: 0; color: #1a1a2e; }
.hint { color: #909399; font-size: 12px; }
.dimension-list { display: grid; grid-template-columns: 1fr; gap: 14px; }
.dimension-card { border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden; }
.dimension-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; background: #f7f9fc; border-bottom: 1px solid #ebeef5; }
.dimension-name { font-weight: 700; color: #1f2d3d; }
.dimension-key, .factor-key { margin-top: 3px; color: #909399; font-size: 12px; font-family: Consolas, monospace; }
.factor-name { font-weight: 600; color: #303133; }
.factor-desc { margin-top: 5px; color: #606266; font-size: 12px; line-height: 1.5; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; }
.source-snapshot { display: flex; flex-wrap: wrap; gap: 6px; color: #666; font-size: 12px; }
.source-snapshot span { padding: 2px 6px; border-radius: 4px; background: #f5f7fa; }
.unit { margin-left: 8px; color: #606266; }
</style>
