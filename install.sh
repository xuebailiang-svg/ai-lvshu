#!/bin/bash
# 电竞馆智能选址系统 - Ubuntu 一键安装脚本
set -e

echo "=== 开始安装电竞馆智能选址系统 ==="

# 1. 安装系统基础依赖
echo ">> 正在安装系统基础依赖..."
sudo apt update
sudo apt install -y nginx postgresql-16 postgresql-16-postgis-3 postgresql-16-pgvector redis-server python3.11 python3.11-venv curl git supervisor

# 2. 配置 PostgreSQL
echo ">> 正在配置 PostgreSQL..."
sudo -u postgres psql -c "CREATE DATABASE esports_db;" || true
sudo -u postgres psql -c "CREATE USER esports_user WITH PASSWORD 'esports_pass';" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE esports_db TO esports_user;" || true
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -d esports_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. 部署目录准备
echo ">> 正在创建部署目录..."
sudo mkdir -p /opt/esports-site
sudo chown -R $USER:$USER /opt/esports-site
# 假设当前目录包含 backend 和 frontend
cp -r backend frontend /opt/esports-site/

# 4. 后端环境设置
echo ">> 正在配置后端环境..."
cd /opt/esports-site/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 前端构建 (需要 node.js)
echo ">> 正在构建前端..."
if ! command -v npm &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
    sudo npm install -g pnpm
fi
cd /opt/esports-site/frontend
pnpm install
pnpm run build

# 6. Nginx 配置
echo ">> 正在配置 Nginx..."
cat << 'NGINX_EOF' | sudo tee /etc/nginx/sites-available/esports-site
server {
    listen 80;
    server_name localhost;

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
    }

    # SSE (Server-Sent Events) 支持
    location /api/sse {
        proxy_pass http://127.0.0.1:8000/api/sse;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_cache off;
        proxy_read_timeout 24h;
    }
}
NGINX_EOF
sudo ln -sf /etc/nginx/sites-available/esports-site /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl restart nginx

# 7. Supervisor 配置 (守护 FastAPI)
echo ">> 正在配置 Supervisor..."
cat << 'SUP_EOF' | sudo tee /etc/supervisor/conf.d/esports-backend.conf
[program:esports-backend]
directory=/opt/esports-site/backend
command=/opt/esports-site/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
autostart=true
autorestart=true
stderr_logfile=/var/log/esports-backend.err.log
stdout_logfile=/var/log/esports-backend.out.log
user=ubuntu
environment=PATH="/opt/esports-site/backend/venv/bin"
SUP_EOF
sudo supervisorctl reread
sudo supervisorctl update

echo "=== 安装完成！ ==="
echo "请访问 http://服务器IP 查看系统。"
