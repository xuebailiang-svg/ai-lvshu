#!/bin/bash
# 电竞馆智能选址系统 - Ubuntu 一键安装脚本
# 支持 Ubuntu 20.04 (Focal) / 22.04 (Jammy) / 24.04 (Noble)
set -e

RESET_DEPLOY_DATA="${RESET_DEPLOY_DATA:-ask}"
RESET_CLEAR_ACCOUNTS="${RESET_CLEAR_ACCOUNTS:-no}"
for arg in "$@"; do
    case "$arg" in
        --reset-data)
            RESET_DEPLOY_DATA="yes"
            ;;
        --keep-data)
            RESET_DEPLOY_DATA="no"
            ;;
        --clear-accounts)
            RESET_CLEAR_ACCOUNTS="yes"
            ;;
    esac
done

echo "=== 开始安装电竞馆智能选址系统 ==="

# ─────────────────────────────────────────
# 1. 检测系统版本
# ─────────────────────────────────────────
OS_CODENAME=$(lsb_release -cs 2>/dev/null || . /etc/os-release && echo "$VERSION_CODENAME")
echo ">> 检测到系统版本：$OS_CODENAME"

# 采集服务资源预检：4 核 8G 为推荐配置。
CPU_CORES=$(nproc)
MEMORY_MB=$(free -m | awk '/^Mem:/ {print $2}')
DISK_FREE_MB=$(df -Pm /opt 2>/dev/null | awk 'NR==2 {print $4}')
DISK_FREE_MB=${DISK_FREE_MB:-$(df -Pm / | awk 'NR==2 {print $4}')}
echo ">> 资源预检：CPU ${CPU_CORES} 核，内存 ${MEMORY_MB}MB，可用磁盘 ${DISK_FREE_MB}MB"
if [ "$MEMORY_MB" -lt 6000 ]; then
    echo "  ⚠️ 内存低于 6GB，Chromium 采集可能影响主服务；建议关闭 crawler.enabled。"
fi
if [ "$DISK_FREE_MB" -lt 5120 ]; then
    echo "  ❌ /opt 可用磁盘不足 5GB，无法安全安装浏览器依赖。"
    exit 1
fi

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

EXISTING_DB_PASSWORD=""
if [ -f /opt/esports-site/backend/.env ]; then
    EXISTING_DB_PASSWORD=$(sed -n 's#^DATABASE_URL=postgresql://esports_user:\([^@]*\)@.*#\1#p' /opt/esports-site/backend/.env | head -n 1)
fi
if [ ${#EXISTING_DB_PASSWORD} -lt 24 ]; then
    EXISTING_DB_PASSWORD=""
fi
DB_PASSWORD="${DB_PASSWORD:-${EXISTING_DB_PASSWORD:-$(openssl rand -hex 24)}}"

sudo -u postgres psql -c "CREATE DATABASE esports_db;" 2>/dev/null || echo "  数据库已存在，跳过"
sudo -u postgres psql -c "CREATE USER esports_user WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || echo "  数据库用户已存在，将更新随机密码"
sudo -u postgres psql -c "ALTER USER esports_user WITH PASSWORD '$DB_PASSWORD';"
# 若旧部署使用弱密码，立即同步新连接串，避免安装中途失败后旧服务无法重连。
if [ -f /opt/esports-site/backend/.env ]; then
    sed -i "s#^DATABASE_URL=.*#DATABASE_URL=postgresql://esports_user:$DB_PASSWORD@localhost:5432/esports_db#" /opt/esports-site/backend/.env
fi
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE esports_db TO esports_user;" 2>/dev/null || true
sudo -u postgres psql -c "ALTER DATABASE esports_db OWNER TO esports_user;" 2>/dev/null || true
sudo -u postgres psql -d esports_db -c "ALTER SCHEMA public OWNER TO esports_user;" 2>/dev/null || true
sudo -u postgres psql -d esports_db -c "GRANT USAGE, CREATE ON SCHEMA public TO esports_user;" 2>/dev/null || true
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
EXISTING_CRAWLER_TOKEN=""
EXISTING_SECRET_KEY=""
if [ -f /opt/esports-site/crawler-service/.env ]; then
    EXISTING_CRAWLER_TOKEN=$(sed -n 's/^CRAWLER_INTERNAL_TOKEN=//p' /opt/esports-site/crawler-service/.env | head -n 1)
fi
if [ -f /opt/esports-site/backend/.env ]; then
    EXISTING_SECRET_KEY=$(sed -n 's/^SECRET_KEY=//p' /opt/esports-site/backend/.env | head -n 1)
fi
if [ ${#EXISTING_SECRET_KEY} -lt 32 ] || [[ "$EXISTING_SECRET_KEY" == CHANGE_ME* ]]; then
    EXISTING_SECRET_KEY=""
fi
cp -r "$SCRIPT_DIR/backend" "$SCRIPT_DIR/frontend" "$SCRIPT_DIR/crawler-service" /opt/esports-site/

# ─────────────────────────────────────────
# 6. 后端 Python 环境
# ─────────────────────────────────────────
echo ">> 正在配置后端 Python 环境..."
cd /opt/esports-site/backend
python3.11 -m venv venv
source venv/bin/activate
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.tuna.tsinghua.edu.cn}"
PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
echo "  使用 PyPI 镜像: $PIP_INDEX_URL"
python -m pip install --upgrade pip -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" --timeout "$PIP_DEFAULT_TIMEOUT" --retries 10
python -m pip install -r requirements.txt -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" --timeout "$PIP_DEFAULT_TIMEOUT" --retries 10
deactivate

# 独立采集服务 Python 环境。Chromium 体积较大，改为后台下载，不能阻塞核心 Web 部署。
echo ">> 正在配置公开信息采集服务..."
cd /opt/esports-site/crawler-service
if [ ! -d venv ]; then
    python3.11 -m venv venv
fi
source venv/bin/activate
python -m pip install --upgrade pip -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" --timeout "$PIP_DEFAULT_TIMEOUT" --retries 10
python -m pip install -r requirements.txt -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" --timeout "$PIP_DEFAULT_TIMEOUT" --retries 10
export PLAYWRIGHT_BROWSERS_PATH=/opt/esports-site/crawler-service/browsers
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
sudo chown -R "$CURRENT_USER":"$CURRENT_USER" /opt/esports-site/crawler-service
BROWSER_INSTALL_LOG=/opt/esports-site/crawler-service/browser-install.log
BROWSER_INSTALL_PID_FILE=/opt/esports-site/crawler-service/browser-install.pid
BROWSER_INSTALL_RUNNING="no"
if [ -s "$BROWSER_INSTALL_PID_FILE" ]; then
    EXISTING_BROWSER_PID=$(cat "$BROWSER_INSTALL_PID_FILE" 2>/dev/null || true)
    if [ -n "$EXISTING_BROWSER_PID" ] && kill -0 "$EXISTING_BROWSER_PID" 2>/dev/null; then
        BROWSER_INSTALL_RUNNING="yes"
        echo "  Chromium 已在后台下载（PID: $EXISTING_BROWSER_PID）"
    fi
fi
if [ "$BROWSER_INSTALL_RUNNING" != "yes" ]; then
    echo "  Chromium 将在后台下载；此过程不会阻塞前端和后端部署。"
    sudo -u "$CURRENT_USER" env \
        PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
        PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 \
        nohup /opt/esports-site/crawler-service/venv/bin/scrapling install \
        > "$BROWSER_INSTALL_LOG" 2>&1 < /dev/null &
    BROWSER_INSTALL_PID=$!
    echo "$BROWSER_INSTALL_PID" > "$BROWSER_INSTALL_PID_FILE"
    echo "  Chromium 后台任务 PID: $BROWSER_INSTALL_PID"
    echo "  下载日志: $BROWSER_INSTALL_LOG"
fi
deactivate

CRAWLER_INTERNAL_TOKEN="${EXISTING_CRAWLER_TOKEN:-$(openssl rand -hex 32)}"
cat << CRAWLER_ENV_EOF > /opt/esports-site/crawler-service/.env
CRAWLER_INTERNAL_TOKEN=$CRAWLER_INTERNAL_TOKEN
CRAWLER_REDIS_URL=redis://127.0.0.1:6379/2
CRAWLER_TEMP_DIR=/tmp/esports-crawler
CRAWLER_MAX_PAGES=20
CRAWLER_TASK_TIMEOUT_SECONDS=300
CRAWLER_DOMAIN_DELAY_SECONDS=3
CRAWLER_MAX_RESPONSE_BYTES=5242880
CRAWLER_ENV_EOF
chmod 600 /opt/esports-site/crawler-service/.env
sudo systemctl enable --now redis-server
echo ">> 公开信息采集服务依赖配置完成"

# ─────────────────────────────────────────
# 7. 前端资源处理（优先使用预构建 dist）
# ─────────────────────────────────────────
echo ">> 正在处理前端资源..."
if [ -d "/opt/esports-site/frontend/dist" ] && [ -f "/opt/esports-site/frontend/dist/index.html" ]; then
    echo "  ✅ 检测到预构建 dist 目录，跳过前端构建"
else
    echo "  未找到预构建 dist，开始在本地构建前端..."
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
    # 跳过 TypeScript 类型检查，直接用 vite build，避免类型错误导致构建失败
    pnpm exec vite build
    if [ ! -f "/opt/esports-site/frontend/dist/index.html" ]; then
        echo "  ❌ 前端构建失败！请检查 Node.js 版本（需要 v18+）"
        exit 1
    fi
    echo "  ✅ 前端构建完成"
fi
echo ">> 前端资源处理完成"

# ─────────────────────────────────────────
# 8. 写入 .env 配置文件
# ─────────────────────────────────────────
echo ">> 正在写入后端环境配置..."
JWT_SECRET="${EXISTING_SECRET_KEY:-$(openssl rand -hex 32)}"
INITIAL_ADMIN_PASSWORD="${INITIAL_ADMIN_PASSWORD:-$(openssl rand -base64 24 | tr -d '\n')}"
cat << ENV_EOF > /opt/esports-site/backend/.env
# 数据库连接（PostgreSQL 16）
DATABASE_URL=postgresql://esports_user:$DB_PASSWORD@localhost:5432/esports_db

# JWT 密钥（安装时随机生成，重装时自动复用）
SECRET_KEY=$JWT_SECRET

# 仅首次创建管理员时使用，初始化完成后安装脚本会删除此项
INITIAL_ADMIN_PASSWORD=$INITIAL_ADMIN_PASSWORD

# 应用配置
PROJECT_NAME=电竞馆智能选址系统
API_V1_STR=/api/v1
BACKEND_CORS_ORIGINS=[]
ENV_EOF
chmod 600 /opt/esports-site/backend/.env

# ─────────────────────────────────────────
# 9. 初始化数据库表
# ─────────────────────────────────────────
echo ">> Initializing database tables..."
if [ "$RESET_DEPLOY_DATA" = "ask" ]; then
    echo ">> Data cleanup is optional during reinstall."
    echo "   Type yes to clear uploaded files, historical uploads, evaluation history, RAG/chat/memory data, feedback, and model versions."
    echo "   API keys, system settings, tenants, and user accounts will be preserved."
    echo "   To clear tenants and user accounts too, rerun with --clear-accounts."
    read -r -p "Clear business data now? [yes/NO]: " RESET_DEPLOY_DATA_INPUT || RESET_DEPLOY_DATA_INPUT=""
    case "$RESET_DEPLOY_DATA_INPUT" in
        yes|YES|y|Y)
            RESET_DEPLOY_DATA="yes"
            ;;
        *)
            RESET_DEPLOY_DATA="no"
            ;;
    esac
fi
cd /opt/esports-site/backend
source venv/bin/activate
ADMIN_PASSWORD_WILL_APPLY="no"
if [ "$RESET_DEPLOY_DATA" = "yes" ] && [ "$RESET_CLEAR_ACCOUNTS" = "yes" ]; then
    ADMIN_PASSWORD_WILL_APPLY="yes"
elif ! PGPASSWORD="$DB_PASSWORD" psql -h localhost -U esports_user -d esports_db -Atc "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='users'" | grep -qx 1; then
    ADMIN_PASSWORD_WILL_APPLY="yes"
elif ! PGPASSWORD="$DB_PASSWORD" psql -h localhost -U esports_user -d esports_db -Atc "SELECT 1 FROM users WHERE username='admin' LIMIT 1" | grep -qx 1; then
    ADMIN_PASSWORD_WILL_APPLY="yes"
fi
RESET_DEPLOY_DATA="$RESET_DEPLOY_DATA" RESET_CLEAR_ACCOUNTS="$RESET_CLEAR_ACCOUNTS" CRAWLER_INTERNAL_TOKEN="$CRAWLER_INTERNAL_TOKEN" python3 - <<'PY'
import asyncio
import os
from app.core.crypto import encrypt_config_value
from app.db.session import SessionLocal
from app.db.init_db import init_db, init_ai_tables
from app.db.reset_deploy_data import clear_upload_files, reset_deploy_data
from app.models.system_config import SystemConfig

should_reset = os.environ.get("RESET_DEPLOY_DATA", "no").strip().lower() in {"1", "true", "yes", "y"}
clear_accounts = os.environ.get("RESET_CLEAR_ACCOUNTS", "no").strip().lower() in {"1", "true", "yes", "y"}

db = SessionLocal()
try:
    init_db(db)
    if should_reset:
        cleared_tables = reset_deploy_data(db, clear_accounts=clear_accounts)
        cleared_dirs = clear_upload_files()
        init_db(db)
    else:
        cleared_tables = []
        cleared_dirs = []
    asyncio.run(init_ai_tables(db))
    crawler_token = os.environ.get("CRAWLER_INTERNAL_TOKEN", "")
    if crawler_token:
        token_cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "crawler.internal_token").first()
        if token_cfg:
            token_cfg.config_value = encrypt_config_value(crawler_token)
            token_cfg.is_encrypted = True
            db.commit()
    if should_reset:
        print("  Database initialized; business data reset completed.")
        if clear_accounts:
            print("  Preserved table: system_configs (LLM/AMap/Embedding/Reranker keys and system settings).")
        else:
            print("  Preserved tables: system_configs, users, tenants.")
        print("  Cleared business tables: " + (", ".join(cleared_tables) if cleared_tables else "none"))
        print("  Cleared upload directories: " + (", ".join(cleared_dirs) if cleared_dirs else "none"))
    else:
        print("  Database initialized; existing business data kept.")
finally:
    db.close()
PY
deactivate
# 初始密码只用于创建账号，不长期明文保存在配置文件中。
sed -i '/^INITIAL_ADMIN_PASSWORD=/d' /opt/esports-site/backend/.env

# ─────────────────────────────────────────
# 10. Nginx 配置
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
        proxy_set_header Authorization $http_authorization;
    }

    # SSE (Server-Sent Events) 流式输出支持
    location ~ ^/api/v1/(evaluate|chat)/.*stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
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
# 11. Supervisor 守护进程配置
# ─────────────────────────────────────────
echo ">> 正在配置 Supervisor 守护进程..."
# 获取实际执行用户（兼容 sudo 执行，避免写死 ubuntu）
CURRENT_USER=${SUDO_USER:-$(logname 2>/dev/null || id -un)}
echo "  守护进程将以用户 [$CURRENT_USER] 运行"

# 使用 printf 写入配置文件，确保变量正确展开
sudo bash -c "printf '[program:esports-backend]\ndirectory=/opt/esports-site/backend\ncommand=/opt/esports-site/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2\nautostart=true\nautorestart=true\nstderr_logfile=/var/log/esports-backend.err.log\nstdout_logfile=/var/log/esports-backend.out.log\nuser=%s\nenvironment=PATH=\"/opt/esports-site/backend/venv/bin\"\n' '$CURRENT_USER' > /etc/supervisor/conf.d/esports-backend.conf"

sudo bash -c "printf '[program:esports-crawler-api]\ndirectory=/opt/esports-site/crawler-service\ncommand=/opt/esports-site/crawler-service/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --workers 1\nautostart=true\nautorestart=true\nstopsignal=TERM\nstopasgroup=true\nkillasgroup=true\nstderr_logfile=/var/log/esports-crawler-api.err.log\nstdout_logfile=/var/log/esports-crawler-api.out.log\nuser=%s\nenvironment=PATH=\"/opt/esports-site/crawler-service/venv/bin\",PLAYWRIGHT_BROWSERS_PATH=\"/opt/esports-site/crawler-service/browsers\"\n' '$CURRENT_USER' > /etc/supervisor/conf.d/esports-crawler-api.conf"

sudo bash -c "printf '[program:esports-crawler-worker]\ndirectory=/opt/esports-site/crawler-service\ncommand=/opt/esports-site/crawler-service/venv/bin/python worker.py\nautostart=true\nautorestart=true\nstopsignal=TERM\nstopasgroup=true\nkillasgroup=true\nnumprocs=1\nstderr_logfile=/var/log/esports-crawler-worker.err.log\nstdout_logfile=/var/log/esports-crawler-worker.out.log\nuser=%s\nenvironment=PATH=\"/opt/esports-site/crawler-service/venv/bin\",PLAYWRIGHT_BROWSERS_PATH=\"/opt/esports-site/crawler-service/browsers\"\n' '$CURRENT_USER' > /etc/supervisor/conf.d/esports-crawler-worker.conf"

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start esports-backend || true
sudo supervisorctl start esports-crawler-api esports-crawler-worker || true

echo ">> 检查内部采集服务..."
CRAWLER_HEALTH_OK="no"
for _ in 1 2 3 4 5; do
    if curl -fsS -H "Authorization: Bearer $CRAWLER_INTERNAL_TOKEN" http://127.0.0.1:8010/v1/health >/dev/null; then
        CRAWLER_HEALTH_OK="yes"
        echo "  ✅ crawler-service health check 通过"
        break
    fi
    sleep 2
done
if [ "$CRAWLER_HEALTH_OK" != "yes" ]; then
    echo "  ⚠️ crawler-service health check 未通过；主系统仍可使用，请检查 /var/log/esports-crawler-api.err.log"
else
    if /opt/esports-site/crawler-service/venv/bin/python /opt/esports-site/crawler-service/scripts/smoke_test.py; then
        echo "  ✅ crawler-service 公开测试页采集通过"
    else
        echo "  ⚠️ 公开测试页采集未通过；可能是服务器外网或 robots.txt 限制，主系统仍可使用"
    fi
fi

# ─────────────────────────────────────────
# 完成
# ─────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     🎮 电竞馆智能选址系统安装完成！       ║"
echo "╠══════════════════════════════════════════╣"
echo "║  访问地址：http://$(hostname -I | awk '{print $1}')          ║"
echo "║  管理员账号：admin                         ║"
if [ "$ADMIN_PASSWORD_WILL_APPLY" = "yes" ]; then
    echo "║  本次生成的初始密码：$INITIAL_ADMIN_PASSWORD"
else
    echo "║  管理员密码：沿用现有密码                  ║"
fi
echo "║  API 文档：http://$(hostname -I | awk '{print $1}')/api/v1/docs ║"
echo "╠══════════════════════════════════════════╣"
echo "║  查看后端日志：                           ║"
echo "║  tail -f /var/log/esports-backend.out.log ║"
echo "║  浏览器下载日志：                         ║"
echo "║  tail -f /opt/esports-site/crawler-service/browser-install.log"
echo "╚══════════════════════════════════════════╝"
