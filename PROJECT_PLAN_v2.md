# 智能选址系统 V2 全面优化开发计划

> 版本：V2.0 | 日期：2026-05-11 | 状态：待确认

---

## 一、代码审查发现的问题清单

| # | 文件 | 问题 | 严重程度 |
|---|------|------|---------|
| 1 | `evaluate.py` | `event_stream()` 直接使用外部 `db` Session，StreamingResponse 返回后 Session 可能已关闭 | 高 |
| 2 | `scoring.py` | `evaluate_location()` 末尾无 LLM 报告生成步骤，只有数字评分，无 AI 文字分析 | 高 |
| 3 | `MapView.vue` | `aiContent` 展示区存在但 `scoring.py` 从未 yield `type=llm` 事件，AI 报告区永远为空 | 高 |
| 4 | `chat.py` | `SYSTEM_PROMPT` 写死"电竞馆顾问"，无推荐问题生成逻辑，回复后无 follow-up 提示 | 中 |
| 5 | `EvaluateView.vue` | 聊天气泡无 Markdown 渲染，长文本无格式；无推荐问题组件；输入框提示语单薄 | 中 |
| 6 | `amap.py` | 热力图函数仅有注释，无实现；前端 MapView 无热力图图层开关 | 中 |
| 7 | `MapView.vue` | 评估报告面板无 AI 文字报告展示（aiContent 区域样式简陋，无 Markdown 渲染） | 中 |
| 8 | `requirements.txt` | `openai` 之前被注释，已修复；`httpx` 版本与 openai 2.x 可能冲突 | 低 |

---

## 二、本次优化目标

### 2.1 聊天界面升级（EvaluateView.vue）

**智能推荐问题（核心新功能）**：
- 每次 AI 回复完成后，后端额外生成 3 条 follow-up 推荐问题（通过 SSE `type=suggestions` 事件推送）
- 前端在 AI 气泡下方展示 3 个可点击的推荐问题标签，点击即发送
- 欢迎页的快速问题也升级为动态生成（基于用户历史偏好）

**UI 全面优化**：
- AI 消息气泡支持 Markdown 渲染（使用 `marked` + `DOMPurify`）
- 输入框增加地址联想提示（输入地址时自动补全）
- 消息气泡增加复制按钮
- 工作流侧边栏样式优化（步骤图标更直观、进度动画）
- 响应式布局优化（移动端适配）

### 2.2 报告完整化

**单点评估（scoring.py + evaluate.py）**：
- 在 `evaluate_location()` 末尾新增 LLM 报告生成步骤
- 报告包含：综合结论、各维度深度分析、核心风险点、3 条具体建议、与历史成功案例对比
- 通过 SSE `type=llm` 事件流式推送 AI 报告内容
- 前端 MapView 的 AI 报告区支持 Markdown 渲染

**地图选址（MapView.vue）**：
- 右侧结果面板增加"AI 深度报告"折叠区，支持展开/收起
- 报告内容 Markdown 渲染
- 增加"导出完整报告"按钮（生成 PDF/文本）

**EvaluateView 对话报告**：
- 对话中涉及地址评估时，自动触发完整评分流程并在对话中展示报告卡片

### 2.3 消费热力图集成

**高德热力图方案**：
- 高德 JS API 内置 `AMap.HeatMap` 插件，**无需额外付费**，使用现有 JS API Key 即可
- 热力图数据来源：使用高德 POI 数据模拟消费密度（以餐饮、娱乐、购物 POI 密度代表消费热度）
- 后端新增 `/api/v1/map/heatmap-data` 接口，返回指定区域的 POI 密度热力点数据
- 前端 MapView 新增热力图图层开关

**预留接口说明**：
- 高德「慧眼」商业数据 API（`https://restapi.amap.com/v4/`）可提供真实消费热力数据，需单独申请企业版权限
- 系统预留 `amap_huiyan_key` 配置项，配置后自动切换为真实消费热力数据

### 2.4 README 重写

重点突出"越用越聪明"的核心优势：
- 三类记忆系统详细说明
- 自适应评分闭环图解
- Agentic RAG 架构说明
- 与传统选址工具的对比表
- 完整的安装/升级/卸载流程

---

## 三、技术方案

### 3.1 推荐问题生成

**后端（chat.py）**：
```python
# 在 LLM 回复完成后，额外调用一次 LLM 生成 3 条推荐问题
SUGGEST_PROMPT = "根据以上对话，生成3条用户可能感兴趣的后续问题，JSON格式：[\"问题1\",\"问题2\",\"问题3\"]"
suggestions = await chat_completion([...history, {"role": "user", "content": SUGGEST_PROMPT}], db)
yield {"type": "suggestions", "questions": json.loads(suggestions)}
```

**前端（EvaluateView.vue）**：
```vue
<div class="suggestions" v-if="msg.suggestions">
  <div v-for="q in msg.suggestions" @click="sendMessage(q)" class="suggestion-chip">{{ q }}</div>
</div>
```

### 3.2 评估报告 LLM 生成（scoring.py）

```python
# 在 yield final_result 之前
report_prompt = f"""
你是电竞馆选址专家，请基于以下评分数据生成完整选址报告：
地址：{address}
综合评分：{total_score}分（{grade_label}）
各维度评分：{json.dumps(dimension_results, ensure_ascii=False)}
...
"""
async for token in chat_completion_stream([{"role":"user","content":report_prompt}], db):
    yield {"type": "llm", "data": {"content": token}}
```

### 3.3 热力图集成

**前端**：
```javascript
// 加载高德热力图插件
AMap.plugin('AMap.HeatMap', () => {
  heatmap = new AMap.HeatMap(map, { radius: 25, opacity: [0, 0.8] })
  heatmap.setDataSet({ data: heatmapData, max: 100 })
})
```

**后端（amap.py 新增）**：
```python
async def get_heatmap_data(lng, lat, radius, api_key):
    """获取区域消费热力数据（基于 POI 密度）"""
    categories = ["餐饮服务", "购物服务", "娱乐休闲服务"]
    # 调用高德 POI 搜索，返回各 POI 坐标作为热力点
```

---

## 四、文件改动清单

| 文件 | 改动类型 | 主要内容 |
|------|---------|---------|
| `backend/app/api/chat.py` | 修改 | 新增推荐问题生成逻辑（suggestions 事件） |
| `backend/app/api/evaluate.py` | 修改 | 修复 db Session 问题；新增热力图数据接口 |
| `backend/app/services/scoring.py` | 修改 | 新增 LLM 报告生成步骤（流式输出） |
| `backend/app/services/amap.py` | 修改 | 实现热力图数据获取函数 |
| `frontend/src/views/EvaluateView.vue` | 重构 | 推荐问题组件、Markdown 渲染、UI 全面优化 |
| `frontend/src/views/MapView.vue` | 修改 | 热力图图层、AI 报告 Markdown 渲染、完整报告展示 |
| `README.md` | 重写 | 系统说明、核心优势、架构图、部署指南 |

---

## 五、迭代阶段

| 阶段 | 内容 | 预计工作量 |
|------|------|----------|
| **Phase 1** | 代码审查修复 + 聊天界面升级（推荐问题 + Markdown + UI） | 2-3h |
| **Phase 2** | 评估报告完整化（scoring.py LLM 报告 + MapView 展示） | 1-2h |
| **Phase 3** | 消费热力图集成（后端接口 + 前端图层） | 1h |
| **Phase 4** | README 重写 + 提交推送 | 0.5h |

---

## 六、关于消费热力图 API 的说明

> **高德地图热力图有两种方案，请您确认使用哪种：**

**方案 A（推荐，免费，立即可用）**：
- 使用高德 JS API 内置 `AMap.HeatMap` 插件
- 热力数据由后端调用高德 POI 搜索 API 生成（以餐饮/娱乐/购物 POI 密度模拟消费热度）
- 使用现有高德 Web 服务 API Key，**无需额外申请**

**方案 B（精准，需申请企业权限）**：
- 高德「慧眼」商业智能数据平台（`https://lbs.amap.com/api/huiyan/`）
- 提供真实的人流热力、消费热力、客群画像等数据
- 需在高德开放平台申请「商业数据」权限（企业认证后可申请试用）
- 申请地址：`https://lbs.amap.com/api/huiyan/guide/base/introduce`

**系统将同时预留两种接口**，配置了慧眼 Key 则使用真实数据，否则使用 POI 密度模拟数据。

---

计划已完成，请你审查并回复「**确认**」、「**修改**」或具体意见。只有收到明确的「确认」或「开始执行」指令后，才进入执行阶段。
