# AI 智能选址评估系统 (AI Site Selection)

一款专为连锁门店（如电竞馆、餐饮、零售等）打造的 **AI 驱动型智能选址与单点评估应用**。系统基于 B/S 架构设计，采用 Vue3 + FastAPI + PostgreSQL (pgvector) 构建，深度集成高德地图 API 与大语言模型（LLM），提供从地图可视化选址到 AI 深度分析的一站式解决方案。

## 🌟 核心优势：越用越聪明的选址大脑

与传统的静态数据大屏不同，本系统具有独特的**记忆与自进化能力**：

### 1. 三重记忆体系
- **偏好记忆 (Preference Memory)**：自动记录老板/选址专员的选址偏好（如“偏好靠近大学城”、“租金敏感度高”），并在后续 AI 报告中自动应用这些标准。
- **语义记忆 (Semantic Memory)**：通过 pgvector 向量数据库，将历史选址对话、评估报告转化为经验库。遇到相似商圈时，AI 能自动回想起历史案例（“这个位置和我们去年在小寨开的店很像”）。
- **情景记忆 (Episodic Memory)**：完整记录每次对话的上下文，支持多轮连贯的深度追问，不再是“一问一答”的机械对话。

### 2. 自适应动态评分闭环
系统包含六大评估维度（交通人流、竞品分析、目标客群、租金成本、配套设施、政策环境）。通过录入历史门店的真实运营数据（成功/关闭），系统会自动调整各维度的评分权重，实现**“经验数据化，数据反哺决策”**的闭环。

### 3. Agent 工作流透明化
在单点评估和对话过程中，系统会在侧边栏实时展示 AI Agent 的思考过程和执行步骤（类似 Dify 的工作流日志），让 AI 的每一步分析都有迹可循，便于问题定位和逻辑优化。

---

## ✨ 核心功能模块

### 🗺️ 智能地图选址 (Map View)
- **多模式选址**：支持地址搜索、地图点击选址、多边形框选分析。
- **消费热力图**：集成高德热力图层，支持免费的 **POI 密度模拟** 与精准的 **高德慧眼企业数据** 两种模式无缝切换。
- **六维雷达图**：直观展示目标位置的综合评分与各维度得分。
- **AI 深度报告**：评分完成后，大模型自动生成 800-1200 字的专业 Markdown 选址分析报告（包含风险提示与具体建议）。

### 💬 单点精准评估 (Evaluate View)
- **多轮深度对话**：像和资深选址专家聊天一样，对特定地址进行深度剖析。
- **智能追问推荐**：每次 AI 回复后，自动生成 3 条相关的推荐问题，引导用户深入思考（如“如何评估这里的竞品压力？”）。
- **富文本渲染**：对话内容支持完整的 Markdown 渲染（表格、加粗、代码块等），支持一键复制。

### ⚙️ 系统配置 (Settings)
- **灵活的大模型接入**：支持本地 Ollama（如 Qwen2.5）、OpenAI、阿里云百炼等多种 LLM 接口。
- **API 密钥管理**：高德 JS API、Web 服务 API、高德慧眼 API 集中管理。

---

## 🚀 部署指南 (Linux B/S 架构)

系统采用原生部署方式（非 Docker），适合在 Ubuntu 20.04/22.04 服务器上运行。

### 1. 首次安装
```bash
# 1. 下载源码
wget https://github.com/xuebailiang-svg/ai-site-selection/archive/refs/heads/main.zip -O ai-site-selection.zip
unzip ai-site-selection.zip
cd ai-site-selection-main

# 2. 赋予执行权限并运行安装脚本
chmod +x install.sh
sudo ./install.sh
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
rm -rf ai-site-selection-main ai-site-selection.zip

# 4. 下载最新代码并重新安装
wget https://github.com/xuebailiang-svg/ai-site-selection/archive/refs/heads/main.zip -O ai-site-selection.zip
unzip ai-site-selection.zip
cd ai-site-selection-main
chmod +x install.sh
sudo ./install.sh
```

### 3. 初始化配置
安装完成后，在浏览器中访问服务器 IP（默认端口 80），默认管理员账号：
- **账号**：`admin`
- **密码**：`admin123`

登录后，请务必前往 **系统配置** 页面完成以下设置：
1. **高德地图 API**：填写 Web 端 (JS API) 和 Web 服务 API Key。
2. **高德慧眼 API**（可选）：填写企业版 Key 以获取精准消费热力图。
3. **大模型配置**：选择本地 Ollama 或填写云端 API Key（如 OpenAI / 阿里云）。

---

## 🛠️ 技术栈
- **前端**：Vue 3 (Composition API) + Element Plus + AMap (高德地图 JS API) + marked (Markdown 渲染)
- **后端**：FastAPI (Python 3.11) + SQLAlchemy + psycopg2
- **数据库**：PostgreSQL 14 + pgvector (向量检索扩展)
- **部署**：Nginx (前端静态托管 + 反向代理) + Supervisor (后端进程管理)
