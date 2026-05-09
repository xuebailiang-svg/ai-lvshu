# 🎮 电竞馆智能选址系统 (AI Site Selection)

基于 Agentic RAG 与多维数据分析的电竞馆智能选址决策支持系统。

## 🌟 核心功能

- **多维数据沉淀**：支持基础信息、营收、会员画像、硬件配置等多维 Excel 模板上传解析
- **自适应评分闭环**：根据历史上传数据，AI 自动分析并动态更新六大维度评分权重
- **地图交互评估**：集成高德地图，支持框选区域、连锁门店辐射圈标记、单点雷达图评估
- **Agentic RAG 报告**：5 节点智能检索架构，结合历史案例与外部数据生成自然语言报告
- **三类记忆系统**：支持语义记忆、情景记忆（艾宾浩斯遗忘曲线衰减）、程序记忆（用户偏好）
- **透明工作流**：类似 Dify 的实时工作流日志面板，Agent 思考与执行过程完全可视化

---

## 🚀 本地大模型部署指南

系统支持完全本地化的私有部署，确保数据绝对安全。根据你当前的 Ollama 列表：

```bash
NAME                    ID              SIZE      MODIFIED    
qwen2.5:14b-instruct    7cdf5a0187d5    9.0 GB    2 weeks ago    
qwen2.5:14b             7cdf5a0187d5    9.0 GB    4 weeks ago    
bge-m3:latest           790764642607    1.2 GB    4 weeks ago    
qwen2.5:32b             9f13ba1299af    19 GB     4 weeks ago
```

### 1. 现有模型分析

你已经拥有非常棒的本地模型组合，**可以直接跑通核心流程**：
- **推理模型 (LLM)**：`qwen2.5:32b` (推荐用于生成最终报告，逻辑最强) 或 `qwen2.5:14b-instruct` (推荐用于 Agent 路由判断，速度更快)
- **嵌入模型 (Embedding)**：`bge-m3:latest` (非常优秀的向量化模型，支持多语言和长文本)

### 2. 还需要补充什么？

系统采用了 Agentic RAG 架构，包含一个**重排模型 (Reranker)** 节点。Ollama 原生不直接支持 Reranker 接口。

**解决方案（二选一）：**
1. **方案 A（推荐，最简单）**：在系统配置中将重排模型配置留空或设置为 `none`，系统会自动跳过重排阶段，直接使用向量检索的原始分数，不影响系统运行。
2. **方案 B（进阶，效果更好）**：部署一个本地的 BGE-Reranker 服务（如使用 Xinference 或 TEI 部署 `bge-reranker-v2-m3`），然后在系统配置中填入其接口地址。

---

## ⚙️ 系统配置接口填写示例

登录系统后，进入**「⚙️ 系统配置」**页面，按以下示例填写你的本地模型配置：

### 大模型配置 (LLM)
| 配置项 | 填写示例 | 说明 |
|-------|---------|------|
| llm.type | `local` | 指定使用本地模型 |
| llm.local_url | `http://127.0.0.1:11434/v1` | 你的 Ollama 默认 API 地址（注意加上 /v1） |
| llm.model_name | `qwen2.5:32b` | 使用你本地最大的模型生成报告 |
| llm.api_key | `ollama` | Ollama 随便填一个字符串即可 |

### 向量模型配置 (Embedding)
| 配置项 | 填写示例 | 说明 |
|-------|---------|------|
| embed.type | `local` | 指定使用本地模型 |
| embed.local_url | `http://127.0.0.1:11434/api/embeddings` | Ollama 向量化接口 |
| embed.model_name | `bge-m3:latest` | 使用你本地的 bge-m3 |
| embed.api_key | `ollama` | 随便填 |

### 重排模型配置 (Reranker) - 暂不使用
| 配置项 | 填写示例 | 说明 |
|-------|---------|------|
| rerank.type | `none` | 填 none 即可跳过重排阶段 |

### 外部 API 配置
| 配置项 | 填写示例 | 说明 |
|-------|---------|------|
| amap_api_key | `你的高德Web服务Key` | 必须填写，用于地址转经纬度、周边竞品/交通/配套数据获取 |

---

## 🛠️ 安装与运行 (Linux 原生 B/S 架构)

本项目采用前后端分离架构，Linux 原生部署，无需 Docker。

### 1. 环境准备
确保你的 Ubuntu 服务器已安装：
- Python 3.11+
- Node.js 18+ (用于前端构建)
- PostgreSQL 16+ (必须安装 `postgis` 和 `pgvector` 扩展)
- Nginx

### 2. 一键安装脚本
项目根目录提供了 `install.sh` 脚本，可协助完成基础环境搭建：
```bash
chmod +x install.sh
sudo ./install.sh
```
*注：脚本会尝试安装 PostgreSQL 及其扩展，如果你的环境较特殊，建议手动配置数据库。*

### 3. 手动启动（开发环境）

**启动后端：**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# 启动 FastAPI
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**启动前端：**
```bash
cd frontend
pnpm install
pnpm run dev
```

### 4. 默认账号
系统启动并初始化数据库后，默认管理员账号：
- 用户名：`admin`
- 密码：`admin123`

---

## 📁 核心目录结构

```text
ai-lvshu/
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── api/              # 路由接口 (auth, data, evaluate, chat, config)
│   │   ├── core/             # 核心配置与安全 (JWT, CORS)
│   │   ├── db/               # 数据库连接与初始化 (init_db.py)
│   │   ├── models/           # SQLAlchemy ORM 模型 (用户、店铺、数据模板、配置)
│   │   └── services/         # 核心业务逻辑
│   │       ├── amap.py       # 高德 API 封装
│   │       ├── analyzer.py   # 数据分析与动态权重更新
│   │       ├── embedding.py  # 向量化网关
│   │       ├── importer.py   # Excel 解析与店铺自动识别
│   │       ├── llm_gateway.py# 大模型网关 (支持 SSE 流式)
│   │       ├── memory.py     # 三类记忆系统
│   │       ├── scoring.py    # 六维评分引擎
│   │       └── vector_rag.py # Agentic RAG 核心逻辑
│   └── main.py               # 后端入口
├── frontend/                 # Vue 3 前端
│   └── src/
│       ├── api/              # Axios 封装
│       ├── views/            # 核心页面 (MapView, EvaluateView, DataView)
│       └── layouts/          # 主布局
└── install.sh                # Ubuntu 部署脚本
```
