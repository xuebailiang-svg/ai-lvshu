<template>
  <div class="map-page" :class="{ 'report-workbench': showResult }">
    <!-- 左侧控制面板 -->
    <div class="control-panel">
      <div class="panel-header">
        <el-icon class="header-icon"><Location /></el-icon>
        <span>新地址评估</span>
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
        <div class="data-gate">
          <div class="data-gate-head">
            <span>报告数据</span>
            <el-button size="small" link @click="loadDataReadiness">刷新</el-button>
          </div>
          <div class="data-gate-item" v-for="item in dataRequirementItems" :key="item.key" :class="{ missing: !item.ready && item.required }">
            <span>{{ item.name }}</span>
            <el-tag size="small" :type="item.ready ? 'success' : item.required ? 'danger' : 'info'">
              {{ item.ready ? '已具备' : item.required ? '必须补充' : '可补充' }}
            </el-tag>
          </div>
          <div class="manual-data-card">
            <span :class="singleManualDataReady ? 'ready-text' : 'missing-text'">
              {{ singleManualDataReady ? '关键调研数据已补充' : '存在待补充调研字段' }}
            </span>
            <el-button size="small" @click="openManualDataDialog">补充调研数据</el-button>
          </div>
          <div class="mock-row" :class="{ enabled: allowMockData }">
            <span>{{ allowMockData ? '已授权客户侧缺失项估算' : '未授权客户侧缺失项估算' }}</span>
            <el-button size="small" :type="allowMockData ? 'warning' : 'primary'" plain @click="allowMockData = !allowMockData">
              {{ allowMockData ? '取消授权' : '估算租金/政策缺失项' }}
            </el-button>
          </div>
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
        <div class="layer-item">
          <el-switch v-model="showHeatmap" size="small" @change="toggleHeatmap" :loading="heatmapLoading" />
          <span class="layer-label">消费热力图</span>
        </div>
        <div v-if="heatmapSource" class="heatmap-source-tag">
          <el-tag size="small" :type="heatmapSource === 'huiyan' ? 'success' : 'info'">
            {{ heatmapSource === 'huiyan' ? '慧眼精准数据' : 'POI 模拟数据' }}
          </el-tag>
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

      <!-- 地图顶部浮层搜索框 -->
      <div class="map-search-bar" v-if="mapLoaded">
        <div class="map-search-inner">
          <el-icon class="map-search-icon"><Search /></el-icon>
          <input
            ref="mapSearchInput"
            v-model="mapSearchKeyword"
            class="map-search-input"
            placeholder="搜索地址定位，再拖拽标记精确选点..."
            autocomplete="off"
            @input="onSearchInput"
            @keyup.enter="doSearch"
            @focus="showSearchDropdown = true"
            @blur="hideDropdownDelay"
          />
          <button v-if="mapSearchKeyword" class="map-search-clear" @click="clearSearch">✕</button>
          <button class="map-search-btn" @click="doSearch">定位</button>
        </div>
        <!-- 搜索下拉候选 -->
        <div class="map-search-dropdown" v-if="showSearchDropdown && searchSuggestions.length > 0">
          <div
            v-for="(item, idx) in searchSuggestions"
            :key="idx"
            class="search-suggestion-item"
            @mousedown.prevent="selectSuggestion(item)"
          >
            <el-icon class="sug-icon"><Location /></el-icon>
            <div class="sug-content">
              <div class="sug-name">{{ item.name }}</div>
              <div class="sug-address">{{ item.district }}{{ item.address }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 拖拽提示 -->
      <transition name="fade">
        <div class="drag-tip" v-if="showDragTip">
          <el-icon><Aim /></el-icon>
          拖动标记精确选点，松手后自动更新地址
        </div>
      </transition>

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
      <div class="result-panel" v-if="showResult" :style="reportWorkbenchStyle">
        <div class="result-header">
          <div class="result-title"><el-icon><DataAnalysis /></el-icon><span>评估报告</span></div>
          <el-button text @click="showResult = false" style="color:#888"><el-icon><Close /></el-icon></el-button>
        </div>
        <div class="result-address">
          <el-icon style="flex-shrink:0;margin-top:2px"><Location /></el-icon>
          <span>{{ evaluationResult?.address || evaluateAddress }}</span>
        </div>
        <div class="workbench-banner" v-if="evaluationResult">
          <div>
            <div class="workbench-title">初版选址评估 + 调研指南</div>
            <div class="workbench-desc">本报告先基于真实高德底表生成筛选方向；可下载调研明细表，补齐竞品、配套、物业和容量参数后重新生成正式报告。</div>
            <div class="workbench-model">使用模型：{{ evaluationResult?.model_version?.name || '当前评分权重' }}</div>
          </div>
          <el-tag size="small" :type="evaluationResult?.data_quality?.has_simulation ? 'warning' : 'success'">
            {{ evaluationResult?.data_quality?.has_simulation ? '含授权估算项' : '真实数据优先' }}
          </el-tag>
        </div>
        <div class="research-flow" v-if="evaluationResult">
          <el-steps :active="researchStepActive" simple finish-status="success">
            <el-step title="初版地图报告" />
            <el-step title="调研数据补充" />
            <el-step title="重新生成报告" />
            <el-step title="反馈沉淀" />
          </el-steps>
          <el-alert
            type="warning"
            title="初版报告用于筛选方向；正式投资决策前，请通过调研工作台或 Excel 调研明细表补齐关键字段后重新生成报告。"
            :closable="false"
            show-icon
          />
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
        <div class="data-quality-section" v-if="evaluationResult?.data_quality?.items?.length">
          <div class="section-label">数据来源</div>
          <div v-for="item in evaluationResult.data_quality.items" :key="item.key" class="quality-item">
            <span>{{ item.name }}</span>
            <el-tag size="small" :type="item.status === 'simulation' || item.status === 'missing' ? 'warning' : 'success'">
              {{ item.status === 'missing' ? '缺失/待调研' : item.status === 'simulation' ? '模拟/估算' : '真实数据' }}
            </el-tag>
          </div>
          <el-alert
            v-for="issue in evaluationResult.data_quality.issues || []"
            :key="issue.issue_type + issue.title"
            type="warning"
            :title="issue.title"
            :description="issue.description"
            show-icon
            :closable="false"
            style="margin-top:8px"
          />
        </div>
        <div class="research-status-section" v-if="evaluationResult?.research_required_fields?.length">
          <div class="section-label-row">
            <span class="section-label">调研数据完整度</span>
            <el-tag size="small" :type="(evaluationResult.research_completion_rate || 0) >= 80 ? 'success' : 'warning'">
              {{ evaluationResult.research_completion_rate || 0 }}%
            </el-tag>
          </div>
          <div class="research-field-grid">
            <div v-for="field in evaluationResult.research_required_fields" :key="field.key" class="research-field" :class="{ missing: !field.ready }">
              <span>{{ field.label }}</span>
              <el-tag size="small" :type="field.ready ? 'success' : 'warning'">{{ field.status }}</el-tag>
            </div>
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
            <div v-if="dim.factor_breakdown?.length" class="factor-breakdown">
              <div v-for="factor in dim.factor_breakdown" :key="`${key}-${factor.sub_factor}`" class="factor-row">
                <div class="factor-main">
                  <span class="factor-name">{{ factor.name || factor.sub_factor }}</span>
                  <span class="factor-meta">权重 {{ factor.weight }}%</span>
                  <span class="factor-score" :class="{ missing: factor.score === null || factor.score === undefined }">
                    {{ factor.score === null || factor.score === undefined ? '待调研' : `${factor.score}分` }}
                  </span>
                </div>
                <div class="factor-basis">{{ factor.basis || factor.description }}</div>
              </div>
            </div>
            <div v-if="dim.evidence_pois?.length" class="poi-evidence">
              <span v-for="poi in dim.evidence_pois.slice(0, 5)" :key="`${poi.name}-${poi.distance}`" class="poi-chip">
                {{ poi.name }}<template v-if="typeof poi.distance === 'number'"> · {{ poi.distance }}m</template>
              </span>
            </div>
          </div>
        </div>
        <div class="education-evidence-section" v-if="educationEvidence">
          <div class="section-label-row">
            <span class="section-label">真实地图证据：教育客群</span>
            <el-tag size="small" type="info">{{ educationEvidence.education_filter_summary || '已清洗 POI' }}</el-tag>
          </div>
          <div class="education-stat-grid">
            <div class="education-stat">
              <span class="stat-value">{{ educationEvidence.education_raw_match_count ?? educationEvidence.university_api_total_count ?? 0 }}</span>
              <span class="stat-name">高德原始匹配</span>
            </div>
            <div class="education-stat">
              <span class="stat-value">{{ educationEvidence.education_effective_count ?? 0 }}</span>
              <span class="stat-name">有效教育客群</span>
            </div>
            <div class="education-stat">
              <span class="stat-value">{{ educationEvidence.higher_education_count ?? educationEvidence.university_count ?? 0 }}</span>
              <span class="stat-name">高校/高职</span>
            </div>
            <div class="education-stat">
              <span class="stat-value">{{ educationEvidence.excluded_education_count ?? 0 }}</span>
              <span class="stat-name">已排除</span>
            </div>
          </div>
          <div v-if="educationEvidence.education_pois?.length" class="poi-list-block">
            <div class="poi-list-title">计入客群分析的学校</div>
            <div v-for="poi in educationEvidence.education_pois.slice(0, 12)" :key="`edu-${poi.name}-${poi.distance}`" class="poi-row">
              <div class="poi-row-main">
                <span class="poi-row-name">{{ poi.name }}</span>
                <el-tag size="small">{{ poi.classification_label || poi.type || '学校' }}</el-tag>
              </div>
              <div class="poi-row-meta">
                <span v-if="typeof poi.distance === 'number'">{{ poi.distance }}m</span>
                <span>{{ poi.classification_reason || poi.address }}</span>
              </div>
            </div>
          </div>
          <el-collapse v-if="educationEvidence.excluded_education_pois?.length" class="excluded-collapse">
            <el-collapse-item :title="`查看已排除的误匹配 POI（${educationEvidence.excluded_education_pois.length}）`" name="excluded">
              <div v-for="poi in educationEvidence.excluded_education_pois.slice(0, 20)" :key="`excluded-${poi.name}-${poi.distance}`" class="poi-row excluded">
                <div class="poi-row-main">
                  <span class="poi-row-name">{{ poi.name }}</span>
                  <el-tag size="small" type="warning">已排除</el-tag>
                </div>
                <div class="poi-row-meta">
                  <span v-if="typeof poi.distance === 'number'">{{ poi.distance }}m</span>
                  <span>{{ poi.classification_reason || '不属于有效教育客群' }}</span>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
        <div class="poi-audit-section" v-if="poiEvidenceGroups.length">
          <div class="section-label-row">
            <span class="section-label">高德 API 底表明细</span>
            <el-tag size="small" type="success">真实查询 + 清洗状态</el-tag>
          </div>
          <el-table v-if="poiAuditSummaryRows.length" :data="poiAuditSummaryRows" size="small" class="poi-audit-table poi-audit-summary-table" max-height="260">
            <el-table-column label="模块" min-width="110">
              <template #default="{ row }">{{ row.label || row.key }}</template>
            </el-table-column>
            <el-table-column label="关键词" min-width="180">
              <template #default="{ row }">{{ row.keywords || '-' }}</template>
            </el-table-column>
            <el-table-column label="原始" width="70" prop="raw_count" />
            <el-table-column label="去重" width="70" prop="deduped_count" />
            <el-table-column label="计入" width="70" prop="included_count" />
            <el-table-column label="待核验" width="80" prop="pending_count" />
            <el-table-column label="排除" width="70" prop="excluded_count" />
            <el-table-column label="截断" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.is_truncated ? 'warning' : 'success'">{{ row.is_truncated ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-for="group in poiEvidenceGroups" :key="group.key" class="poi-audit-block">
            <div class="poi-audit-head">
              <div>
                <div class="poi-audit-title">{{ group.title }}</div>
                <div class="poi-audit-summary">{{ group.summary }}</div>
                <div v-if="group.audit" class="poi-audit-counts">
                  原始 {{ group.audit.raw_count ?? 0 }} 条 / 去重 {{ group.audit.deduped_count ?? 0 }} 条 / 计入 {{ group.audit.included_count ?? group.items.length }} 条 / 待核验 {{ group.audit.pending_count ?? 0 }} 条 / 排除 {{ group.audit.excluded_count ?? group.excluded.length }} 条
                  <span v-if="group.audit.is_truncated">；页面仅展示部分，完整明细见 Excel</span>
                </div>
              </div>
              <el-tag size="small" :type="group.excluded?.length ? 'warning' : 'info'">
                {{ group.items.length }} 条底表
              </el-tag>
            </div>
            <el-table :data="group.items" size="small" class="poi-audit-table" max-height="260" empty-text="高德 API 已查询，未返回可用 POI">
              <el-table-column label="名称" min-width="160">
                <template #default="{ row }">
                  <span class="poi-table-name">{{ row.name || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="类型" min-width="130">
                <template #default="{ row }">
                  <div>{{ row.classification_label || row.type || '-' }}</div>
                  <div v-if="row.typecode" class="poi-typecode">typecode: {{ row.typecode }}</div>
                </template>
              </el-table-column>
              <el-table-column label="距离" width="90">
                <template #default="{ row }">{{ formatPoiDistance(row.distance) }}</template>
              </el-table-column>
              <el-table-column label="地址/依据" min-width="220">
                <template #default="{ row }">{{ row.classification_reason || row.address || '-' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="researchStatusTagTypes[row.status] || 'info'">{{ researchStatusLabels[row.status] || row.status || '未标注' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="120">
                <template #default="{ row }">{{ row.source || row.data_source || '高德API' }}</template>
              </el-table-column>
            </el-table>
            <el-collapse v-if="group.excluded?.length" class="excluded-collapse poi-audit-excluded">
              <el-collapse-item :title="`查看已排除误匹配（${group.excluded.length} 条）`" :name="`${group.key}-excluded`">
                <el-table :data="group.excluded" size="small" class="poi-audit-table" max-height="220" empty-text="暂无排除项">
                  <el-table-column label="名称" min-width="170" prop="name" />
                  <el-table-column label="距离" width="90">
                    <template #default="{ row }">{{ formatPoiDistance(row.distance) }}</template>
                  </el-table-column>
                  <el-table-column label="排除原因" min-width="240">
                    <template #default="{ row }">{{ row.classification_reason || row.type || row.address || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="110">
                    <template #default="{ row }">
                      <el-tag size="small" type="danger">{{ researchStatusLabels[row.status] || '误匹配排除' }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
        <div class="capacity-section" v-if="evaluationResult?.dimensions?.competition?.market_capacity">
          <div class="section-label-row">
            <span class="section-label">商圈容量模型</span>
            <el-tag size="small" :type="evaluationResult.dimensions.competition.market_capacity.can_calculate ? 'success' : 'warning'">
              {{ evaluationResult.dimensions.competition.market_capacity.can_calculate ? '已计算' : '待补充' }}
            </el-tag>
          </div>
          <div v-if="evaluationResult.dimensions.competition.market_capacity.can_calculate" class="capacity-grid">
            <div><span>理论月市场规模</span><strong>{{ formatMoney(evaluationResult.dimensions.competition.market_capacity.monthly_market_size) }}</strong></div>
            <div><span>可容纳门店</span><strong>{{ evaluationResult.dimensions.competition.market_capacity.supportable_store_count }} 家</strong></div>
            <div><span>已识别供给</span><strong>{{ evaluationResult.dimensions.competition.market_capacity.existing_supply_count }} 家</strong></div>
            <div><span>剩余容量</span><strong>{{ evaluationResult.dimensions.competition.market_capacity.remaining_capacity }} 家</strong></div>
          </div>
          <el-alert
            v-else
            type="warning"
            :title="evaluationResult.dimensions.competition.market_capacity.detail"
            show-icon
            :closable="false"
          />
        </div>
        <div class="ai-section" v-if="aiContent || evaluating">
          <div class="section-label-row">
            <span class="section-label">🤖 AI 选址分析报告</span>
            <div class="ai-actions">
              <span v-if="aiContent" class="ai-action-btn" @click="aiReportExpanded = !aiReportExpanded">
                {{ aiReportExpanded ? '收起' : '展开' }}
              </span>
              <span v-if="aiContent" class="ai-action-btn" @click="copyAiReport">复制</span>
            </div>
          </div>
          <div v-if="evaluating && !aiContent" class="ai-generating">
            <span class="ai-cursor">▇</span> AI 报告生成中...
          </div>
          <div
            v-if="aiContent"
            class="ai-text markdown-body"
            :class="{ collapsed: !aiReportExpanded }"
            v-html="renderMarkdown(aiContent)"
          ></div>
          <div v-if="!aiReportExpanded && aiContent.length > 300" class="ai-expand-hint" @click="aiReportExpanded = true">
            点击展开全文 ▼
          </div>
        </div>
        <!-- 相似历史案例推荐 -->
        <div class="report-advisor-section" v-if="evaluationResult" :style="reportAdvisorStyle">
          <div class="advisor-resize-handle" @pointerdown="startReportChatResize" title="上下拖动调整聊天窗口高度">
            <span></span>
          </div>
          <div class="section-label-row">
            <span class="section-label">继续追问 / 解释数据</span>
            <el-button size="small" link @click="resetReportChat">新建追问</el-button>
          </div>
          <div class="advisor-context-card">
            <div class="advisor-context-title">{{ evaluationResult.address || evaluateAddress }}</div>
            <div class="advisor-context-meta">
              <span>综合 {{ evaluationResult.total_score }} 分</span>
              <span>{{ evaluationResult.grade }} 级 · {{ evaluationResult.grade_label }}</span>
              <span>{{ evaluationResult?.data_quality?.has_simulation ? '含授权估算项' : '真实数据优先' }}</span>
            </div>
          </div>
          <div class="advisor-suggestions" v-if="reportSuggestions.length && !reportGenerating">
            <button v-for="q in reportSuggestions" :key="q" type="button" @click="sendReportQuestion(q)">{{ q }}</button>
          </div>
          <div class="advisor-messages" ref="reportChatRef">
            <div v-if="reportMessages.length === 0 && !reportGenerating" class="advisor-empty">
              围绕当前报告继续追问，例如学校明细、排除原因、评分低的维度和改进建议。
            </div>
            <div v-for="(msg, idx) in reportMessages" :key="idx" class="advisor-message" :class="msg.role">
              <div class="advisor-bubble markdown-body" v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
              <div class="advisor-bubble" v-else>{{ msg.content }}</div>
            </div>
            <div v-if="reportGenerating" class="advisor-message assistant">
              <div class="advisor-bubble markdown-body">
                <span v-if="reportStreamingContent" v-html="renderMarkdown(reportStreamingContent)"></span>
                <span v-else>正在基于当前报告分析...</span>
              </div>
            </div>
          </div>
          <div class="advisor-input-row">
            <el-input
              v-model="reportQuestion"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="继续追问当前报告，例如：具体有哪些学校？哪些被排除了？这个评分为什么低？"
              @keydown.enter.exact.prevent="sendReportQuestion()"
            />
            <el-button type="primary" :loading="reportGenerating" :disabled="!reportQuestion.trim()" @click="sendReportQuestion()">发送</el-button>
          </div>
          <div v-if="reportWorkflowSteps.length" class="advisor-workflow">
            <div v-for="(step, idx) in reportWorkflowSteps.slice(-4)" :key="idx" class="advisor-workflow-step">
              <span>[{{ step.step }}]</span>
              <span>{{ step.message }}</span>
            </div>
          </div>
        </div>
        <div class="similar-cases-section" v-if="similarCases.length > 0 || loadingSimilarCases">
          <div class="section-label">📊 相似历史案例</div>
          <div v-if="loadingSimilarCases" class="cases-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 正在检索相似案例...
          </div>
          <div v-for="(c, idx) in similarCases" :key="idx" class="case-card" :class="c.is_success === true ? 'success' : c.is_success === false ? 'failed' : ''">
            <div class="case-header">
              <span class="case-type-tag" v-if="c.type === 'store'">
                <el-tag :type="c.is_success === true ? 'success' : c.is_success === false ? 'danger' : 'info'" size="small">
                  {{ c.is_success === true ? '成功门店' : c.is_success === false ? '已关闭' : '历史门店' }}
                </el-tag>
              </span>
              <span class="case-type-tag" v-else>
                <el-tag type="warning" size="small">历史评估</el-tag>
              </span>
              <span class="case-similarity">相似度 {{ c.similarity }}%</span>
            </div>
            <div class="case-name" v-if="c.name">{{ c.name }}</div>
            <div class="case-address">{{ c.address }}</div>
            <div class="case-meta" v-if="c.type === 'store'">
              <span v-if="c.area_sqm">面积 {{ c.area_sqm }}㎡</span>
              <span v-if="c.machine_count">机器 {{ c.machine_count }}台</span>
              <span v-if="c.total_score">得分 {{ c.total_score }}分</span>
            </div>
            <div class="case-meta" v-else>
              <span v-if="c.total_score">得分 {{ c.total_score }}分</span>
              <span v-if="c.grade_label">{{ c.grade_label }}</span>
            </div>
            <div class="case-notes" v-if="c.experience_notes || c.summary">
              {{ (c.experience_notes || c.summary || '').slice(0, 80) }}{{ (c.experience_notes || c.summary || '').length > 80 ? '...' : '' }}
            </div>
          </div>
          <div v-if="!loadingSimilarCases && similarCases.length === 0" class="cases-empty">
            暂无相似历史案例，上传历史门店数据后将自动积累案例库
          </div>
        </div>

        <div class="result-actions" v-if="evaluationResult">
          <el-button size="small" type="success" @click="openManualDataDialog">补充调研数据</el-button>
          <el-button size="small" type="success" plain @click="downloadResearchTemplate">下载调研明细表</el-button>
          <el-button size="small" type="primary" plain :loading="researchImportLoading" @click="triggerResearchUpload">上传补充表</el-button>
          <el-button size="small" @click="saveResearchDraft">保存为调研草稿</el-button>
          <el-button size="small" type="primary" plain @click="regenerateReport">重新生成报告</el-button>
          <el-button size="small" type="primary" @click="exportReport">导出报告</el-button>
          <el-button size="small" type="warning" @click="markCurrentEvaluationAbnormal">标记不合理</el-button>
          <el-button size="small" @click="router.push('/feedback-quality')">提交反馈</el-button>
          <el-button size="small" @click="clearMapOverlays">清除重置</el-button>
          <input ref="researchFileInput" type="file" accept=".xlsx" style="display:none" @change="uploadResearchTemplate" />
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

    <el-dialog v-model="researchImportPreviewVisible" title="调研明细表上传预览" width="760px">
      <el-alert
        v-if="researchImportPreview?.errors?.length"
        type="warning"
        title="表格存在错误，原调研草稿尚未被覆盖。请修正后重新上传。"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else
        type="success"
        title="解析通过。确认后只保存为调研草稿，不会自动重新生成报告。"
        :closable="false"
        show-icon
      />
      <div class="research-import-preview" v-if="researchImportPreview">
        <div class="preview-grid">
          <div v-for="(value, key) in researchImportPreview.summary" :key="key" class="preview-stat">
            <span>{{ researchSummaryLabel(String(key)) }}</span>
            <strong>{{ value }}</strong>
          </div>
        </div>
        <el-table v-if="researchImportPreview.errors?.length" :data="researchImportPreview.errors" size="small" border max-height="260">
          <el-table-column label="Sheet" prop="sheet" width="140" />
          <el-table-column label="行号" prop="row" width="90" />
          <el-table-column label="问题" prop="message" />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="researchImportPreviewVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="Boolean(researchImportPreview?.errors?.length)"
          :loading="researchImportConfirming"
          @click="confirmResearchImport"
        >确认保存为草稿</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="manualDataDialogVisible" title="调研工作台：补充真实经营与周边数据" size="92%" class="research-drawer">
      <div class="research-drawer-body">
        <el-alert
          type="info"
          title="先用高德 API 生成底表，再由人工调研或外部采集补齐字段。未补齐的数据会在报告中标记为缺失，不会由 AI 编造。"
          :closable="false"
          show-icon
        />
        <div class="research-toolbar">
          <el-tag type="success">当前地址：{{ evaluationResult?.address || evaluateAddress || '未生成报告' }}</el-tag>
          <el-tag :type="researchCompletionLocal >= 80 ? 'success' : 'warning'">完整度 {{ researchCompletionLocal }}%</el-tag>
          <el-button size="small" @click="seedResearchRowsFromEvaluation">从高德明细重新带入底表</el-button>
        </div>
        <div class="research-import">
          <el-select v-model="researchImportTarget" style="width:180px">
            <el-option label="导入到竞品" value="competitors" />
            <el-option label="导入到餐饮" value="food_places" />
            <el-option label="导入到夜市摊" value="night_markets" />
            <el-option label="导入到娱乐配套" value="entertainment_places" />
            <el-option label="导入到便利店" value="convenience_stores" />
          </el-select>
          <el-input
            v-model="researchImportText"
            type="textarea"
            :rows="2"
            placeholder="可粘贴外部采集结果，每行一条，逗号或 Tab 分隔。竞品格式：名称,距离,配置,小时价,上座率；配套格式：名称,类型,距离,营业时间"
          />
          <el-button type="primary" plain @click="importResearchRows">粘贴导入</el-button>
        </div>

        <el-tabs v-model="researchTab" class="research-tabs">
          <el-tab-pane label="竞品调研" name="competitors">
            <div class="research-section-head">
              <span>竞品档案补充</span>
              <el-button size="small" type="primary" @click="addResearchRow('competitors')">新增竞品</el-button>
            </div>
            <el-table :data="editingManualData.competitors" size="small" border class="research-table" max-height="520">
              <el-table-column label="状态" width="120">
                <template #default="{ row }">
                  <el-select v-model="row.status" @change="syncResearchInclude(row)">
                    <el-option v-for="item in researchStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="竞品名" min-width="180"><template #default="{ row }"><el-input v-model="row.name" placeholder="竞品名称" /></template></el-table-column>
              <el-table-column label="距离(m)" width="110"><template #default="{ row }"><el-input-number v-model="row.distance" :min="0" :step="50" /></template></el-table-column>
              <el-table-column label="配置" min-width="150"><template #default="{ row }"><el-input v-model="row.configuration" placeholder="显卡/显示器/配置" /></template></el-table-column>
              <el-table-column label="机器数(台)" width="120"><template #default="{ row }"><el-input-number v-model="row.machine_count" :min="0" /></template></el-table-column>
              <el-table-column label="面积(㎡)" width="110"><template #default="{ row }"><el-input-number v-model="row.area_sqm" :min="0" /></template></el-table-column>
              <el-table-column label="小时价(元)" width="120"><template #default="{ row }"><el-input-number v-model="row.hourly_price" :min="0" /></template></el-table-column>
              <el-table-column label="套餐价" min-width="140"><template #default="{ row }"><el-input v-model="row.package_price" placeholder="包夜/会员价" /></template></el-table-column>
              <el-table-column label="上座率(%)" width="120"><template #default="{ row }"><el-input-number v-model="row.occupancy_rate" :min="0" :max="100" /></template></el-table-column>
              <el-table-column label="开业年限" width="120"><template #default="{ row }"><el-input-number v-model="row.open_years" :min="0" :step="0.5" /></template></el-table-column>
              <el-table-column label="月售" width="110"><template #default="{ row }"><el-input-number v-model="row.monthly_sales" :min="0" /></template></el-table-column>
              <el-table-column label="年售" width="110"><template #default="{ row }"><el-input-number v-model="row.annual_sales" :min="0" /></template></el-table-column>
              <el-table-column label="充值信息" min-width="150"><template #default="{ row }"><el-input v-model="row.recharge_info" /></template></el-table-column>
              <el-table-column label="来源" width="140"><template #default="{ row }"><el-select v-model="row.source"><el-option label="高德API" value="高德API" /><el-option label="人工调研" value="人工调研" /><el-option label="爬虫/外部采集" value="爬虫/外部采集" /><el-option label="估算" value="估算" /></el-select></template></el-table-column>
              <el-table-column label="置信度" width="120"><template #default="{ row }"><el-input-number v-model="row.confidence" :min="0" :max="1" :step="0.1" /></template></el-table-column>
              <el-table-column label="备注" min-width="160"><template #default="{ row }"><el-input v-model="row.notes" /></template></el-table-column>
              <el-table-column label="操作" width="80" fixed="right"><template #default="{ $index }"><el-button link type="danger" @click="removeResearchRow('competitors', $index)">删除</el-button></template></el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="周边配套" name="facility">
            <div class="research-two-col">
              <div v-for="section in facilityResearchSections" :key="section.key" class="facility-edit-card">
                <div class="research-section-head">
                  <span>{{ section.title }}</span>
                  <el-button size="small" type="primary" @click="addResearchRow(section.key)">新增</el-button>
                </div>
                <el-table :data="editingManualData[section.key]" size="small" border class="research-table" max-height="340">
                  <el-table-column label="状态" width="120">
                    <template #default="{ row }">
                      <el-select v-model="row.status" @change="syncResearchInclude(row)">
                        <el-option v-for="item in researchStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column :label="section.nameLabel" min-width="150"><template #default="{ row }"><el-input v-model="row.name" /></template></el-table-column>
                  <el-table-column label="类型" width="130"><template #default="{ row }"><el-input v-model="row.type" /></template></el-table-column>
                  <el-table-column label="距离(m)" width="110"><template #default="{ row }"><el-input-number v-model="row.distance" :min="0" :step="50" /></template></el-table-column>
                  <el-table-column v-if="section.key === 'night_markets'" label="摊位数量" width="120"><template #default="{ row }"><el-input-number v-model="row.stall_count" :min="0" /></template></el-table-column>
                  <el-table-column label="营业时间" min-width="150"><template #default="{ row }"><el-input v-model="row.business_hours" placeholder="如 18:00-02:00" /></template></el-table-column>
                  <el-table-column v-if="section.key === 'food_places'" label="营业到凌晨" width="110"><template #default="{ row }"><el-switch v-model="row.late_night" /></template></el-table-column>
                  <el-table-column v-if="section.key === 'convenience_stores'" label="24小时" width="90"><template #default="{ row }"><el-switch v-model="row.is_24h" /></template></el-table-column>
                  <el-table-column label="开业年限" width="110"><template #default="{ row }"><el-input-number v-model="row.open_years" :min="0" :step="0.5" /></template></el-table-column>
                  <el-table-column label="规模" width="120"><template #default="{ row }"><el-input v-model="row.scale" /></template></el-table-column>
                  <el-table-column label="来源" width="140"><template #default="{ row }"><el-select v-model="row.source"><el-option label="高德API" value="高德API" /><el-option label="人工调研" value="人工调研" /><el-option label="爬虫/外部采集" value="爬虫/外部采集" /><el-option label="估算" value="估算" /></el-select></template></el-table-column>
                  <el-table-column label="备注" min-width="150"><template #default="{ row }"><el-input v-model="row.notes" /></template></el-table-column>
                  <el-table-column label="操作" width="80" fixed="right"><template #default="{ $index }"><el-button link type="danger" @click="removeResearchRow(section.key, $index)">删除</el-button></template></el-table-column>
                </el-table>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="物业与容量" name="property">
            <el-form label-width="170px">
              <div class="manual-form-section">
                <h4>物业与成本</h4>
                <div class="manual-form-grid">
                  <el-form-item label="月租金（元/月）"><el-input-number v-model="editingManualData.property_conditions.monthly_rent" :min="0" :step="1000" style="width:100%" /></el-form-item>
                  <el-form-item label="面积（㎡）"><el-input-number v-model="editingManualData.property_conditions.area_sqm" :min="0" :step="10" style="width:100%" /></el-form-item>
                  <el-form-item label="楼层（层）"><el-input-number v-model="editingManualData.property_conditions.floor" :min="-3" :step="1" style="width:100%" /></el-form-item>
                  <el-form-item label="门头可见性">
                    <el-select v-model="editingManualData.property_conditions.frontage_visibility" clearable placeholder="请选择" style="width:100%">
                      <el-option label="高：主街明显可见" value="high" />
                      <el-option label="中：需要导视" value="medium" />
                      <el-option label="低：隐蔽/楼上深处" value="low" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="停车便利"><el-switch v-model="editingManualData.property_conditions.parking_convenience" /></el-form-item>
                  <el-form-item label="消防满足"><el-switch v-model="editingManualData.property_conditions.fire_safety_ready" /></el-form-item>
                  <el-form-item label="电力容量满足"><el-switch v-model="editingManualData.property_conditions.power_capacity_ready" /></el-form-item>
                  <el-form-item label="空调/排烟满足"><el-switch v-model="editingManualData.property_conditions.hvac_ready" /></el-form-item>
                  <el-form-item label="物业限制" class="wide"><el-input v-model="editingManualData.property_conditions.property_restriction" type="textarea" :rows="2" /></el-form-item>
                </div>
              </div>
              <div class="manual-form-section">
                <h4>商圈容量参数</h4>
                <div class="manual-form-grid">
                  <el-form-item label="18-35岁有效人口"><el-input-number v-model="editingManualData.market_capacity_inputs.effective_population_18_35" :min="0" :step="100" style="width:100%" /></el-form-item>
                  <el-form-item label="流动人口（人/月）"><el-input-number v-model="editingManualData.market_capacity_inputs.floating_population" :min="0" :step="100" style="width:100%" /></el-form-item>
                  <el-form-item label="转化率（%）"><el-input-number v-model="editingManualData.market_capacity_inputs.conversion_rate_pct" :min="0" :max="100" :step="0.5" style="width:100%" /></el-form-item>
                  <el-form-item label="月均消费频次"><el-input-number v-model="editingManualData.market_capacity_inputs.monthly_frequency" :min="0" :step="0.5" style="width:100%" /></el-form-item>
                  <el-form-item label="客单价（元）"><el-input-number v-model="editingManualData.market_capacity_inputs.avg_spend" :min="0" :step="5" style="width:100%" /></el-form-item>
                  <el-form-item label="健康月营收（元/月）"><el-input-number v-model="editingManualData.market_capacity_inputs.healthy_monthly_revenue" :min="0" :step="5000" style="width:100%" /></el-form-item>
                </div>
              </div>
              <div class="manual-form-section">
                <h4>政策与其他</h4>
                <div class="manual-form-grid">
                  <el-form-item label="预计日客流（人/日）"><el-input-number v-model="editingManualData.expected_daily_visitors" :min="0" :step="10" style="width:100%" /></el-form-item>
                  <el-form-item label="政策风险等级">
                    <el-select v-model="editingManualData.policy_risk" placeholder="请选择" style="width:100%">
                      <el-option label="低风险：证照、消防、经营时间基本明确" value="low" />
                      <el-option label="中等风险：存在待确认事项" value="medium" />
                      <el-option label="高风险：证照、消防或经营限制明显" value="high" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="政策说明（文字）" class="wide">
                    <el-input v-model="editingManualData.policy_notes" type="textarea" :rows="3" placeholder="消防验收、证照、未成年人管控、物业限制等" />
                  </el-form-item>
                </div>
              </div>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="manualDataDialogVisible = false">取消</el-button>
        <el-button @click="saveManualData">仅保存到当前评估</el-button>
        <el-button type="primary" @click="saveManualDataAndDraft">保存为调研草稿</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'MapView' })
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Location, Search, DataAnalysis, Aim, ScaleToOriginal, Delete, Close, MapLocation, ArrowUp, ArrowDown, Loading } from '@element-plus/icons-vue'
import api from '@/api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

const router = useRouter()
const mapContainer = ref<HTMLDivElement>()
const radarCanvas = ref<HTMLCanvasElement>()
const workflowBodyRef = ref<HTMLElement>()
const reportChatRef = ref<HTMLElement>()
const mapSearchInput = ref<HTMLInputElement>()
const researchFileInput = ref<HTMLInputElement>()

// 地图搜索定位相关状态
const mapSearchKeyword = ref('')
const searchSuggestions = ref<any[]>([])
const showSearchDropdown = ref(false)
const showDragTip = ref(false)
let autoCompleteInstance: any = null
let dragTipTimer: any = null

const evaluateAddress = ref('')
const evaluateRadius = ref(1500)
const evaluating = ref(false)
const showResult = ref(false)
const showChainStores = ref(true)
const mapTool = ref('click')
const workflowExpanded = ref(true)
const similarCases = ref<any[]>([])
const loadingSimilarCases = ref(false)
const mapLoaded = ref(false)
const evaluationResult = ref<any>(null)
const aiContent = ref('')
const aiReportExpanded = ref(false)
const workflowSteps = ref<any[]>([])
const storeStats = ref({ total: 0, success: 0, failed: 0 })
const showHeatmap = ref(false)
const heatmapLoading = ref(false)
const heatmapSource = ref('')
const dataReadiness = ref<any>(null)
const allowMockData = ref(false)
const manualData = ref<any>({})
const manualDataDialogVisible = ref(false)
const editingManualData = ref<any>({})
const reportQuestion = ref('')
const reportGenerating = ref(false)
const reportStreamingContent = ref('')
const reportMessages = ref<any[]>([])
const reportWorkflowSteps = ref<any[]>([])
const reportSessionId = ref<string | null>(null)
const reportSuggestions = ref<string[]>(['列出周边学校', '解释被排除 POI', '按客群价值分析'])
const reportAdvisorHeight = ref(320)
const researchTab = ref('competitors')
const researchImportTarget = ref('competitors')
const researchImportText = ref('')
const researchImportLoading = ref(false)
const researchImportConfirming = ref(false)
const researchImportPreviewVisible = ref(false)
const researchImportPreview = ref<any>(null)
let reportResizeStartY = 0
let reportResizeStartHeight = 0

let mapInstance: any = null
let chainStoreMarkers: any[] = []
let evaluateMarker: any = null
let drawingManager: any = null
let currentOverlay: any = null
let heatmapLayer: any = null

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

const reportAdvisorStyle = computed(() => ({
  '--advisor-height': `${reportAdvisorHeight.value}px`,
  '--advisor-message-height': `${Math.max(120, reportAdvisorHeight.value - 178)}px`
}))

const reportWorkbenchStyle = computed(() => ({
  '--advisor-total-space': `${reportAdvisorHeight.value + 126}px`
}))

const facilityResearchSections = [
  { key: 'food_places', title: '餐饮', nameLabel: '店铺名' },
  { key: 'night_markets', title: '夜市摊', nameLabel: '名称/位置' },
  { key: 'entertainment_places', title: '娱乐配套', nameLabel: '名称' },
  { key: 'convenience_stores', title: '便利店', nameLabel: '名称' }
]

const researchStatusOptions = [
  { label: '计入', value: 'included' },
  { label: '待核验', value: 'pending_review' },
  { label: '误匹配', value: 'excluded' },
  { label: '人工新增', value: 'manual_added' }
]

const researchStatusLabels: Record<string, string> = {
  included: '计入',
  pending_review: '待核验',
  excluded: '误匹配排除',
  manual_added: '人工补充'
}

const researchStatusTagTypes: Record<string, string> = {
  included: 'success',
  pending_review: 'warning',
  excluded: 'danger',
  manual_added: 'primary'
}

const singleManualDataReady = computed(() => Boolean(
  (manualData.value.property_conditions?.monthly_rent || manualData.value.monthly_rent)
  && (manualData.value.property_conditions?.area_sqm || manualData.value.area_sqm)
  && manualData.value.policy_risk
))

const researchStepActive = computed(() => {
  if (!evaluationResult.value) return 0
  if ((evaluationResult.value.research_completion_rate || 0) >= 80) return 2
  if (Object.keys(manualData.value || {}).length > 0) return 1
  return 0
})

const researchCompletionLocal = computed(() => calculateResearchCompletion(editingManualData.value))

const dataRequirementItems = computed(() => {
  const base = dataReadiness.value?.items || []
  return base.map((item: any) => {
    if (item.key === 'rent_policy') return { ...item, ready: singleManualDataReady.value }
    return item
  }).filter((item: any) => item.required || ['basic', 'revenue', 'member', 'hardware', 'competitor_profiles'].includes(item.key))
})

const missingRequiredItems = computed(() => dataRequirementItems.value.filter((item: any) => item.required && !item.ready))

const educationEvidence = computed(() => {
  const population = evaluationResult.value?.dimensions?.population
  if (!population) return null
  const hasEvidence = population.education_pois?.length
    || population.university_pois?.length
    || population.excluded_education_pois?.length
    || typeof population.education_effective_count === 'number'
  if (!hasEvidence) return null
  return {
    ...population,
    education_pois: population.education_pois || population.university_pois || [],
    excluded_education_pois: population.excluded_education_pois || [],
  }
})

function formatPoiDistance(distance: any): string {
  if (typeof distance === 'number') return `${distance}m`
  if (typeof distance === 'string' && distance) return distance.endsWith('m') ? distance : `${distance}m`
  return '-'
}

function formatMoney(value: any): string {
  const num = Number(value || 0)
  if (!Number.isFinite(num)) return '-'
  return `${Math.round(num).toLocaleString()} 元`
}

const poiAuditSummaryRows = computed(() => {
  const direct = evaluationResult.value?.poi_audit_summary
  const nested = evaluationResult.value?.data_quality?.poi_audit_summary
  return Array.isArray(direct) ? direct : (Array.isArray(nested) ? nested : [])
})

function buildPoiGroup(key: string, title: string, summary: string, items: any[] = [], excluded: any[] = []) {
  const audit = poiAuditSummaryRows.value.find((row: any) => row.key === key)
  return {
    key,
    title,
    summary,
    items: (items || []).filter(Boolean),
    excluded: (excluded || []).filter(Boolean),
    audit
  }
}

function flattenBaseTable(table: any = {}, keys = ['amap', 'pending', 'manual']) {
  const rows: any[] = []
  keys.forEach((key) => {
    const part = table?.[key]
    if (Array.isArray(part)) rows.push(...part)
  })
  return rows.filter(Boolean)
}

function normalizeEvidenceRows(rows: any[] = [], fallbackStatus = 'included') {
  return rows.filter(Boolean).map((row: any) => ({
    ...row,
    status: row.status || fallbackStatus,
    source: ['amap', 'api'].includes(row.source || row.data_source)
      ? '高德API'
      : (row.source || row.data_source || (fallbackStatus === 'manual_added' ? '人工调研' : '高德API'))
  }))
}

const poiEvidenceGroups = computed(() => {
  const dimensions = evaluationResult.value?.dimensions || {}
  const traffic = dimensions.traffic || {}
  const competition = dimensions.competition || {}
  const facility = dimensions.facility || {}
  const population = dimensions.population || {}
  const policy = dimensions.policy || {}
  const confirmedTables = evaluationResult.value?.confirmed_poi_tables || {}
  const excludedTables = evaluationResult.value?.excluded_poi_tables || {}
  const groups: any[] = []

  const competitorTable = confirmedTables.competitors || {}
  groups.push(buildPoiGroup(
    'competitors',
    '竞品底表',
    competition.competitor_filter_summary || competition.detail || '高德 API 已查询竞品关键词，并按有效竞品、待核验、误匹配排除分类',
    normalizeEvidenceRows(flattenBaseTable(competitorTable)),
    normalizeEvidenceRows(excludedTables.competitors || competition.excluded_competitor_pois || [], 'excluded')
  ))

  const tableConfigs = [
    ['traffic_stations', '交通站点底表', traffic.detail || '高德返回的公交、地铁、轻轨站点明细'],
    ['commercial_places', '商业设施底表', '高德 API 商业设施底表，用于核验商场、商业广场等客流载体'],
    ['food_places', '餐饮底表', '高德 API 餐饮底表，可补充营业时间、是否营业到凌晨、开业年限'],
    ['entertainment_places', '娱乐配套底表', '高德 API 娱乐配套底表，可核验 KTV、酒吧、台球、密室、影院等'],
    ['convenience_stores', '便利店底表', '高德 API 便利店底表，可补充是否 24 小时营业'],
    ['parking_places', '停车场底表', '高德 API 停车场底表，用于判断停车便利性'],
    ['education', '教育/客群底表', `高德 API 学校底表，核心范围 ${population.education_core_radius_m || evaluateRadius.value}m，扩展观察范围 ${population.education_search_radius_m || 3000}m`],
    ['policy_redline', '政策红线 200m 明细', policy.policy_redline_summary || '小学、幼儿园、中学、政府机构距离需要大于 200m'],
    ['residential_office', '住宅办公底表', '高德 API 住宅、公寓、写字楼、办公园区底表']
  ]
  tableConfigs.forEach(([key, title, summary]) => {
    const table = confirmedTables[key] || {}
    const tableKeys = key === 'education' ? ['core', 'extended', 'amap', 'pending', 'manual'] : ['amap', 'pending', 'manual']
    const rows = normalizeEvidenceRows(flattenBaseTable(table, tableKeys))
    const fallbackRows = key === 'traffic_stations'
      ? normalizeEvidenceRows(traffic.transit_pois || [])
      : key === 'commercial_places'
        ? normalizeEvidenceRows(traffic.commercial_pois || [])
        : key === 'entertainment_places'
          ? normalizeEvidenceRows(facility.entertainment_pois || [])
          : key === 'residential_office'
            ? normalizeEvidenceRows([...(population.residential_pois || []), ...(population.office_pois || [])])
            : []
    const excludedRows = normalizeEvidenceRows(excludedTables[key] || [], 'excluded')
    groups.push(buildPoiGroup(key, title, summary, rows.length ? rows : fallbackRows, excludedRows))
  })

  return groups
})
function buildReportSuggestions(result: any) {
  if (!result) return ['这个地址最大风险是什么？', '怎么补充调研数据？', '报告里哪些数据待核验？']
  const suggestions: string[] = []
  const confirmed = result.confirmed_poi_tables || {}
  const excluded = result.excluded_poi_tables || {}
  const missing = result.research_required_fields?.missing || []
  const competitorTable = confirmed.competitors || {}
  const pendingCompetitors = flattenBaseTable(competitorTable, ['pending'])
  const competitors = flattenBaseTable(competitorTable, ['amap', 'manual'])
  const educationRows = flattenBaseTable(confirmed.education || {}, ['amap'])
  const excludedRows = [
    ...(excluded.competitors || []),
    ...(excluded.education || []),
    ...(excluded.food_places || []),
    ...(excluded.convenience_stores || [])
  ]

  if (missing.length) suggestions.push('还缺哪些关键调研数据？')
  if (pendingCompetitors.length) suggestions.push('列出需要人工核验的竞品')
  if (excludedRows.length) suggestions.push('为什么这些 POI 被排除？')
  if (competitors.length) suggestions.push('哪些竞品压力最大？')
  if (educationRows.length) suggestions.push('哪些学校被计入客群？')
  suggestions.push('这个地址最大风险是什么？')
  return Array.from(new Set(suggestions)).slice(0, 3)
}

async function loadDataReadiness() {
  try {
    dataReadiness.value = await api.get('/evaluate/data-readiness')
  } catch {
    dataReadiness.value = null
  }
}

function openManualDataDialog() {
  editingManualData.value = ensureResearchDraftShape(manualData.value)
  seedResearchRowsFromEvaluation(false)
  manualDataDialogVisible.value = true
}

function parseManualCompetitors(text: string) {
  return String(text || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map((line, idx) => {
      const parts = line.split(',').map(part => part.trim())
      const distanceText = parts[1] || ''
      const price = Number(parts[3])
      const occupancy = Number(String(parts[4] || '').replace('%', ''))
      return {
        id: `manual-line-${idx + 1}`,
        name: parts[0],
        distance: Number(distanceText.replace(/[^\d.]/g, '')) || undefined,
        configuration: parts[2] || undefined,
        hourly_price: Number.isFinite(price) ? price : undefined,
        occupancy_rate: Number.isFinite(occupancy) ? occupancy : undefined,
        data_source: 'manual',
      }
    })
    .filter(item => item.name)
}

function ensureResearchDraftShape(data: any = {}) {
  const property = data.property_conditions || {}
  const capacity = data.market_capacity_inputs || {}
  return {
    ...data,
    competitors: Array.isArray(data.competitors) ? data.competitors.map(normalizeResearchRow) : parseManualCompetitors(data.competitor_text || ''),
    food_places: Array.isArray(data.food_places) ? data.food_places.map(normalizeResearchRow) : [],
    night_markets: Array.isArray(data.night_markets) ? data.night_markets.map(normalizeResearchRow) : [],
    entertainment_places: Array.isArray(data.entertainment_places) ? data.entertainment_places.map(normalizeResearchRow) : [],
    convenience_stores: Array.isArray(data.convenience_stores) ? data.convenience_stores.map(normalizeResearchRow) : [],
    property_conditions: {
      monthly_rent: property.monthly_rent ?? data.monthly_rent,
      area_sqm: property.area_sqm ?? data.area_sqm,
      floor: property.floor ?? data.floor,
      frontage_visibility: property.frontage_visibility ?? data.frontage_visibility,
      parking_convenience: property.parking_convenience ?? data.parking_convenience,
      fire_safety_ready: property.fire_safety_ready ?? data.fire_safety_ready,
      power_capacity_ready: property.power_capacity_ready ?? data.power_capacity_ready,
      hvac_ready: property.hvac_ready ?? data.hvac_ready,
      property_restriction: property.property_restriction ?? data.property_restriction,
    },
    market_capacity_inputs: {
      effective_population_18_35: capacity.effective_population_18_35 ?? data.effective_population_18_35,
      floating_population: capacity.floating_population ?? data.floating_population,
      conversion_rate_pct: capacity.conversion_rate_pct ?? data.conversion_rate_pct,
      monthly_frequency: capacity.monthly_frequency ?? data.monthly_frequency,
      avg_spend: capacity.avg_spend ?? data.avg_spend,
      healthy_monthly_revenue: capacity.healthy_monthly_revenue ?? data.healthy_monthly_revenue,
    }
  }
}

function normalizeResearchRow(row: any = {}) {
  const rawSource = row.source || row.data_source
  const displaySource = ['amap', 'api'].includes(rawSource) ? '高德API' : (rawSource || '人工调研')
  const status = row.status || (row.include === false ? 'excluded' : (displaySource === '高德API' ? 'pending_review' : 'manual_added'))
  return {
    ...row,
    include: ['excluded', 'pending_review'].includes(status) ? false : (row.include ?? true),
    status,
    source: displaySource,
    confidence: row.confidence ?? 0.8
  }
}

function syncResearchInclude(row: any) {
  row.include = !['excluded', 'pending_review'].includes(row.status)
  if (row.status === 'manual_added' && (!row.source || row.source === '高德API')) {
    row.source = '人工调研'
  }
}

function makeResearchRow(section: string, row: any = {}) {
  const base = normalizeResearchRow({
    name: '',
    type: '',
    distance: undefined,
    business_hours: '',
    source: '人工调研',
    status: 'manual_added',
    notes: '',
    ...row
  })
  if (section === 'competitors') return { ...base, configuration: '', machine_count: undefined, area_sqm: undefined, hourly_price: undefined, package_price: '', occupancy_rate: undefined, open_years: undefined, monthly_sales: undefined, annual_sales: undefined, recharge_info: '' }
  if (section === 'night_markets') return { ...base, stall_count: undefined, scale: '' }
  if (section === 'food_places') return { ...base, late_night: false, open_years: undefined }
  if (section === 'convenience_stores') return { ...base, is_24h: false, open_years: undefined }
  return { ...base, open_years: undefined }
}

function addResearchRow(section: string) {
  if (!Array.isArray(editingManualData.value[section])) editingManualData.value[section] = []
  editingManualData.value[section].push(makeResearchRow(section))
}

function removeResearchRow(section: string, index: number) {
  editingManualData.value[section]?.splice(index, 1)
}

function importResearchRows() {
  const text = researchImportText.value.trim()
  if (!text) {
    ElMessage.warning('请先粘贴要导入的数据')
    return
  }
  const target = researchImportTarget.value
  const rows = text.split('\n').map(line => line.trim()).filter(Boolean).map((line, index) => {
    const parts = line.split(/\t|,/).map(part => part.trim())
    if (target === 'competitors') {
      return makeResearchRow(target, {
        name: parts[0],
        distance: Number(String(parts[1] || '').replace(/[^\d.]/g, '')) || undefined,
        configuration: parts[2],
        hourly_price: Number(parts[3]) || undefined,
        occupancy_rate: Number(String(parts[4] || '').replace('%', '')) || undefined,
        source: '爬虫/外部采集',
        status: 'manual_added',
        notes: parts.slice(5).join('；')
      })
    }
    return makeResearchRow(target, {
      name: parts[0],
      type: parts[1],
      distance: Number(String(parts[2] || '').replace(/[^\d.]/g, '')) || undefined,
      business_hours: parts[3],
      source: '爬虫/外部采集',
      status: 'manual_added',
      notes: parts.slice(4).join('；'),
      is_24h: target === 'convenience_stores' && /24/.test(parts[3] || ''),
      late_night: target === 'food_places' && /(凌晨|02|03|04|24)/.test(parts[3] || ''),
      stall_count: target === 'night_markets' ? Number(parts[1]) || undefined : undefined,
      id: `import-${Date.now()}-${index}`
    })
  }).filter(row => row.name)
  if (!Array.isArray(editingManualData.value[target])) editingManualData.value[target] = []
  editingManualData.value[target].push(...rows)
  researchImportText.value = ''
  researchTab.value = target === 'competitors' ? 'competitors' : 'facility'
  ElMessage.success(`已导入 ${rows.length} 条调研数据`)
}

function mergeUniqueRows(section: string, rows: any[]) {
  if (!Array.isArray(editingManualData.value[section])) editingManualData.value[section] = []
  const existing = new Set(editingManualData.value[section].map((row: any) => `${row.name || ''}-${row.distance || ''}`))
  rows.forEach(row => {
    const key = `${row.name || ''}-${row.distance || ''}`
    if (row.name && !existing.has(key)) {
      editingManualData.value[section].push(makeResearchRow(section, row))
      existing.add(key)
    }
  })
}

function seedResearchRowsFromEvaluation(showMessage = true) {
  if (!evaluationResult.value) return
  const confirmed = evaluationResult.value.confirmed_poi_tables || {}
  const excluded = evaluationResult.value.excluded_poi_tables || {}
  const dims = evaluationResult.value.dimensions || {}
  const competition = dims.competition || {}
  const facility = dims.facility || {}
  const competitorTable = confirmed.competitors || {}
  mergeUniqueRows('competitors', [
    ...normalizeEvidenceRows(flattenBaseTable(competitorTable, ['amap', 'manual']), 'included'),
    ...normalizeEvidenceRows(flattenBaseTable(competitorTable, ['pending']), 'pending_review'),
    ...normalizeEvidenceRows(excluded.competitors || [], 'excluded'),
    ...normalizeEvidenceRows(competition.local_competitor_profiles || [], 'manual_added')
  ].map((poi: any) => ({
    name: poi.name,
    distance: poi.distance,
    type: poi.classification_label || poi.type,
    status: poi.status,
    include: !['excluded', 'pending_review'].includes(poi.status),
    source: poi.source || (poi.data_source === 'competitor_profile' ? '人工调研' : '高德API'),
    notes: poi.classification_reason || poi.address
  })))
  const foodRows = normalizeEvidenceRows(flattenBaseTable(confirmed.food_places || {}, ['amap', 'manual']), 'included')
  const convenienceRows = normalizeEvidenceRows(flattenBaseTable(confirmed.convenience_stores || {}, ['amap', 'manual']), 'included')
  mergeUniqueRows('food_places', (foodRows.length ? foodRows : (facility.food_pois || [])).map((poi: any) => ({ name: poi.name, type: poi.type || '餐饮', distance: poi.distance, status: poi.status || 'included', source: poi.source || '高德API', notes: poi.classification_reason || poi.address })))
  mergeUniqueRows('convenience_stores', (convenienceRows.length ? convenienceRows : (facility.convenience_pois || [])).map((poi: any) => ({ name: poi.name, type: poi.type || '便利店', distance: poi.distance, status: poi.status || 'included', source: poi.source || '高德API', notes: poi.classification_reason || poi.address })))
  if (showMessage) ElMessage.success('已从当前评估的高德明细带入待核验底表')
}

function finalizeManualData(data: any) {
  const shaped = ensureResearchDraftShape(data)
  const property = shaped.property_conditions || {}
  const capacity = shaped.market_capacity_inputs || {}
  return {
    ...shaped,
    monthly_rent: property.monthly_rent,
    area_sqm: property.area_sqm,
    floor: property.floor,
    frontage_visibility: property.frontage_visibility,
    parking_convenience: property.parking_convenience,
    fire_safety_ready: property.fire_safety_ready,
    power_capacity_ready: property.power_capacity_ready,
    hvac_ready: property.hvac_ready,
    property_restriction: property.property_restriction,
    effective_population_18_35: capacity.effective_population_18_35,
    floating_population: capacity.floating_population,
    conversion_rate_pct: capacity.conversion_rate_pct,
    monthly_frequency: capacity.monthly_frequency,
    avg_spend: capacity.avg_spend,
    healthy_monthly_revenue: capacity.healthy_monthly_revenue,
    late_night_food_count: shaped.food_places.filter((row: any) => row.include !== false && row.status !== 'pending_review' && row.late_night).length,
    entertainment_count: shaped.entertainment_places.filter((row: any) => row.include !== false && row.status !== 'pending_review').length,
    convenience_24h_count: shaped.convenience_stores.filter((row: any) => row.include !== false && row.status !== 'pending_review' && row.is_24h).length,
    night_market_level: shaped.night_markets.some((row: any) => row.include !== false && row.status !== 'pending_review') ? 'medium' : undefined
  }
}

function calculateResearchCompletion(data: any) {
  const shaped = ensureResearchDraftShape(data || {})
  const checks = [
    shaped.property_conditions.monthly_rent,
    shaped.property_conditions.area_sqm,
    shaped.property_conditions.floor,
    shaped.property_conditions.frontage_visibility,
    shaped.property_conditions.fire_safety_ready,
    shaped.policy_risk,
    shaped.market_capacity_inputs.effective_population_18_35,
    shaped.market_capacity_inputs.conversion_rate_pct,
    shaped.market_capacity_inputs.monthly_frequency,
    shaped.market_capacity_inputs.avg_spend,
    shaped.market_capacity_inputs.healthy_monthly_revenue,
    shaped.competitors?.some((row: any) => row.include !== false && row.status !== 'pending_review' && row.name),
    shaped.food_places?.some((row: any) => row.include !== false && row.status !== 'pending_review' && row.name) || shaped.night_markets?.some((row: any) => row.include !== false && row.status !== 'pending_review' && row.name),
  ]
  const ready = checks.filter(value => Boolean(value) || value === false).length
  return Math.round((ready / checks.length) * 100)
}

function saveManualData() {
  const payload = finalizeManualData(editingManualData.value)
  manualData.value = payload
  manualDataDialogVisible.value = false
  ElMessage.success('调研数据已保存到当前评估上下文')
}

async function saveResearchDraft() {
  manualData.value = finalizeManualData(manualData.value)
  const evaluationId = evaluationResult.value?.evaluation_id
  if (!evaluationId) {
    ElMessage.warning('当前评估记录尚未落库，已先保存到本次页面上下文')
    return
  }
  try {
    const res: any = await api.put(`/evaluate/${evaluationId}/research`, { manual_data: manualData.value })
    evaluationResult.value = { ...evaluationResult.value, ...res }
    ElMessage.success('调研草稿已保存')
  } catch (e: any) {
    ElMessage.error('调研草稿保存失败：' + (e.message || '未知错误'))
  }
}

function researchSummaryLabel(key: string) {
  const labels: Record<string, string> = {
    competitors: '竞品',
    food_places: '餐饮',
    night_markets: '夜市摊',
    entertainment_places: '娱乐配套',
    convenience_stores: '便利店',
    parking_places: '停车场',
    education_places: '教育客群',
    policy_redline_review: '政策红线',
    property_fields: '物业字段',
    capacity_fields: '容量字段'
  }
  return labels[key] || key
}

function getResearchEvaluationId() {
  const evaluationId = evaluationResult.value?.evaluation_id
  if (!evaluationId) {
    ElMessage.warning('当前评估记录尚未落库，请先完成一次新地址评估')
    return null
  }
  return evaluationId
}

async function downloadResearchTemplate() {
  const evaluationId = getResearchEvaluationId()
  if (!evaluationId) return
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/v1/evaluate/${evaluationId}/research-template`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const disposition = response.headers.get('content-disposition') || ''
    const match = disposition.match(/filename\*=UTF-8''([^;]+)/)
    const filename = match ? decodeURIComponent(match[1]) : `选址调研明细_${Date.now()}.xlsx`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('调研明细表已下载')
  } catch (e: any) {
    ElMessage.error('调研明细表下载失败：' + (e.message || '未知错误'))
  }
}

function triggerResearchUpload() {
  if (!getResearchEvaluationId()) return
  researchFileInput.value?.click()
}

async function uploadResearchTemplate(event: Event) {
  const evaluationId = getResearchEvaluationId()
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!evaluationId || !file) return
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    ElMessage.warning('请上传 .xlsx 格式的调研明细表')
    return
  }
  researchImportLoading.value = true
  try {
    const token = localStorage.getItem('token')
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`/api/v1/evaluate/${evaluationId}/research-import`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`)
    researchImportPreview.value = data
    researchImportPreviewVisible.value = true
    if (data.errors?.length) {
      ElMessage.warning(`调研明细表解析完成，但有 ${data.errors.length} 个问题需要处理`)
    } else {
      ElMessage.success('调研明细表解析通过，请确认保存为草稿')
    }
  } catch (e: any) {
    ElMessage.error('调研明细表上传失败：' + (e.message || '未知错误'))
  } finally {
    researchImportLoading.value = false
  }
}

async function confirmResearchImport() {
  const evaluationId = getResearchEvaluationId()
  const preview = researchImportPreview.value
  if (!evaluationId || !preview?.manual_data) return
  if (preview.errors?.length) {
    ElMessage.warning('当前表格仍有错误，请修正后重新上传')
    return
  }
  researchImportConfirming.value = true
  try {
    const res: any = await api.post(`/evaluate/${evaluationId}/research-import/confirm`, {
      manual_data: preview.manual_data
    })
    manualData.value = res.manual_data || preview.manual_data
    editingManualData.value = ensureResearchDraftShape(manualData.value)
    evaluationResult.value = { ...evaluationResult.value, ...res }
    researchImportPreviewVisible.value = false
    researchImportPreview.value = null
    ElMessage.success('调研明细表已保存为草稿，可点击“重新生成报告”')
  } catch (e: any) {
    ElMessage.error('确认导入失败：' + (e.message || '未知错误'))
  } finally {
    researchImportConfirming.value = false
  }
}

async function saveManualDataAndDraft() {
  const payload = finalizeManualData(editingManualData.value)
  manualData.value = payload
  manualDataDialogVisible.value = false
  await saveResearchDraft()
}

async function regenerateReport() {
  manualData.value = finalizeManualData(manualData.value)
  await startEvaluation()
}

function getScoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 65) return '#409eff'
  if (score >= 50) return '#e6a23c'
  return '#f56c6c'
}

async function initMap() {
  try {
    const mapKeys: any = await api.get('/system/config/map-keys')
    const jsKey: string = mapKeys?.js_key || ''
    const secCode: string = mapKeys?.security_code || ''
    if (!jsKey) return
    if (secCode) {
      (window as any)._AMapSecurityConfig = { securityJsCode: secCode }
    }
    await new Promise<void>((resolve, reject) => {
      if ((window as any).AMap) { resolve(); return }
      const script = document.createElement('script')
      // ★ 初始化时预加载 HeatMap 插件，避免切换热力图时动态加载失败
      script.src = 'https://webapi.amap.com/maps?v=2.0&key=' + jsKey + '&plugin=AMap.Scale,AMap.ToolBar,AMap.MouseTool,AMap.Geocoder,AMap.HeatMap'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('高德地图脚本加载失败'))
      document.head.appendChild(script)
    })
    const AMap = (window as any).AMap
    mapInstance = new AMap.Map('amap-container', {
      zoom: 13, center: [108.9398, 34.3416], mapStyle: 'amap://styles/dark', resizeEnable: true
    })
    AMap.plugin(['AMap.ToolBar', 'AMap.Scale', 'AMap.MouseTool', 'AMap.AutoComplete', 'AMap.PlaceSearch'], () => {
      mapInstance.addControl(new AMap.ToolBar({ position: 'RB' }))
      mapInstance.addControl(new AMap.Scale())
      drawingManager = new AMap.MouseTool(mapInstance)
      // 初始化 AutoComplete，用于搜索建议
      autoCompleteInstance = new AMap.AutoComplete({ city: '全国' })
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
    const res: any = await api.get('/evaluate/stores')
    const stores = res?.stores || res?.data?.stores || []
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
  resetReportChat()
  showResult.value = false; evaluateAddress.value = ''
  mapSearchKeyword.value = ''; searchSuggestions.value = []
}

// ===== 地图搜索定位相关函数 =====

function onSearchInput() {
  const kw = mapSearchKeyword.value.trim()
  if (!kw || !autoCompleteInstance) { searchSuggestions.value = []; return }
  autoCompleteInstance.search(kw, (status: string, result: any) => {
    if (status === 'complete' && result.tips) {
      searchSuggestions.value = result.tips.filter((t: any) => t.location)
    } else {
      searchSuggestions.value = []
    }
  })
}

function doSearch() {
  const kw = mapSearchKeyword.value.trim()
  if (!kw) return
  if (!autoCompleteInstance) { ElMessage.warning('搜索插件未加载'); return }
  autoCompleteInstance.search(kw, (status: string, result: any) => {
    if (status === 'complete' && result.tips && result.tips.length > 0) {
      const first = result.tips.find((t: any) => t.location) || result.tips[0]
      if (first) selectSuggestion(first)
    } else {
      ElMessage.warning('未找到相关地址，请尝试更详细的地址描述')
    }
  })
}

function selectSuggestion(item: any) {
  showSearchDropdown.value = false
  searchSuggestions.value = []
  if (!mapInstance) return

  let lng: number, lat: number
  if (item.location) {
    lng = item.location.getLng ? item.location.getLng() : item.location.lng
    lat = item.location.getLat ? item.location.getLat() : item.location.lat
  } else {
    ElMessage.warning('该地址无坐标信息')
    return
  }

  // 地图飞行定位到该地址，zoom 17 层级方便拖拽精确选点
  mapInstance.setZoomAndCenter(17, [lng, lat], false, 600)

  // 放置可拖拽标记
  handleMapClick(lng, lat, true)

  // 更新搜索框显示内容
  mapSearchKeyword.value = item.name || item.address || ''
  evaluateAddress.value = item.name || item.address || ''

  ElMessage.success(`已定位到「${item.name || '目标地址'}」，可拖动标记精确选点`)
}

function clearSearch() {
  mapSearchKeyword.value = ''
  searchSuggestions.value = []
  showSearchDropdown.value = false
}

function hideDropdownDelay() {
  setTimeout(() => { showSearchDropdown.value = false }, 200)
}

function toggleChainStores(val: boolean) {
  if (val) loadChainStores()
  else { chainStoreMarkers.forEach(m => mapInstance?.remove(m)); chainStoreMarkers = [] }
}

async function toggleHeatmap(val: boolean) {
  if (!mapInstance) { ElMessage.warning('地图未加载'); showHeatmap.value = false; return }
  const AMap = (window as any).AMap
  if (!AMap) { ElMessage.warning('高德地图未加载'); showHeatmap.value = false; return }

  // 关闭热力图
  if (!val) {
    if (heatmapLayer) { heatmapLayer.hide(); heatmapLayer = null }
    heatmapSource.value = ''
    return
  }

  // 开启热力图
  await loadDataReadiness()
  if (!dataReadiness.value?.has_huiyan_key && !allowMockData.value) {
    ElMessage.warning('消费热力图缺少高德慧眼真实数据。请配置慧眼 Key，或明确点击“使用模拟数据”。')
    showHeatmap.value = false
    return
  }
  heatmapLoading.value = true
  try {
    // 获取当前地图中心点
    const center = mapInstance.getCenter()
    const lng = center.getLng ? center.getLng() : center.lng
    const lat = center.getLat ? center.getLat() : center.lat

    const res: any = await api.post('/evaluate/heatmap', {
      longitude: lng, latitude: lat, radius: 3000, allow_mock_data: allowMockData.value
    })
    heatmapSource.value = res.source || 'poi_simulation'

    if (!res.points || res.points.length === 0) {
      ElMessage.info(res.message || '当前区域无热力数据')
      showHeatmap.value = false
      return
    }

    // ★ 确保 HeatMap 插件已加载（初始化时已预加载，这里再确保一次）
    if (!AMap.HeatMap) {
      await new Promise<void>((resolve) => {
        AMap.plugin('AMap.HeatMap', () => resolve())
      })
    }

    // 销毁旧热力图实例
    if (heatmapLayer) {
      try { heatmapLayer.hide() } catch {}
      heatmapLayer = null
    }

    heatmapLayer = new AMap.HeatMap(mapInstance, {
      radius: 25,
      opacity: [0, 0.8],
      gradient: {
        0.4: 'rgba(0,0,255,0.6)',
        0.65: 'rgba(0,255,0,0.7)',
        0.85: 'rgba(255,165,0,0.8)',
        1.0: 'rgba(255,0,0,0.9)'
      },
      '3d': false
    })

    const dataSet = res.points.map((p: any) => ({ lng: p.lng, lat: p.lat, count: p.weight }))
    heatmapLayer.setDataSet({ data: dataSet, max: 100 })
    heatmapLayer.show()

    const sourceLabel = res.source === 'huiyan' ? '慧眼精准消费数据' : 'POI 模拟数据'
    const tipSuffix = res.source !== 'huiyan' ? '（配置真实高德 Key 可获得精准消费数据）' : ''
    ElMessage.success(`消费热力图已加载（${sourceLabel}，${res.total} 个数据点${tipSuffix}）`)
  } catch (e: any) {
    console.error('热力图加载失败', e)
    ElMessage.error('热力图加载失败：' + (e.message || '未知错误'))
    showHeatmap.value = false
  } finally {
    heatmapLoading.value = false
  }
}

async function handleMapClick(lng: number, lat: number, isDraggable = false) {
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
    animation: 'AMAP_ANIMATION_DROP',
    draggable: true,   // 标记始终可拖拽
    cursor: 'move',
    title: '拖动我来精确选点'
  })
  mapInstance.add(evaluateMarker)

  // 拖拽开始：显示拖拽提示
  evaluateMarker.on('dragstart', () => {
    showDragTip.value = true
    if (dragTipTimer) clearTimeout(dragTipTimer)
  })

  // 拖拽结束：逆地理编码更新地址
  evaluateMarker.on('dragend', (e: any) => {
    const newLng = e.lnglat.getLng ? e.lnglat.getLng() : e.lnglat.lng
    const newLat = e.lnglat.getLat ? e.lnglat.getLat() : e.lnglat.lat
    reverseGeocode(newLng, newLat)
    dragTipTimer = setTimeout(() => { showDragTip.value = false }, 2000)
  })

  // 逆地理编码获取地址
  reverseGeocode(lng, lat)

  // 搜索定位后显示拖拽提示
  if (isDraggable) {
    showDragTip.value = true
    dragTipTimer = setTimeout(() => { showDragTip.value = false }, 3500)
  }
}

function reverseGeocode(lng: number, lat: number) {
  const AMap = (window as any).AMap
  if (!AMap) return
  AMap.plugin('AMap.Geocoder', () => {
    const geocoder = new AMap.Geocoder()
    geocoder.getAddress([lng, lat], (status: string, result: any) => {
      if (status === 'complete' && result.regeocode) {
        evaluateAddress.value = result.regeocode.formattedAddress
        mapSearchKeyword.value = result.regeocode.formattedAddress
      }
    })
  })
}

async function startEvaluation() {
  if (!evaluateAddress.value.trim()) { ElMessage.warning('请输入评估地址或在地图上点击选址'); return }
  await loadDataReadiness()
  if (!dataReadiness.value?.has_amap_key) {
    ElMessage.warning('正式选址报告必须使用真实高德地图 API。请先到系统配置填写并测试高德 API Key。')
    return
  }
  if (missingRequiredItems.value.length > 0 && !allowMockData.value) {
    ElMessage.warning(`仍有 ${missingRequiredItems.value.length} 项调研数据缺失，将生成初版报告并标注待补充字段。`)
  }
  evaluating.value = true; showResult.value = true; workflowSteps.value = []
  evaluationResult.value = null; aiContent.value = ''
  resetReportChat()
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/evaluate/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({
        address: evaluateAddress.value,
        radius: evaluateRadius.value,
        allow_mock_data: allowMockData.value,
        manual_data: manualData.value
      })
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
              // 将评估结果写入 sessionStorage，供单点评估对话页读取上下文
              sessionStorage.setItem('lastEvaluationResult', JSON.stringify(step))
              reportSuggestions.value = buildReportSuggestions(step)
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
  } finally {
    evaluating.value = false
    // 评估完成后自动检索相似历史案例
    if (evaluationResult.value) {
      fetchSimilarCases()
    }
  }
}

async function fetchSimilarCases() {
  if (!evaluationResult.value) return
  loadingSimilarCases.value = true
  similarCases.value = []
  try {
    const res: any = await api.post('/evaluate/similar-cases', {
      address: evaluationResult.value.address || evaluateAddress.value,
      total_score: evaluationResult.value.total_score,
      top_k: 3
    })
    similarCases.value = res.cases || res.data?.cases || []
  } catch (e) {
    // 相似案例检索失败不影响主流程
    console.warn('相似案例检索失败', e)
  } finally {
    loadingSimilarCases.value = false
  }
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

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    const raw = marked.parse(text) as string
    return DOMPurify.sanitize(raw)
  } catch {
    return text.replace(/\n/g, '<br>')
  }
}

async function copyAiReport() {
  if (!aiContent.value) return
  try {
    await navigator.clipboard.writeText(aiContent.value)
    ElMessage.success('已复制 AI 报告内容')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function resetReportChat() {
  reportQuestion.value = ''
  reportGenerating.value = false
  reportStreamingContent.value = ''
  reportMessages.value = []
  reportWorkflowSteps.value = []
  reportSessionId.value = null
  reportSuggestions.value = buildReportSuggestions(evaluationResult.value)
}

function clampReportAdvisorHeight(height: number): number {
  const maxHeight = Math.max(280, Math.min(680, window.innerHeight - 190))
  return Math.max(260, Math.min(maxHeight, height))
}

function handleReportChatResize(event: PointerEvent) {
  const delta = reportResizeStartY - event.clientY
  reportAdvisorHeight.value = clampReportAdvisorHeight(reportResizeStartHeight + delta)
}

function stopReportChatResize() {
  window.removeEventListener('pointermove', handleReportChatResize)
  window.removeEventListener('pointerup', stopReportChatResize)
  window.removeEventListener('pointercancel', stopReportChatResize)
}

function startReportChatResize(event: PointerEvent) {
  event.preventDefault()
  reportResizeStartY = event.clientY
  reportResizeStartHeight = reportAdvisorHeight.value
  window.addEventListener('pointermove', handleReportChatResize)
  window.addEventListener('pointerup', stopReportChatResize)
  window.addEventListener('pointercancel', stopReportChatResize)
}

function scrollReportChatToBottom() {
  nextTick(() => {
    if (reportChatRef.value) reportChatRef.value.scrollTop = reportChatRef.value.scrollHeight
  })
}

async function sendReportQuestion(question?: string) {
  const text = (question || reportQuestion.value).trim()
  if (!text || reportGenerating.value) return
  if (!evaluationResult.value) {
    ElMessage.warning('请先完成新地址评估，再围绕正式报告追问')
    return
  }

  reportQuestion.value = ''
  reportGenerating.value = true
  reportStreamingContent.value = ''
  reportWorkflowSteps.value = []
  reportMessages.value.push({ role: 'user', content: text, created_at: new Date().toISOString() })
  scrollReportChatToBottom()

  try {
    if (!reportSessionId.value) {
      const created: any = await api.post('/chat/sessions')
      reportSessionId.value = created?.session_id || created?.data?.session_id || null
    }
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        session_id: reportSessionId.value,
        message: text,
        address: evaluationResult.value.address || evaluateAddress.value,
        evaluation_context: evaluationResult.value,
      })
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let assistantContent = ''
    let pendingSuggestions: string[] = []

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        try {
          const event = JSON.parse(raw)
          if (event.type === 'log') {
            reportWorkflowSteps.value.push(event)
          } else if (event.type === 'token') {
            assistantContent += event.content
            reportStreamingContent.value = assistantContent
            scrollReportChatToBottom()
          } else if (event.type === 'suggestions') {
            pendingSuggestions = event.questions || []
          } else if (event.type === 'done') {
            reportMessages.value.push({
              role: 'assistant',
              content: assistantContent,
              created_at: new Date().toISOString(),
            })
            reportSuggestions.value = pendingSuggestions.length
              ? pendingSuggestions
              : buildReportSuggestions(evaluationResult.value)
            reportStreamingContent.value = ''
            reportGenerating.value = false
            scrollReportChatToBottom()
          }
        } catch {}
      }
    }
  } catch (e: any) {
    reportGenerating.value = false
    reportStreamingContent.value = ''
    ElMessage.error('追问失败：' + (e.message || '未知错误'))
  }
}

async function markCurrentEvaluationAbnormal() {
  if (!evaluationResult.value?.evaluation_id) {
    ElMessage.warning('当前评估尚未保存，暂不能标记')
    return
  }
  await api.post('/data-quality/issues', {
    evaluation_id: evaluationResult.value.evaluation_id,
    source_type: 'evaluation_result',
    source_id: evaluationResult.value.evaluation_id,
    issue_type: 'user_marked_abnormal',
    severity: 'warning',
    title: '用户标记评估数据不合理',
    description: `${evaluationResult.value.address || evaluateAddress.value} 的评估结果需要人工核验`,
    payload: evaluationResult.value.data_quality || {}
  })
  ElMessage.success('已记录数据质量问题，可在“评估反馈 / 数据质量”中处理')
}

async function exportReport() {
  if (!evaluationResult.value) return
  ElMessage.info('正在生成 HTML 报告...')
  try {
    const token = localStorage.getItem('token')
    const response = await fetch('/api/v1/evaluate/export-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({
        evaluation_result: evaluationResult.value,
        ai_report: aiContent.value,
        similar_cases: similarCases.value,
        format: 'html'
      })
    })
    if (!response.ok) throw new Error('HTTP ' + response.status)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const contentDisposition = response.headers.get('Content-Disposition') || ''
    const filenameMatch = contentDisposition.match(/filename\*=UTF-8''(.+)/)
    const filename = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `选址评估报告_${new Date().toLocaleDateString()}.html`
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('HTML 报告已下载')
  } catch (e: any) {
    ElMessage.error('报告导出失败：' + (e.message || '未知错误'))
  }
}

onMounted(async () => { await nextTick(); await loadDataReadiness(); await initMap() })
onUnmounted(() => {
  stopReportChatResize()
  mapInstance?.destroy()
})
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
.data-gate { margin-top: 12px; padding: 10px; border: 1px solid rgba(108,99,255,0.18); border-radius: 8px; background: rgba(255,255,255,0.035); }
.data-gate-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 12px; color: rgba(255,255,255,0.76); font-weight: 600; }
.data-gate-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 0; border-top: 1px solid rgba(255,255,255,0.04); font-size: 11px; color: rgba(255,255,255,0.6); }
.data-gate-item.missing { color: #fca5a5; }
.manual-data-card { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 12px; }
.ready-text { color: #67c23a; }
.missing-text { color: #f56c6c; }
.mock-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; padding: 8px; border: 1px dashed rgba(255,255,255,0.16); border-radius: 6px; font-size: 12px; color: rgba(255,255,255,0.62); }
.mock-row.enabled { border-color: rgba(230,162,60,0.55); background: rgba(230,162,60,0.08); color: #f3c77b; }
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
.result-panel { width: min(620px, 46vw); min-width: 520px; height: 100%; background: #13132a; border-left: 1px solid rgba(108,99,255,0.15); overflow-y: auto; z-index: 10; }
.map-page.report-workbench { display: block; height: calc(100vh - 60px); overflow: hidden; background: #0d0d1a; }
.map-page.report-workbench .control-panel,
.map-page.report-workbench .map-container { display: none; }
.map-page.report-workbench .result-panel {
  width: 100%;
  min-width: 0;
  height: 100%;
  border-left: none;
  overflow-y: auto;
  padding-bottom: var(--advisor-total-space, 446px);
  background: #10101f;
}
.map-page.report-workbench .result-header {
  position: sticky;
  top: 0;
  z-index: 16;
}
.map-page.report-workbench .score-overview,
.map-page.report-workbench .data-quality-section,
.map-page.report-workbench .research-flow,
.map-page.report-workbench .research-status-section,
.map-page.report-workbench .radar-section,
.map-page.report-workbench .dimension-scores,
.map-page.report-workbench .education-evidence-section,
.map-page.report-workbench .poi-audit-section,
.map-page.report-workbench .capacity-section,
.map-page.report-workbench .ai-section,
.map-page.report-workbench .similar-cases-section {
  max-width: 1120px;
  margin-left: auto;
  margin-right: auto;
}
.map-page.report-workbench .workbench-banner,
.map-page.report-workbench .result-address {
  max-width: 1120px;
  margin-left: auto;
  margin-right: auto;
  border-left: 1px solid rgba(255,255,255,0.04);
  border-right: 1px solid rgba(255,255,255,0.04);
}
.workbench-banner { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.06); background: rgba(64,158,255,0.08); }
.workbench-title { color: #e0e0ff; font-size: 15px; font-weight: 700; margin-bottom: 4px; }
.workbench-desc { color: rgba(255,255,255,0.58); font-size: 12px; line-height: 1.5; }
.workbench-model { color: rgba(160,212,255,0.86); font-size: 12px; margin-top: 6px; }
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
.data-quality-section, .research-status-section, .research-flow { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.quality-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 0; font-size: 12px; color: rgba(255,255,255,0.62); border-top: 1px solid rgba(255,255,255,0.04); }
.research-flow { display: flex; flex-direction: column; gap: 10px; }
.research-flow :deep(.el-steps--simple) { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
.research-field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.research-field { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border: 1px solid rgba(103,194,58,0.16); border-radius: 8px; background: rgba(103,194,58,0.06); color: rgba(255,255,255,0.68); font-size: 12px; }
.research-field.missing { border-color: rgba(230,162,60,0.22); background: rgba(230,162,60,0.08); }
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
.factor-breakdown { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.factor-row { padding: 8px; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; background: rgba(255,255,255,0.03); }
.factor-main { display: grid; grid-template-columns: minmax(0,1fr) auto auto; align-items: center; gap: 8px; }
.factor-name { color: rgba(255,255,255,0.82); font-size: 12px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.factor-meta { color: rgba(255,255,255,0.46); font-size: 11px; }
.factor-score { color: #67c23a; font-size: 11px; font-weight: 700; }
.factor-score.missing { color: #e6a23c; }
.factor-basis { margin-top: 4px; color: rgba(255,255,255,0.42); font-size: 11px; line-height: 1.45; }
.poi-evidence { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.poi-chip {
  max-width: 100%;
  padding: 3px 6px;
  border: 1px solid rgba(64, 158, 255, 0.24);
  border-radius: 6px;
  color: rgba(210, 230, 255, 0.78);
  background: rgba(64, 158, 255, 0.08);
  font-size: 10px;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-section { padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.section-label-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-label-row .section-label { margin-bottom: 0; }
.ai-actions { display: flex; gap: 6px; }
.ai-action-btn { font-size: 11px; color: rgba(108,99,255,0.7); cursor: pointer; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(108,99,255,0.2); transition: all 0.2s; }
.ai-action-btn:hover { background: rgba(108,99,255,0.15); color: #a0a0ff; }
.ai-generating { font-size: 12px; color: rgba(108,99,255,0.8); padding: 8px; animation: blink-cursor 1s infinite; }
.ai-cursor { animation: blink-cursor 0.8s infinite; }
@keyframes blink-cursor { 0%,100% { opacity:1; } 50% { opacity:0; } }
.ai-text { font-size: 12px; color: rgba(255,255,255,0.75); line-height: 1.7; background: rgba(108,99,255,0.06); border-left: 3px solid #6c63ff; padding: 12px; border-radius: 0 8px 8px 0; }
.ai-text.collapsed { max-height: 200px; overflow: hidden; position: relative; }
.ai-text.collapsed::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 60px; background: linear-gradient(transparent, rgba(19,19,42,0.95)); }
.ai-expand-hint { text-align: center; font-size: 11px; color: rgba(108,99,255,0.7); cursor: pointer; padding: 6px; margin-top: 4px; }
.ai-expand-hint:hover { color: #a0a0ff; }
.education-evidence-section, .report-advisor-section, .poi-audit-section, .capacity-section { padding: 16px; border-bottom: 1px solid rgba(255,255,255,0.06); }
.capacity-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.capacity-grid div { padding: 12px; border: 1px solid rgba(64,158,255,0.16); border-radius: 8px; background: rgba(64,158,255,0.06); }
.capacity-grid span { display: block; color: rgba(255,255,255,0.45); font-size: 11px; margin-bottom: 6px; }
.capacity-grid strong { color: #e0e0ff; font-size: 16px; }
.manual-form-section { padding: 14px 0 4px; border-top: 1px solid #edf0f5; }
.manual-form-section:first-child { border-top: none; padding-top: 0; }
.manual-form-section h4 { margin: 0 0 12px; color: #1f2d3d; font-size: 14px; }
.manual-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
.manual-form-grid :deep(.wide) { grid-column: 1 / -1; }
.research-drawer :deep(.el-drawer__body) { background: #f6f8fc; padding: 0; }
.research-drawer :deep(.el-drawer__footer) { border-top: 1px solid #e6ebf2; padding: 12px 18px; }
.research-drawer-body { padding: 18px; }
.research-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 14px 0; }
.research-import { display: grid; grid-template-columns: 180px minmax(0, 1fr) 110px; gap: 10px; align-items: stretch; margin-bottom: 14px; }
.research-tabs { background: #fff; border: 1px solid #e4e9f3; border-radius: 10px; padding: 14px; box-shadow: 0 10px 28px rgba(20,30,55,0.06); }
.research-section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; color: #1f2d3d; font-size: 14px; font-weight: 700; }
.research-table { width: 100%; }
.research-table :deep(.el-input), .research-table :deep(.el-select), .research-table :deep(.el-input-number) { width: 100%; }
.research-two-col { display: grid; grid-template-columns: 1fr; gap: 18px; }
.facility-edit-card { border: 1px solid #e6ebf2; border-radius: 8px; padding: 12px; background: #fbfcff; overflow-x: auto; }
.facility-edit-card .research-table { min-width: 1160px; }
.education-stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
.education-stat { padding: 10px 8px; border: 1px solid rgba(64,158,255,0.16); border-radius: 8px; background: rgba(64,158,255,0.06); }
.education-stat .stat-value { display: block; color: #e0e0ff; font-size: 18px; font-weight: 800; line-height: 1.1; }
.education-stat .stat-name { display: block; color: rgba(255,255,255,0.45); font-size: 11px; margin-top: 5px; }
.poi-list-block { margin-top: 10px; }
.poi-list-title { color: rgba(255,255,255,0.68); font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.poi-row { padding: 8px 0; border-top: 1px solid rgba(255,255,255,0.06); }
.poi-row-main { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.poi-row-name { color: rgba(255,255,255,0.82); font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.poi-row-meta { display: flex; gap: 8px; margin-top: 4px; color: rgba(255,255,255,0.42); font-size: 11px; line-height: 1.4; }
.poi-row.excluded .poi-row-name { color: rgba(255,255,255,0.58); }
.excluded-collapse { margin-top: 8px; --el-collapse-header-bg-color: transparent; --el-collapse-content-bg-color: transparent; --el-collapse-border-color: rgba(255,255,255,0.08); --el-collapse-header-text-color: rgba(255,255,255,0.62); }
.poi-audit-block { margin-top: 14px; border: 1px solid rgba(64,158,255,0.14); border-radius: 8px; overflow: hidden; background: rgba(255,255,255,0.025); }
.poi-audit-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); background: rgba(64,158,255,0.06); }
.poi-audit-title { color: rgba(235,245,255,0.9); font-size: 13px; font-weight: 700; margin-bottom: 4px; }
.poi-audit-summary { color: rgba(255,255,255,0.46); font-size: 11px; line-height: 1.5; }
.poi-audit-counts { color: rgba(255,255,255,0.58); font-size: 11px; line-height: 1.5; margin-top: 4px; }
.poi-audit-summary-table { margin-bottom: 14px; border-radius: 8px; overflow: hidden; }
.poi-audit-table { --el-table-bg-color: rgba(0,0,0,0.08); --el-table-tr-bg-color: rgba(0,0,0,0.08); --el-table-header-bg-color: rgba(64,158,255,0.1); --el-table-border-color: rgba(255,255,255,0.06); --el-table-text-color: rgba(255,255,255,0.68); --el-table-header-text-color: rgba(210,230,255,0.86); }
.poi-table-name { color: rgba(255,255,255,0.86); font-weight: 600; }
.poi-typecode { margin-top: 2px; color: rgba(255,255,255,0.38); font-size: 11px; line-height: 1.25; }
.poi-audit-excluded { padding: 0 12px 10px; }
.advisor-context-card { padding: 12px; border: 1px solid rgba(108,99,255,0.24); border-radius: 8px; background: rgba(108,99,255,0.08); margin-bottom: 10px; }
.advisor-context-title { color: #e0e0ff; font-size: 13px; font-weight: 700; line-height: 1.4; }
.advisor-context-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; color: rgba(255,255,255,0.48); font-size: 11px; }
.advisor-suggestions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.advisor-suggestions button { border: 1px solid rgba(64,158,255,0.28); background: rgba(64,158,255,0.08); color: rgba(210,230,255,0.88); border-radius: 999px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
.advisor-suggestions button:hover { background: rgba(64,158,255,0.16); }
.advisor-messages { max-height: 360px; overflow-y: auto; padding: 8px; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; background: rgba(0,0,0,0.12); }
.advisor-empty { color: rgba(255,255,255,0.38); font-size: 12px; text-align: center; padding: 16px 8px; line-height: 1.5; }
.advisor-message { display: flex; margin: 8px 0; }
.advisor-message.user { justify-content: flex-end; }
.advisor-message.assistant { justify-content: flex-start; }
.advisor-bubble { max-width: 88%; padding: 10px 12px; border-radius: 10px; font-size: 12px; line-height: 1.7; color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.06); box-shadow: 0 4px 14px rgba(0,0,0,0.12); }
.advisor-message.user .advisor-bubble { background: rgba(64,158,255,0.24); color: #eef6ff; border-bottom-right-radius: 3px; }
.advisor-message.assistant .advisor-bubble { border-bottom-left-radius: 3px; }
.advisor-input-row { display: flex; gap: 8px; align-items: flex-end; margin-top: 10px; }
.advisor-input-row .el-button { min-height: 34px; }
.advisor-workflow { margin-top: 8px; padding: 8px; border-radius: 6px; background: rgba(255,255,255,0.035); }
.advisor-workflow-step { display: flex; gap: 6px; color: rgba(255,255,255,0.44); font-size: 11px; line-height: 1.5; }
.map-page.report-workbench .report-advisor-section {
  position: fixed;
  left: 252px;
  right: 32px;
  bottom: 70px;
  z-index: 30;
  max-width: none;
  height: var(--advisor-height, 320px);
  padding: 14px;
  padding-top: 18px;
  border: 1px solid rgba(108,99,255,0.24);
  border-radius: 10px;
  background: rgba(18,18,38,0.96);
  box-shadow: 0 18px 48px rgba(0,0,0,0.36);
  backdrop-filter: blur(10px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.advisor-resize-handle {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: ns-resize;
  touch-action: none;
}
.advisor-resize-handle span {
  width: 54px;
  height: 4px;
  border-radius: 999px;
  background: rgba(180,200,255,0.38);
}
.advisor-resize-handle:hover span {
  background: rgba(180,200,255,0.68);
}
.map-page.report-workbench .advisor-context-card {
  display: none;
}
.map-page.report-workbench .advisor-suggestions {
  margin-bottom: 8px;
}
.map-page.report-workbench .advisor-messages {
  flex: 1;
  max-height: none;
  min-height: 0;
  height: var(--advisor-message-height, 142px);
  background: rgba(0,0,0,0.18);
  scroll-behavior: smooth;
}
.map-page.report-workbench .advisor-input-row {
  margin-top: 8px;
  flex-shrink: 0;
}
.map-page.report-workbench .advisor-workflow {
  display: none;
}
/* Markdown 样式 */
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { color: #c0b8ff; margin: 8px 0 4px; font-weight: 600; }
.markdown-body :deep(h2) { font-size: 13px; border-bottom: 1px solid rgba(108,99,255,0.2); padding-bottom: 3px; }
.markdown-body :deep(h3) { font-size: 12px; }
.markdown-body :deep(strong) { color: #a0d4ff; font-weight: 600; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 16px; margin: 4px 0; }
.markdown-body :deep(li) { margin: 2px 0; }
.markdown-body :deep(p) { margin: 4px 0; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 11px; }
.markdown-body :deep(th) { background: rgba(108,99,255,0.2); color: #c0b8ff; padding: 4px 6px; border: 1px solid rgba(108,99,255,0.2); }
.markdown-body :deep(td) { padding: 3px 6px; border: 1px solid rgba(255,255,255,0.07); color: #ccc; }
.markdown-body :deep(blockquote) { border-left: 2px solid rgba(108,99,255,0.5); padding: 3px 8px; margin: 4px 0; color: #999; background: rgba(108,99,255,0.06); border-radius: 0 4px 4px 0; }
.result-actions { padding: 14px 16px; display: flex; gap: 8px; flex-wrap: wrap; }
.map-page.report-workbench .result-actions {
  position: fixed;
  left: 252px;
  right: 32px;
  bottom: 16px;
  z-index: 31;
  max-width: none;
  padding: 10px 14px;
  justify-content: flex-end;
  border: 1px solid rgba(108,99,255,0.2);
  border-radius: 10px;
  background: rgba(18,18,38,0.98);
  box-shadow: 0 12px 36px rgba(0,0,0,0.32);
  backdrop-filter: blur(10px);
}
.map-page.report-workbench .workflow-panel { display: none; }
.workflow-panel { position: absolute; bottom: 16px; left: 276px; right: calc(min(620px, 46vw) + 16px); background: rgba(13,13,26,0.96); border: 1px solid rgba(108,99,255,0.3); border-radius: 10px; backdrop-filter: blur(10px); z-index: 100; max-height: 260px; overflow: hidden; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }
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
/* 热力图图层样式 */
.heatmap-source-tag { margin-top: 6px; padding-left: 2px; }
/* 相似历史案例样式 */
.similar-cases-section { padding: 12px 16px; border-top: 1px solid rgba(108,99,255,0.12); }
.cases-loading { font-size: 12px; color: #888; display: flex; align-items: center; gap: 6px; padding: 8px 0; }

/* 地图搜索浮层 */
.map-search-bar {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: 480px;
  max-width: calc(100% - 40px);
  z-index: 200;
  filter: drop-shadow(0 4px 16px rgba(0,0,0,0.5));
}
.map-search-inner {
  display: flex;
  align-items: center;
  background: rgba(18, 18, 36, 0.95);
  border: 1px solid rgba(108,99,255,0.4);
  border-radius: 10px;
  padding: 0 12px;
  height: 44px;
  backdrop-filter: blur(12px);
  gap: 8px;
}
.map-search-icon {
  color: #6c63ff;
  font-size: 16px;
  flex-shrink: 0;
}
.map-search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #e0e0ff;
  font-size: 14px;
  caret-color: #6c63ff;
}
.map-search-input::placeholder { color: rgba(255,255,255,0.3); }
.map-search-clear {
  background: none;
  border: none;
  color: rgba(255,255,255,0.35);
  cursor: pointer;
  font-size: 14px;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
}
.map-search-clear:hover { color: rgba(255,255,255,0.7); }
.map-search-btn {
  background: linear-gradient(135deg, #6c63ff, #8b5cf6);
  border: none;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 5px 14px;
  border-radius: 7px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: opacity 0.2s;
}
.map-search-btn:hover { opacity: 0.85; }
.map-search-dropdown {
  background: rgba(18, 18, 36, 0.97);
  border: 1px solid rgba(108,99,255,0.3);
  border-top: none;
  border-radius: 0 0 10px 10px;
  max-height: 280px;
  overflow-y: auto;
  backdrop-filter: blur(12px);
}
.search-suggestion-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  transition: background 0.15s;
}
.search-suggestion-item:hover { background: rgba(108,99,255,0.12); }
.search-suggestion-item:last-child { border-bottom: none; }
.sug-icon { color: #6c63ff; font-size: 14px; flex-shrink: 0; }
.sug-content { flex: 1; min-width: 0; }
.sug-name { font-size: 13px; color: #e0e0ff; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sug-address { font-size: 11px; color: rgba(255,255,255,0.35); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 拖拽提示浮层 */
.drag-tip {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(108,99,255,0.92);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 20px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 200;
  pointer-events: none;
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 16px rgba(108,99,255,0.4);
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s, transform 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
.case-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(108,99,255,0.15); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.case-card.success { border-color: rgba(103,194,58,0.3); background: rgba(103,194,58,0.04); }
.case-card.failed { border-color: rgba(245,108,108,0.3); background: rgba(245,108,108,0.04); }
.case-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.case-similarity { font-size: 11px; color: #6c63ff; font-weight: 600; }
.case-name { font-size: 13px; font-weight: 600; color: #e0e0ff; margin-bottom: 3px; }
.case-address { font-size: 12px; color: #aaa; margin-bottom: 4px; }
.case-meta { display: flex; gap: 10px; font-size: 11px; color: #888; margin-bottom: 4px; }
.case-notes { font-size: 11px; color: #999; line-height: 1.5; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 4px; margin-top: 4px; }
.cases-empty { font-size: 12px; color: #666; text-align: center; padding: 12px 0; }
.research-import-preview { margin-top: 14px; display: flex; flex-direction: column; gap: 14px; }
.preview-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.preview-stat { border: 1px solid #e4e7ed; border-radius: 8px; padding: 10px; background: #f8fafc; }
.preview-stat span { display: block; font-size: 12px; color: #667085; margin-bottom: 4px; }
.preview-stat strong { font-size: 20px; color: #1f2937; }
@media (max-width: 900px) {
  .map-page.report-workbench .result-panel {
    padding-bottom: 430px;
  }
  .map-page.report-workbench .report-advisor-section {
    left: 12px;
    right: 12px;
    bottom: 82px;
  }
  .map-page.report-workbench .result-actions {
    left: 12px;
    right: 12px;
    bottom: 12px;
    justify-content: center;
  }
  .map-page.report-workbench .advisor-messages {
    max-height: 150px;
  }
  .education-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

