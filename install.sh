#!/bin/bash
# 电竞馆智能选址系统 - Ubuntu 一键安装脚本
# 支持 Ubuntu 20.04 (Focal) / 22.04 (Jammy) / 24.04 (Noble)
set -e

echo "=== 开始安装电竞馆智能选址系统 ==="

# ─────────────────────────────────────────
# 1. 检测系统版本
# ─────────────────────────────────────────
OS_CODENAME=$(lsb_release -cs 2>/dev/null || . /etc/os-release && echo "$VERSION_CODENAME")
echo ">> 检测到系统版本：$OS_CODENAME"

# ─────────────────────────────────────────
# 2. 添加 PostgreSQL 官方 APT 源
#    Ubuntu 默认源只有 PostgreSQL 14，需要官方源才能安装 16
# ─────────────────────────────────────────
echo ">> 正在添加 PostgreSQL 官方 APT 源..."
sudo apt install -y curl ca-certificates gnupg lsb-release

# 导入 PostgreSQL GPG Key
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | sudo gpg --dearmor -o /usr/share/keyrings/postgresql.gpg

# 写入 APT 源
echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] \
https://apt.postgresql.org/pub/repos/apt ${OS_CODENAME}-pgdg main" \
    | sudo tee /etc/apt/sources.list.d/pgdg.list > /dev/null

sudo apt update
echo ">> PostgreSQL 官方源添加完成"

# ─────────────────────────────────────────
# 3. 安装 PostgreSQL 16 + PostGIS + pgvector
# ─────────────────────────────────────────
echo ">> 正在安装 PostgreSQL 16 及扩展..."
sudo apt install -y \
    postgresql-16 \
    postgresql-16-postgis-3 \
    postgresql-16-pgvector \
    redis-server \
    nginx \
    supervisor \
    python3.11 \
    python3.11-venv \
    python3-pip \
    git

# ─────────────────────────────────────────
# 4. 配置 PostgreSQL
# ─────────────────────────────────────────
echo ">> 正在配置 PostgreSQL 数据库..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

sudo -u postgres psql -c "CREATE DATABASE esports_db;" 2>/dev/null || echo "  数据库已存在，跳过"
sudo -u postgres psql -c "CREATE USER esports_user WITH PASSWORD 'esports_pass';" 2>/dev/null || echo "  用户已存在，跳过"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE esports_db TO esports_user;" 2>/dev/null || true
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
echo ">> PostgreSQL 配置完成"

# ─────────────────────────────────────────
# 5. 部署目录准备
# ─────────────────────────────────────────
echo ">> 正在创建部署目录 /opt/esports-site ..."
sudo mkdir -p /opt/esports-site
CURRENT_USER=${SUDO_USER:-$USER}
sudo chown -R "$CURRENT_USER":"$CURRENT_USER" /opt/esports-site

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR/backend" "$SCRIPT_DIR/frontend" /opt/esports-site/

# ─────────────────────────────────────────
# 6. 后端 Python 环境
# ─────────────────────────────────────────
echo ">> 正在配置后端 Python 环境..."
cd /opt/esports-site/backend
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# ─────────────────────────────────────────
# 7. 前端构建
# ─────────────────────────────────────────
echo ">> 正在构建前端..."
if ! command -v node &> /dev/null; then
    echo "  Node.js 未安装，正在安装..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
fi

if ! command -v pnpm &> /dev/null; then
    sudo npm install -g pnpm
fi

cd /opt/esports-site/frontend
pnpm install
pnpm run build
echo ">> 前端构建完成"

# ─────────────────────────────────────────
# 8. 写入 .env 配置文件
# ─────────────────────────────────────────
echo ">> 正在写入后端环境配置..."
cat << 'ENV_EOF' > /opt/esports-site/backend/.env
# 数据库连接（PostgreSQL 16）
DATABASE_URL=postgresql://esports_user:esports_pass@localhost:5432/esports_db

# JWT 密钥（请修改为随机字符串）
SECRET_KEY=CHANGE_ME_TO_A_RANDOM_SECRET_KEY_AT_LEAST_32_CHARS

# 应用配置
PROJECT_NAME=电竞馆智能选址系统
API_V1_STR=/api/v1
ENV_EOF

# ─────────────────────────────────────────
# 9. Nginx 配置
# ─────────────────────────────────────────
echo ">> 正在配置 Nginx..."
cat << 'NGINX_EOF' | sudo tee /etc/nginx/sites-available/esports-site
server {
    listen 80;
    server_name _;

    # 前端静态文件
    location / {
        root /opt/esports-site/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # SSE (Server-Sent Events) 流式输出支持
    location ~ ^/api/v1/(evaluate|chat)/.*stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_cache off;
        proxy_buffering off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }
}
NGINX_EOF

sudo ln -sf /etc/nginx/sites-available/esports-site /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
echo ">> Nginx 配置完成"

# ─────────────────────────────────────────
# 10. Supervisor 守护进程配置
# ─────────────────────────────────────────
echo ">> 正在配置 Supervisor 守护进程..."
CURRENT_USER=${SUDO_USER:-$USER}
cat << SUP_EOF | sudo tee /etc/supervisor/conf.d/esports-backend.conf
[program:esports-backend]
directory=/opt/esports-site/backend
command=/opt/esports-site/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
autostart=true
autorestart=true
stderr_logfile=/var/log/esports-backend.err.log
stdout_logfile=/var/log/esports-backend.out.log
user=${CURRENT_USER}
environment=PATH="/opt/esports-site/backend/venv/bin"
SUP_EOF

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start esports-backend || true

# ─────────────────────────────────────────
# 完成
# ─────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     🎮 电竞馆智能选址系统安装完成！       ║"
echo "╠══════════════════════════════════════════╣"
echo "║  访问地址：http://$(hostname -I | awk '{print $1}')          ║"
echo "║  默认账号：admin / admin123               ║"
echo "║  API 文档：http://$(hostname -I | awk '{print $1}')/api/v1/docs ║"
echo "╠══════════════════════════════════════════╣"
echo "║  查看后端日志：                           ║"
echo "║  tail -f /var/log/esports-backend.out.log ║"
echo "╚══════════════════════════════════════════╝"
