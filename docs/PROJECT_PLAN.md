# 电竞馆智能选址系统 - 详细开发计划 (Project Plan)

## 1. 项目架构与技术栈

系统采用标准的 **B/S 架构**，全面支持在 **Ubuntu** 环境下进行原生部署。为了实现高度智能化的 Agentic RAG 与记忆系统，AI 架构层进行了深度重构。

*   **前端 (Frontend)**：Vue 3 + Vite + TailwindCSS + Element Plus + 高德地图 JS API。
*   **后端 (Backend)**：Python 3.11 + FastAPI + SQLAlchemy + Pydantic。
*   **数据库 (Database)**：PostgreSQL 16 + PostGIS（地理空间计算）+ pgvector（向量检索）。
*   **缓存与队列 (Cache & Queue)**：Redis（用于 JWT 鉴权、API 缓存、异步任务）。
*   **部署 (Deployment)**：Nginx（反向代理与静态资源）+ Systemd（进程守护）+ Shell 脚本（一键安装）。

### 🤖 AI 架构层 (基于 Agentic RAG 与多维记忆系统)
*   **大模型引擎 (LLM)**：支持通过配置切换**API 大模型**（如 OpenAI, 阿里云百炼）与**本地推理模型**（如 Ollama + Qwen/Llama）。
*   **向量模型 (Embedding)**：支持切换**API 向量模型**与**本地嵌入式模型**（如 `sentence-transformers`）。
*   **重排模型 (Reranker)**：**新增**重排模型接口（支持本地 BGE-Reranker 或 API 服务），用于在多路召回（混合检索）后提升上下文精确度 (Context Precision)。
*   **记忆系统 (Memory System)**：
    *   **语义记忆**：记录用户的长期偏好（如选址偏好的城市、特定参数阈值）。
    *   **情景记忆**：记录历史评估交互，用于 few-shot 示例增强。
    *   **程序记忆 (Skill)**：管理选址评估的标准操作流程（SOP），作为结构化的 Skill 文档供 Agent 调用。
    *   **时效性管理**：引入类似艾宾浩斯遗忘曲线的权重衰减与激活机制，解决“忘”比“存”难的问题。

## 2. 功能拆解与迭代阶段 (Milestones & Estimates)

整个项目分为 4 个核心阶段（Sprint），总计预估 **4-5 周**。

### 阶段 1：基础设施与用户体系 (第 1 周)
*   **目标**：搭建前后端框架，实现数据库连接、用户登录与鉴权、系统配置管理。
*   **核心任务**：
    1.  初始化 Vue 3 和 FastAPI 项目结构。
    2.  编写 Ubuntu 一键安装与环境配置脚本（`cat eof` 等结构，可直接复制）。
    3.  设计 PostgreSQL 数据库表结构（用户、租户、配置表）。
    4.  实现 JWT 登录、注册、权限验证。
    5.  开发系统配置管理接口（高德 Key、大模型 API/本地配置、嵌入模型配置、重排模型配置）。
*   **估算**：5 天。

### 阶段 2：数据层构建与自适应评分闭环 (第 2 周)
*   **目标**：实现电竞馆多维数据的标准化上传、解析、存储、分析总结，并闭环更新评分模型。
*   **核心任务**：
    1.  **多维数据模板体系**：提供多种 `.xlsx` 模板，涵盖电竞馆核心数据维度：
        *   **基础模板**：店铺名称、详细地址（自动转经纬度）、面积、机器数、租金、成败标签、经验总结等。
        *   **营收模板**：水吧收入、网费收入、台球/棋牌附加收入、净利润等。
        *   **会员画像模板**：年龄段分布（如25-30岁占比）、职业分布、消费频次、客单价等。
        *   **硬件外设模板**：显卡配置比例（如4060/4070/4090占比）、显示器刷新率、外设品牌等。
    2.  **原始文件追溯**：所有上传的 Excel 文件**永远先完整保存在服务器本地或对象存储中**，生成唯一文件 ID 关联入库记录，确保可追溯。
    3.  **数据解析与存储**：
        *   自动将“详细地址”转换为经纬度；以“店铺名称/ID”为主键自动拆分识别，独立记录。
        *   结构化数据（如年龄占比、营收数据）存入 PostgreSQL 关系型表。
        *   非结构化数据（经验总结）通过**嵌入式模型**向量化存入 pgvector。
    4.  **数据分析与总结（自适应闭环）**：
        *   **分析引擎**：后台定时或手动触发数据分析任务（如：分析发现某店“25-30岁会员贡献了70%营业额”且“净利润极高”）。
        *   **大模型总结**：调用大模型对分析结果进行深度总结，提取成功模式（如：“25-30岁客群是高净利核心”）。
        *   **更新打分模型**：将总结出的模式转化为评分权重调整策略（如：在选址时，将周边25-30岁人口密度的权重从 15% 提升至 25%），存入 `scoring_rules` 表。
*   **说明**：历史运营数据仅起到**辅助和矫正（few-shot/RAG/动态权重）**作用，没有历史数据，系统依赖基础规则和外部数据依然完整可用。
*   **估算**：6 天。

### 阶段 3：地图交互与 Agent 记忆系统 (第 3 周)
*   **目标**：完成前端地图交互，接入外部 API，并建立支持“越用越聪明”的记忆机制。
*   **核心任务**：
    1.  前端集成高德地图，实现底图展示、多边形框选、地址搜索。
    2.  后端对接高德 API（POI）和美团 API（竞品数据）。
    3.  开发六大维度评分引擎（市场、位置、竞争、经济、合规、技术），并支持读取阶段2生成的动态权重。
    4.  **开发 Agent 记忆模块**：
        *   建立用户的语义记忆库（记录选址偏好）和情景记忆库（记录历次交互）。
        *   实现记忆的自然降权机制，确保最新偏好权重最高。
*   **估算**：7 天。

### 阶段 4：Agentic RAG 报告与智能推荐 (第 4-5 周)
*   **目标**：打通包含多路召回与重排的 Agentic RAG 链路，生成高质量报告并支持宏观区域推荐。
*   **核心任务**：
    1.  **Agentic RAG 检索链路（核心设计）**：
        Agent 不再是“傻瓜式”的单次检索，而是具备以下 5 个核心判断能力：
        *   **判断要不要检索**：用户提问“什么是电竞馆选址的常规标准？”（靠模型常识直接答） vs “这个地址周围的竞品情况如何？”（必须触发外部高德/美团 API 检索）。
        *   **判断先检索哪一路（路由）**：需要经验总结走 `pgvector` 向量检索；需要特定店铺数据走 PostgreSQL 结构化 SQL 检索；需要周边动态走高德 API 检索。
        *   **判断一次够不够（循环重试）**：如果第一次检索返回的竞品数据为空，Agent 决定是否扩大搜索半径（如 1km 扩大到 3km）进行第二轮补搜。
        *   **判断要不要多跳**：多步推理。例如先通过向量检索找到“成功店铺的特征是靠近大学城”，然后触发第二跳去高德 API 检索“当前目标地址 3km 内是否有大学”。
        *   **判断怎么合并证据**：来自高德的 POI 数据、PostgreSQL 的历史营收数据、pgvector 的相似经验，先进行去重，然后统一输入给**重排模型 (Reranker)** 进行相关性打分，最后保留高分证据交给大模型。
    2.  **LLM 报告生成**：组装重排后的历史经验、当前得分（基于自适应权重）与用户短期/长期记忆，调用推理模型生成《智能选址评估报告》。随着历史数据完善，命中相似案例概率增加，打分模型更准，回答越来越准确。
    3.  **智能区域推荐**：前端框选区域，后端网格化评估，推荐 Top 3 坐标，并规避已有连锁店辐射圈。
*   **估算**：8 天。

## 3. 核心文件结构规划 (Directory Structure)

```text
esports-site-selection/
├── install.sh                  # Ubuntu 一键安装脚本
├── deploy/                     # 部署相关配置
├── frontend/                   # Vue 3 前端代码
└── backend/                    # FastAPI 后端代码
    ├── main.py                 # FastAPI 入口
    ├── app/
    │   ├── api/                # 路由控制器
    │   ├── core/               # 核心配置
    │   ├── db/                 # 数据库连接
    │   ├── models/             # SQLAlchemy ORM 模型
    │   └── services/           # 业务逻辑层
    │       ├── llm_gateway.py  # 推理模型网关 (支持 API/本地)
    │       ├── embedding.py    # 嵌入式向量模型服务
    │       ├── reranker.py     # 重排模型服务
    │       ├── memory.py       # Agent 记忆系统 (语义/情景/程序记忆)
    │       ├── rag_engine.py   # Agentic RAG 引擎 (实现5大判断节点与循环)
    │       ├── amap.py         # 高德 API 封装 (含地址转经纬度)
    │       ├── scoring.py      # 六维评分引擎 (含自适应权重更新逻辑)
    │       ├── data_analyzer.py# 数据分析与总结引擎 (分析营收/会员画像等)
    │       └── importer.py     # 多维模板解析、原始文件保存与店铺识别
└── docs/                       # 项目文档
```

## 4. 核心数据库设计 (Database Schema)

| 表名 | 描述 | 核心字段 |
|---|---|---|
| `users` | 用户表 | id, username, password_hash, tenant_id |
| `system_configs` | 系统配置表 | id, llm_type, llm_api_key, embed_type, rerank_type, map_api_key |
| `raw_uploads` | 原始文件表 | id, file_path, upload_time, status, template_type |
| `historical_shops` | 历史店铺表 | id, raw_file_id, shop_name, address, location(geometry) |
| `historical_metrics` | 历史运营指标 | id, shop_id, revenue_water, revenue_net, net_profit |
| `member_profiles` | 会员画像表 | id, shop_id, age_distribution(jsonb), occupation_distribution(jsonb) |
| `hardware_configs` | 硬件配置表 | id, shop_id, gpu_distribution(jsonb), monitor_refresh_rate |
| `knowledge_vectors`| 经验向量表 | id, shop_id, content(text), embedding(vector) |
| `agent_memories` | 记忆系统表 | id, user_id, memory_type, content, weight, last_accessed |
| `scoring_rules` | 动态评分规则 | id, dimension, base_weight, dynamic_weight, update_reason |

## 5. 测试与部署方案

### 5.1 测试方案
*   针对 Agentic RAG 链路，参考 RAGAS 指标测试上下文召回率与精确度，特别是测试 Agent 的多跳推理和失败重试逻辑。
*   针对数据分析闭环，测试上传特定会员画像后，评分权重是否被正确更新。

### 5.2 部署方案 (Ubuntu 原生)
提供标准的可执行命令脚本，例如：
```bash
cat << 'EOF' > install.sh
#!/bin/bash
# 安装基础依赖
apt update && apt install -y nginx postgresql-16 redis python3.11-venv
# 配置数据库及扩展...
EOF
chmod +x install.sh
./install.sh
```

---

**计划已完成，请你审查并回复‘确认’、‘修改’或具体意见。只有收到我明确的‘确认’或‘开始执行’指令后，才进入执行阶段。**
