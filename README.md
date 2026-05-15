# 电竞馆智能选址顾问系统 (AI-Lvshu)

一款专为连锁门店（如电竞馆、餐饮、零售等）打造的 **AI 驱动型智能选址与单点评估本地应用**。系统基于 B/S 架构设计，采用 Vue3 + FastAPI + PostgreSQL (pgvector) 构建，深度集成高德地图 API 与大语言模型（LLM），提供从地图可视化选址到 AI 深度分析的一站式解决方案。

## 🛡️ 为什么选择本地部署与自主开发？

在市面上已有众多商业选址软件和通用大模型（如 ChatGPT、文心一言）的情况下，我们选择自主开发并本地部署本系统，主要基于以下核心考量：

1. **商业机密与数据隐私的绝对安全**
   电竞馆的真实营收数据、会员画像（年龄/职业分布）、硬件配置 ROI 等，是企业最核心的商业机密。通用大模型或 SaaS 商业选址软件通常要求数据上传至云端，存在极大的数据泄露风险。本地部署确保所有核心经营数据、历史选址经验全部保存在本地数据库中，实现物理隔离。
2. **“越用越聪明”的闭环记忆与自我进化**
   通用大模型虽然知识渊博，但它是“无状态”的，无法真正理解你过去开店失败或成功的深层原因。本系统内置了独特的**三层记忆架构**与**动态权重引擎**。当你导入过去一年的营收与会员数据后，系统会自动分析并修正“选址评分权重”（例如发现某类商圈的年轻人消费力更强，从而自动调高该维度权重）。这种基于真实业务数据的自我进化，是任何通用模型无法提供的。
3. **深度的业务场景定制（Agentic RAG）**
   本系统不是一个简单的聊天框，而是深度整合了高德/美团 API、PostgreSQL+pgvector 向量数据库的 Agent 系统。它可以自动执行“获取经纬度 -> 搜索周边 POI -> 计算竞品密度 -> 提取历史相似案例 -> 综合六维打分 -> 输出分析报告”的完整工作流。
4. **模型自由度与成本控制**
   本地网关支持无缝接入本地开源模型（如通过 Ollama 运行 Qwen、Llama）或云端 API（OpenAI、阿里云百炼）。在处理极其敏感的数据时使用本地模型，在需要极强推理能力时切换云端模型，实现安全与成本的最佳平衡。

---

## 🌟 核心优势：越用越聪明的选址大脑

与传统的静态数据大屏或直接询问通用大模型不同，本系统具有独特的**记忆与自进化能力**：

### 1. 经验反哺的自适应评分闭环
系统包含六大评估维度（交通人流、竞品分析、目标客群、租金成本、配套设施、政策环境）。通过在「数据管理」中导入历史门店的真实运营数据（成功/关闭、营收、会员画像），系统会自动提取成功因子，并**动态调整各维度的评分权重**。例如，如果历史数据显示某类门店的成功高度依赖年轻人密度，系统会自动上调“目标客群”权重。

### 2. 知识库与历史相似案例召回
每次评估完成的结果、AI 深度报告，以及历史门店的经验总结，都会被向量化（Embedding）存入本地 PostgreSQL 的 `pgvector` 知识库。
当您评估一个新地址时，系统不仅能给出当前地址的得分，还能**自动召回最相似的历史门店案例**（如“这个位置和我们去年在小寨开的店相似度达 85%”），用真实的历史经营结果作为最强有力的参考。

### 3. 上下文注入的深度对话
在「单点精准评估」模块中，系统会自动将当前地址的**雷达图得分、核心 POI 数据、相似历史案例**等结构化数据作为上下文注入给大模型。这使得 AI 不再给出“建议选择人流量大的地方”这种通用废话，而是能基于具体数据进行深度剖析（如“虽然这里交通得分高达 90，但 500m 内有 3 家竞品，建议采取差异化竞争策略”）。

---

## ✨ 核心功能模块

### 🗺️ 智能地图选址 (Map View)
- **多模式选址**：支持地址搜索、地图点击选址、多边形框选分析。
- **消费热力图**：集成高德热力图层，支持免费的 **POI 密度模拟** 与精准的 **高德慧眼企业数据** 两种模式无缝切换。即使未配置真实 API Key，也能通过高斯分布采样算法生成地理分布合理的模拟热力点供参考。
- **六维雷达图**：直观展示目标位置的综合评分与各维度得分。
- **AI 深度报告**：评分完成后，大模型自动生成 800-1200 字的专业 Markdown 选址分析报告（包含风险提示与具体建议）。
- **后台独立工作**：页面状态全持久化（基于 Vue KeepAlive）。发起耗时的评估任务后，可随意切换至其他页面，返回时任务状态、工作流日志、AI 报告均完整保留，流式输出不中断。

### ⚖️ 多地址对比评估 (Compare View)
- **横向对比**：同时输入 2-3 个候选地址，系统自动进行批量评估。
- **直观表格**：通过对比表格并排展示各维度的得分差异，高分项自动高亮。
- **AI 综合推荐**：大模型根据对比数据，输出最终的推荐排序和详细理由。
- **状态持久化**：支持离开页面后任务继续在后台运行，返回时查看结果。

### 💬 单点精准评估 (Evaluate View)
- **多轮深度对话**：像和资深选址专家聊天一样，对特定地址进行深度剖析。
- **智能追问推荐**：每次 AI 回复后，自动生成 3 条相关的推荐问题，引导用户深入思考（如“如何评估这里的竞品压力？”）。输入框上方也会根据当前提问动态展示推荐问题。
- **富文本渲染**：对话内容支持完整的 Markdown 渲染（表格、加粗、代码块等），支持一键复制。

### 📊 数据管理与权重可视化 (Data View)
- **历史数据导入**：支持上传包含门店基础信息、营收记录、会员画像的 Excel 模板。
- **权重变化可视化**：清晰展示数据分析后权重的变化趋势（Before → After）及调整原因，让系统的“学习过程”完全透明。

### ⚙️ 系统配置 (Settings)
- **灵活的大模型接入**：支持本地 Ollama（如 Qwen2.5）、OpenAI、阿里云百炼等多种 LLM 接口。
- **API 密钥管理**：高德 JS API、Web 服务 API 集中管理。

---

## 🏗️ 系统架构与实现逻辑

### 核心实现逻辑
1. **Agent 工作流**：
   用户发起评估时，系统并发调用高德 API（地理编码、POI 搜索）收集环境数据，同时在 `pgvector` 中进行 RAG 检索寻找相似案例，最后结合 `scoring_rules` 表中的动态权重计算得分。所有步骤均通过 Server-Sent Events (SSE) 实时推送到前端。
2. **三层记忆系统 (memory.py)**：
   - **程序记忆**：用户明确设定的最高优先级规则。
   - **语义记忆**：从历史数据中总结的通用规律（永久保存）。
   - **情景记忆**：近期对话的上下文（随时间衰减）。
3. **前端状态持久化**：
   使用 Vue `<KeepAlive>` 结合组件 `name` 属性，将地图页、单点评估、对比评估三个核心页面的组件实例常驻内存，确保切换路由时不销毁组件，正在进行的 SSE 流和响应式数据完美保留。

### 技术栈
- **前端**：Vue 3 (Composition API) + Element Plus + AMap (高德地图 JS API) + marked
- **后端**：FastAPI (Python 3.11) + SQLAlchemy + psycopg2 + reportlab
- **数据库**：PostgreSQL 14 + pgvector (向量检索扩展)
- **部署**：Nginx (前端静态托管 + 反向代理) + Supervisor (后端进程管理)

---

## 🚀 部署指南 (Linux B/S 架构)

系统采用原生部署方式（非 Docker），适合在 Ubuntu 20.04/22.04 服务器上运行。

### 1. 首次安装
```bash
# 1. 下载源码
wget https://github.com/xuebailiang-svg/ai-lvshu/archive/refs/heads/main.zip -O ai-lvshu.zip
unzip ai-lvshu.zip
cd ai-lvshu-main

# 2. 赋予执行权限并运行安装脚本
chmod +x install.sh
sudo ./install.sh
```

如果不是使用 `install.sh` 全量安装，而是在已有部署目录中直接拉取或替换代码，更新后必须同步后端依赖：

```bash
cd /opt/esports-site
source backend/venv/bin/activate
pip install -r backend/requirements.txt
sudo supervisorctl restart esports-backend
```

### 2. 更新与重装（卸载旧版）
为了确保新代码完全生效，避免旧文件残留导致的各类问题，建议使用以下标准流程进行更新重装：

```bash
# 1. 停止当前服务
sudo supervisorctl stop esports-backend 2>/dev/null || true
sudo rm -f /etc/supervisor/conf.d/esports-backend.conf
sudo supervisorctl reread 2>/dev/null
sudo supervisorctl update 2>/dev/null

# 2. 清理旧版部署文件（数据库数据不受影响）
sudo rm -rf /opt/esports-site
sudo rm -f /etc/nginx/sites-enabled/esports-site /etc/nginx/sites-available/esports-site
sudo nginx -t && sudo systemctl reload nginx

# 3. 删除旧源码包
cd ~
rm -rf ai-lvshu-main ai-lvshu.zip

# 4. 下载最新代码并重新安装
wget https://github.com/xuebailiang-svg/ai-lvshu/archive/refs/heads/main.zip -O ai-lvshu.zip
unzip ai-lvshu.zip
cd ai-lvshu-main
chmod +x install.sh
sudo ./install.sh
```

本项目新增经验文档上传能力后，后端依赖中包含 `python-docx` 和 `pypdf`。如果你采用 `git pull` 或覆盖源码的方式更新，而不是重新执行 `install.sh`，请务必在项目根目录执行：

```bash
source backend/venv/bin/activate
pip install -r backend/requirements.txt
sudo supervisorctl restart esports-backend
```

### 3. 初始化配置
安装完成后，在浏览器中访问服务器 IP（默认端口 80），默认管理员账号：
- **账号**：`admin`
- **密码**：`admin123`

登录后，请务必前往 **系统配置** 页面完成以下设置：
1. **高德地图 API**：填写 Web 端 (JS API) 和 Web 服务 API Key。
2. **大模型配置**：选择本地 Ollama 或填写云端 API Key（如 OpenAI / 阿里云）。
3. **嵌入模型配置**：系统默认使用本地 `sentence-transformers` 进行向量化，也可配置为 Ollama 提供的 Embedding 模型（如 `bge-m3`）。
