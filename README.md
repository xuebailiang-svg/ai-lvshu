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

## 🚀 首次安装

### 环境要求

- Ubuntu 20.04 / 22.04 / 24.04
- Python 3.11+
- PostgreSQL 14+（需安装 pgvector 扩展）
- Nginx + Supervisor

### 一键安装

```bash
# 方式一：git clone（推荐，方便后续升级）
git clone https://github.com/xuebailiang-svg/ai-lvshu.git
cd ai-lvshu
chmod +x install.sh
sudo ./install.sh
```

```bash
# 方式二：下载 zip 包
wget https://github.com/xuebailiang-svg/ai-lvshu/archive/refs/heads/main.zip -O ai-lvshu.zip
unzip ai-lvshu.zip
cd ai-lvshu-main
chmod +x install.sh
sudo ./install.sh
```

> 脚本会自动处理 PostgreSQL、pgvector、Nginx、Supervisor 等依赖，并将项目部署到 `/opt/esports-site`。

---

## 🔄 升级 / 重装流程

> ⚠️ **重要提示**：直接重新执行 `install.sh` 不会生效！因为旧的部署目录 `/opt/esports-site` 仍然存在，脚本会跳过已有文件。必须先执行卸载步骤，再重新安装。

### 方式一：一键重装（推荐，复制粘贴即可）

```bash
# ===== 一键卸载并重装 =====

# 1. 停止并移除旧服务
sudo supervisorctl stop esports-backend 2>/dev/null || true
sudo rm -f /etc/supervisor/conf.d/esports-backend.conf
sudo supervisorctl reread 2>/dev/null
sudo supervisorctl update 2>/dev/null

# 2. 清理旧部署目录
sudo rm -rf /opt/esports-site

# 3. 清理旧 Nginx 配置
sudo rm -f /etc/nginx/sites-enabled/esports-site
sudo rm -f /etc/nginx/sites-available/esports-site
sudo nginx -t && sudo systemctl reload nginx

# 4. 删除旧源码，下载最新版本
cd ~
rm -rf ai-lvshu ai-lvshu-main ai-lvshu-main.zip ai-lvshu.zip
wget https://github.com/xuebailiang-svg/ai-lvshu/archive/refs/heads/main.zip -O ai-lvshu.zip
unzip ai-lvshu.zip
cd ai-lvshu-main

# 5. 重新安装
chmod +x install.sh && sudo ./install.sh
```

### 方式二：分步操作

**第一步：卸载旧版本**

```bash
# 停止后端服务
sudo supervisorctl stop esports-backend 2>/dev/null || true
sudo rm -f /etc/supervisor/conf.d/esports-backend.conf
sudo supervisorctl reread && sudo supervisorctl update

# 删除部署目录（旧代码和旧前端文件）
sudo rm -rf /opt/esports-site

# 删除 Nginx 站点配置
sudo rm -f /etc/nginx/sites-enabled/esports-site
sudo rm -f /etc/nginx/sites-available/esports-site
sudo nginx -t && sudo systemctl reload nginx
```

> **说明**：以上操作不会删除数据库，历史数据会保留。如需同时清空数据库，追加执行：
> ```bash
> sudo -u postgres psql -c "DROP DATABASE IF EXISTS esports_db;"
> sudo -u postgres psql -c "DROP USER IF EXISTS esports_user;"
> ```

**第二步：下载最新代码**

```bash
cd ~
rm -rf ai-lvshu ai-lvshu-main ai-lvshu-main.zip ai-lvshu.zip

# 选其一：
# git clone（推荐）
git clone https://github.com/xuebailiang-svg/ai-lvshu.git && cd ai-lvshu

# 或 zip 包
wget https://github.com/xuebailiang-svg/ai-lvshu/archive/refs/heads/main.zip -O ai-lvshu.zip
unzip ai-lvshu.zip && cd ai-lvshu-main
```

**第三步：重新安装**

```bash
chmod +x install.sh
sudo ./install.sh
```

---

## 🔧 常用运维命令

```bash
# 查看后端运行状态
sudo supervisorctl status esports-backend

# 查看后端实时日志（接口请求记录）
tail -f /var/log/esports-backend.out.log

# 查看后端错误日志（异常堆栈）
tail -f /var/log/esports-backend.err.log

# 重启后端（修改配置后执行）
sudo supervisorctl restart esports-backend

# 重启 Nginx
sudo systemctl restart nginx

# 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log

# 连接数据库（查看数据）
sudo -u postgres psql -d esports_db
```

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
│   ├── dist/                   # 预构建产物（随代码一起提交，install.sh 直接使用）
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
http://your-server-ip/api/v1/docs
```

---

## 🔒 安全说明

- 生产环境请修改 `.env` 中的 `SECRET_KEY` 为随机强密钥（至少 32 位）
- 登录后请立即修改默认管理员密码
- Nginx 配置中 `allow_origins=["*"]` 在生产环境请修改为具体域名

---

## 📝 更新日志

### v1.2.0（2026-05）

- 预构建 `dist` 随代码一起提交，彻底解决 install.sh 前端构建失败问题
- 新增 README 卸载/重装/升级完整流程和一键重装命令
- install.sh 新增数据库表自动初始化和默认管理员创建步骤
- 修复 SettingsView.vue 中 token key 错误（`access_token` → `token`）导致系统配置页面 401 问题
- Nginx 配置新增 `proxy_set_header Authorization` 防止 token 在代理层丢失

### v1.1.0（2026-05）

- 重构地图页面（MapView.vue）：三栏布局，优化单点评估交互体验，雷达图 + 工作流日志
- 完善系统配置面板（SettingsView.vue）：分 Tab 管理所有 API 配置，支持连通性测试
- 修复 evaluate.py / chat.py 双重路由前缀导致 404 问题
- 修复 config.py 连通性测试接口 405 问题（GET → POST）

### v1.0.0（初始版本）

- 核心功能完整实现：六维评分、Agentic RAG、三类记忆系统
- SSE 流式工作流日志可视化
- Excel 多维模板上传与自动地理编码
