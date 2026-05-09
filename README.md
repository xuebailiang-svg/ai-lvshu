# 🎮 电竞馆智能选址系统 (AI Site Selection)

> 基于 Agentic RAG 与多维数据分析的电竞馆智能选址决策支持系统。  
> 前后端分离 · Linux 原生部署 · 无需 Docker · 支持完全本地化私有部署

---

## 🌟 核心功能

| 功能模块 | 说明 |
|---|---|
| **智能选址地图** | 集成高德地图，支持地址搜索评估、点击选址、框选区域分析、连锁门店辐射圈标记 |
| **单点精准评估** | AI 对话式选址顾问，三栏布局（会话列表 + 对话区 + 工作流日志），流式输出 |
| **历史数据管理** | 支持基础信息、营收、会员画像、硬件配置等多维 Excel 模板上传解析，自动地理编码 |
| **系统配置** | 可视化配置大模型、嵌入模型、重排模型、高德地图 API，支持一键连通性测试 |
| **自适应评分闭环** | 根据历史上传数据，AI 自动分析并动态更新六大维度评分权重 |
| **Agentic RAG 报告** | 5 节点智能检索架构，结合历史案例与外部数据生成自然语言报告 |
| **三类记忆系统** | 语义记忆、情景记忆（艾宾浩斯遗忘曲线衰减）、程序记忆（用户偏好持久化） |
| **透明工作流** | 类 Dify 实时工作流日志面板，Agent 思考与执行过程完全可视化 |

---

## 🚀 快速部署（推荐）

### 环境要求

- Ubuntu 20.04 / 22.04 / 24.04
- Python 3.11+
- Node.js 18+ & pnpm
- PostgreSQL 14+（需安装 pgvector 扩展）
- Nginx + Supervisor

### 一键安装

```bash
git clone https://github.com/xuebailiang-svg/ai-lvshu.git
cd ai-lvshu
chmod +x install.sh
sudo ./install.sh
```

> 脚本会自动处理 PostgreSQL、pgvector、Nginx、Supervisor 等依赖，并将项目部署到 `/opt/esports-site`。

### 手动部署（分步）

详见项目根目录 [`DEPLOY.md`](./DEPLOY.md)，包含完整的分步安装说明和 FAQ。

---

## ⚙️ 首次配置

部署完成后，访问系统并以管理员身份登录：

- **用户名**：`admin`
- **密码**：`admin123`

登录后前往 **「系统配置」** 页面，完成以下配置：

### 大模型配置（本地 Ollama 示例）

| 配置项 | 推荐值 | 说明 |
|---|---|---|
| 模式 | `本地 Ollama` | 完全私有化 |
| Ollama 地址 | `http://127.0.0.1:11434/v1` | 默认地址 |
| 模型名称 | `qwen2.5:32b` | 逻辑最强，推荐用于报告生成 |

### 嵌入模型配置

| 配置项 | 推荐值 | 说明 |
|---|---|---|
| 模式 | `本地 Ollama` | |
| 接口地址 | `http://127.0.0.1:11434/api/embeddings` | |
| 模型名称 | `bge-m3:latest` | 优秀的多语言向量模型 |

### 重排模型配置

- 如无重排服务，**类型选 `none`**，系统自动跳过重排阶段，不影响正常运行。
- 进阶方案：使用 Xinference 或 TEI 部署 `bge-reranker-v2-m3`，填入接口地址。

### 高德地图 API

前往 [高德开放平台](https://lbs.amap.com/) 申请：
- **Web 服务 Key**：用于地理编码、POI 搜索（后端调用）
- **JS API Key + 安全密钥**：用于前端地图渲染

---

## 🛠️ 开发环境启动

```bash
# 后端
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cat > .env << 'EOF'
DATABASE_URL=postgresql://esports_user:esports_pass@localhost:5432/esports_db
SECRET_KEY=your-secret-key-here
PROJECT_NAME=电竞馆智能选址系统
API_V1_STR=/api/v1
EOF

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端（另开终端）
cd frontend
pnpm install
pnpm run dev
```

---

## 📁 项目结构

```text
ai-lvshu/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── api/                # 路由接口
│   │   │   ├── auth.py         # 认证（JWT）
│   │   │   ├── chat.py         # AI 对话评估（SSE 流式）
│   │   │   ├── config.py       # 系统配置管理
│   │   │   ├── data.py         # 数据上传与管理
│   │   │   └── evaluate.py     # 单点评估（SSE 流式）
│   │   ├── core/               # 核心配置（JWT、CORS、依赖注入）
│   │   ├── db/                 # 数据库连接与初始化
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   └── services/           # 核心业务逻辑
│   │       ├── amap.py         # 高德 API 封装
│   │       ├── analyzer.py     # 数据分析与动态权重更新
│   │       ├── embedding.py    # 向量化网关
│   │       ├── importer.py     # Excel 解析与店铺识别
│   │       ├── llm_gateway.py  # 大模型网关（SSE 流式）
│   │       ├── memory.py       # 三类记忆系统
│   │       ├── reranker.py     # 重排服务网关
│   │       ├── scoring.py      # 六维评分引擎
│   │       ├── template_generator.py  # Excel 模板生成
│   │       └── vector_rag.py   # Agentic RAG 核心逻辑
│   ├── main.py                 # 后端入口
│   └── requirements.txt
├── frontend/                   # Vue 3 + TypeScript 前端
│   └── src/
│       ├── api/                # Axios 封装
│       ├── layouts/            # 主布局（侧边栏导航）
│       ├── stores/             # Pinia 状态管理（auth）
│       └── views/
│           ├── LoginView.vue       # 登录页
│           ├── MapView.vue         # 智能选址地图
│           ├── EvaluateView.vue    # 单点精准评估（AI 对话）
│           ├── DataView.vue        # 历史数据管理
│           └── SettingsView.vue    # 系统配置（管理员）
├── DEPLOY.md                   # 详细部署文档
├── install.sh                  # Ubuntu 一键安装脚本
└── README.md
```

---

## 🔧 技术栈

| 层级 | 技术 |
|---|---|
| 前端框架 | Vue 3 + TypeScript + Vite |
| UI 组件库 | Element Plus |
| 地图 | 高德地图 JS API v2 |
| 后端框架 | FastAPI + Python 3.11 |
| 数据库 | PostgreSQL 14 + pgvector |
| 向量检索 | pgvector（HNSW 索引） |
| 流式输出 | SSE（Server-Sent Events） |
| 进程管理 | Supervisor + uvicorn |
| 反向代理 | Nginx 1.18 |
| 认证 | JWT（python-jose） |

---

## 📋 API 文档

后端启动后，访问 Swagger 文档：

```
http://your-server-ip:8000/api/v1/docs
```

---

## 🔒 安全说明

- 生产环境请修改 `.env` 中的 `SECRET_KEY` 为随机强密钥（至少 32 位）
- 登录后请立即修改默认管理员密码
- Nginx 配置中 `allow_origins=["*"]` 在生产环境请修改为具体域名

---

## 📝 更新日志

### v1.1.0（2026-05）
- 重构地图页面（MapView.vue）：三栏布局，优化单点评估交互体验，雷达图 + 工作流日志
- 完善系统配置面板（SettingsView.vue）：分 Tab 管理所有 API 配置，支持连通性测试
- 完整部署支持：pgvector 源码编译、Nginx SSE 无缓冲代理、Supervisor 进程管理
- 修复 requirements.txt 版本号问题，补充 .env 配置说明

### v1.0.0（初始版本）
- 核心功能完整实现：六维评分、Agentic RAG、三类记忆系统
- SSE 流式工作流日志可视化
- Excel 多维模板上传与自动地理编码
