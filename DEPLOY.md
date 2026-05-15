# 🎮 电竞馆智能选址系统 - 部署指南

本文档提供在 Linux 环境下部署本系统的完整步骤，涵盖依赖安装、配置说明以及常见问题解决方案。

## 📋 1. 系统要求

- **操作系统**：Ubuntu 20.04 / 22.04 / 24.04 (推荐)
- **内存**：最低 4GB（如需本地运行 LLM，推荐 16GB+）
- **磁盘**：最低 20GB 可用空间
- **架构**：B/S 架构（原生部署，无需 Docker）

---

## 🛠️ 2. 一键安装 (推荐)

系统提供了一键安装脚本，自动处理 PostgreSQL 16、Nginx、Supervisor 等依赖。

```bash
# 1. 克隆代码
git clone https://github.com/xuebailiang-svg/ai-lvshu.git
cd ai-lvshu

# 2. 赋予执行权限并运行
chmod +x install.sh
sudo ./install.sh
```

> **注意**：脚本会自动将项目部署到 `/opt/esports-site` 目录，并自动生成默认的 `.env` 配置文件。

---

## ⚙️ 3. 手动分布安装 (适合自定义环境)

如果你希望完全控制部署过程，请按以下步骤手动安装。

### 3.1 基础环境准备
```bash
# 更新源并安装基础工具
sudo apt update
sudo apt install -y curl ca-certificates gnupg lsb-release git python3.11 python3.11-venv python3-pip redis-server nginx supervisor
```

### 3.2 安装 PostgreSQL 16 及扩展
Ubuntu 默认源可能只提供 PostgreSQL 14，必须添加官方源：
```bash
# 导入官方 GPG Key
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/postgresql.gpg

# 添加 APT 源
echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list

# 安装 PG 16 及空间/向量扩展
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-postgis-3 postgresql-16-pgvector

# 创建数据库与用户
sudo -u postgres psql -c "CREATE DATABASE esports_db;"
sudo -u postgres psql -c "CREATE USER esports_user WITH PASSWORD 'esports_pass';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE esports_db TO esports_user;"
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3.3 后端部署
```bash
cd backend

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 创建配置文件
cat << 'EOF' > .env
DATABASE_URL=postgresql://esports_user:esports_pass@localhost:5432/esports_db
SECRET_KEY=CHANGE_ME_TO_A_RANDOM_SECRET_KEY_AT_LEAST_32_CHARS
PROJECT_NAME=电竞馆智能选址系统
API_V1_STR=/api/v1
UPLOAD_ROOT=/opt/ai-lvshu/data/uploads
EOF
```

如果修改了 `UPLOAD_ROOT`，需要确保运行后端服务的 Linux 用户对该目录有读写权限。

### 3.4 前端构建
```bash
# 安装 Node.js (如未安装)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pnpm

# 构建前端
cd ../frontend
pnpm install
pnpm run build
```

### 3.5 Nginx 与守护进程
参考项目根目录 `install.sh` 脚本中的 Nginx 与 Supervisor 配置段落进行配置。

---

## 🔧 4. 常见问题排查 (FAQ)

### Q1: `postgresql-16 无法定位软件包`
**原因**：Ubuntu 默认源版本过低。
**解决**：参考上文 3.2 节，添加 PostgreSQL 官方 `apt.postgresql.org` 源后重新 `apt update`。

### Q2: Supervisor 报错 `Invalid user name`
**原因**：配置文件中 `user` 字段指定的用户在系统中不存在。
**解决**：检查 `/etc/supervisor/conf.d/esports-backend.conf`，将 `user=` 后面的名字改为你当前登录系统的实际用户名（例如 `scott`），然后执行 `sudo supervisorctl update`。

### Q3: 后端安装依赖报错 `No matching distribution found for pandas==3.0.2`
**原因**：旧版 `requirements.txt` 中存在错误的版本号。
**解决**：请 `git pull` 拉取最新代码（已修正为 `pandas==2.2.3` 等正确版本），然后重新执行 `pip install -r requirements.txt`。

### Q4: `bash: venv/bin/activate: 没有那个文件或目录`
**原因**：未创建 Python 虚拟环境。
**解决**：在 `backend` 目录下执行 `python3 -m venv venv` 创建环境，然后再执行 `source venv/bin/activate`。

### Q5: 页面显示正常，但无法登录或 API 报 502 错误
**原因**：后端 FastAPI 服务未启动或 Nginx 反向代理配置错误。
**解决**：
1. 检查后端状态：`sudo supervisorctl status`
2. 查看后端报错日志：`tail -n 50 /var/log/esports-backend.err.log`
3. 手动测试后端：进入 `backend` 目录，激活虚拟环境后运行 `uvicorn main:app --host 0.0.0.0 --port 8000` 看是否有报错。

### Q6: 评估页面右侧的"工作流日志"不显示或延迟很久才一起出现
**原因**：Nginx 缓冲了 SSE (Server-Sent Events) 流式输出。
**解决**：确保 Nginx 配置中针对 SSE 路由关闭了缓冲：
```nginx
location ~ ^/api/v1/(evaluate|chat)/.*stream {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_cache off;
    proxy_buffering off;
    chunked_transfer_encoding on;
}
```
修改后执行 `sudo systemctl restart nginx`。

---

## 🔒 5. 系统初始化与账号

部署完成后，通过浏览器访问服务器 IP。
系统启动时会自动初始化数据库表并创建默认管理员：
- **用户名**：`admin`
- **密码**：`admin123`

登录后，请立即前往「系统配置」页面，配置高德地图 API Key 以及大模型接口。
