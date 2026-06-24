#!/usr/bin/env bash
# ============================================================
# Cybersparker 环境安装脚本
# 适用：Debian 12 x86_64 容器 / 虚拟机
# 用法：bash deploy/setup-env.sh
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

# ---- 可配置项 ----
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-cybersparker}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-nihao888}"
REDIS_PORT="${REDIS_PORT:-6379}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "============================================"
echo " Cybersparker 环境安装"
echo " 数据库: ${DB_USER}@localhost:${DB_PORT}/${DB_NAME}"
echo " Redis:  localhost:${REDIS_PORT}"
echo " 项目目录: ${PROJECT_DIR}"
echo "============================================"

# ============================================================
# 1. 修复 apt 源（容器环境常见问题：多源冲突）
# ============================================================
echo ""
echo "[1/8] 修复 apt 源..."

# 容器环境可能出现 deb822 和 sources.list 双源，导致 502/签名错误
if [ -f /etc/apt/sources.list.d/debian.sources ]; then
    mv /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/debian.sources.bak 2>/dev/null || true
    warn "已禁用 /etc/apt/sources.list.d/debian.sources（避免和 sources.list 冲突）"
fi

# nodesource 源在容器中可能 TLS 握手失败
if [ -f /etc/apt/sources.list.d/nodesource.sources ]; then
    mv /etc/apt/sources.list.d/nodesource.sources /etc/apt/sources.list.d/nodesource.sources.bak 2>/dev/null || true
    warn "已禁用 nodesource.sources（容器 TLS 兼容问题）"
fi

apt-get update -qq
log "apt 源已就绪"

# ============================================================
# 2. 安装并启动 PostgreSQL 17
# ============================================================
echo ""
echo "[2/8] 安装 PostgreSQL 17..."

# —— 检查 PG17 包是否已安装 ——
PG_INSTALLED=false
if dpkg -l postgresql-17 2>/dev/null | grep -q '^ii'; then
    PG_INSTALLED=true
fi

if $PG_INSTALLED; then
    log "PostgreSQL 17 已安装，跳过 apt install"
else
    # 添加 PostgreSQL 官方 apt 源
    PGDG_LIST="/etc/apt/sources.list.d/pgdg.list"

    if [ ! -f "$PGDG_LIST" ]; then
        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
            | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg

        echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] \
    https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
            > "$PGDG_LIST"

        apt-get update -qq
    fi

    apt-get install -y -qq postgresql-17 postgresql-client-17 postgresql-server-dev-17
    log "PostgreSQL 17 安装完成"
fi

# —— 配置端口（首次安装后或端口未改时生效） ——
PG_CONF="/etc/postgresql/17/main/postgresql.conf"
if [ -f "${PG_CONF}" ] && grep -q "^port = 5432" "${PG_CONF}"; then
    sed -i "s/^port = 5432/port = ${DB_PORT}/" "${PG_CONF}"
    log "端口已配置为 ${DB_PORT}，需要重启生效"
    PG_NEED_RESTART=true
else
    PG_NEED_RESTART=false
fi

# # —— 配置 data_directory（统一到项目目录 ./pgdata，与生产 Docker 挂载路径对齐） ——
# CURRENT_DATA_DIR=$(grep "^data_directory" "${PG_CONF}" 2>/dev/null | grep -o "'[^']*'" | tr -d "'" || echo "")
# TARGET_DATA_DIR="${PROJECT_DIR}/pgdata"

# if [ "${CURRENT_DATA_DIR}" != "${TARGET_DATA_DIR}" ]; then
#     log "将 PostgreSQL 数据目录迁移到 ${TARGET_DATA_DIR} ..."

#     # 停止 PG 以便迁移数据
#     if pg_isready -p "${DB_PORT}" &>/dev/null; then
#         pg_ctlcluster 17 main stop 2>/dev/null || true
#         sleep 1
#     fi

#     # 迁移或初始化数据目录
#     if [ -d "${CURRENT_DATA_DIR}" ] && [ ! -d "${TARGET_DATA_DIR}" ]; then
#         mv "${CURRENT_DATA_DIR}" "${TARGET_DATA_DIR}"
#         log "数据已从 ${CURRENT_DATA_DIR} 迁移到 ${TARGET_DATA_DIR}"
#     elif [ ! -d "${TARGET_DATA_DIR}" ]; then
#         mkdir -p "${TARGET_DATA_DIR}"
#         chown postgres:postgres "${TARGET_DATA_DIR}"
#         su - postgres -c "pg_ctl init -D ${TARGET_DATA_DIR}" 2>/dev/null || \
#             su - postgres -c "/usr/lib/postgresql/17/bin/initdb -D ${TARGET_DATA_DIR}" 2>/dev/null || true
#         log "已在 ${TARGET_DATA_DIR} 初始化新的 PostgreSQL 数据目录"
#     else
#         log "${TARGET_DATA_DIR} 已存在，跳过数据迁移"
#     fi

#     # 更新 postgresql.conf
#     if grep -q "^data_directory" "${PG_CONF}"; then
#         sed -i "s|^data_directory.*|data_directory = '${TARGET_DATA_DIR}'|" "${PG_CONF}"
#     else
#         echo "data_directory = '${TARGET_DATA_DIR}'" >> "${PG_CONF}"
#     fi
#     log "data_directory 已配置为 ${TARGET_DATA_DIR}"

#     PG_NEED_RESTART=true
# fi

# —— 启动 PostgreSQL ——
if pg_isready -p "${DB_PORT}" &>/dev/null; then
    if $PG_NEED_RESTART; then
        log "重启 PostgreSQL 使配置生效..."
        pg_ctlcluster 17 main restart 2>/dev/null || true
        sleep 1
    else
        log "PostgreSQL 已在运行（端口 ${DB_PORT}），跳过启动"
    fi
else
    pg_ctlcluster 17 main start 2>/dev/null || true

    for i in $(seq 1 10); do
        if pg_isready -p "${DB_PORT}" &>/dev/null; then
            break
        fi
        sleep 1
    done

    if ! pg_isready -p "${DB_PORT}" &>/dev/null; then
        err "PostgreSQL 启动失败（端口 ${DB_PORT}）"
    fi
    log "PostgreSQL 17 已启动（端口 ${DB_PORT}）"
fi

# —— 创建用户密码和数据库（幂等） ——
su - postgres -c "psql -p ${DB_PORT} -c \"ALTER USER ${DB_USER} PASSWORD '${DB_PASS}';\"" 2>/dev/null || true
su - postgres -c "psql -p ${DB_PORT} -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" 2>/dev/null | grep -q 1 || psql -p ${DB_PORT} -c \"CREATE DATABASE ${DB_NAME};\"" 2>/dev/null

# 验证
if PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT 1;" &>/dev/null; then
    log "数据库连接验证通过（${DB_USER}@127.0.0.1:${DB_PORT}/${DB_NAME}）"
else
    err "数据库连接失败，请检查 PostgreSQL 状态和密码"
fi

# —— pg_bigm 扩展（中文全文检索必需） ——
PG_BIGM_SO="/usr/lib/postgresql/17/lib/pg_bigm.so"
PG_BIGM_SQL="SELECT 1 FROM pg_extension WHERE extname='pg_bigm'"

# 检查 .so 文件是否已编译安装
if [ -f "${PG_BIGM_SO}" ]; then
    warn "pg_bigm 已编译，跳过编译"
else
    log "编译安装 pg_bigm..."
    apt-get install -y -qq postgresql-server-dev-17 git make gcc 2>/dev/null || true

    PG_BIGM_TMP="/tmp/pg_bigm_build_$$"
    git clone --depth 1 https://github.com/pgbigm/pg_bigm.git "${PG_BIGM_TMP}" || echo "maybe network error, use this command set git proxy: git config --global https.proxy http://192.168.x.x:7890"
    cd "${PG_BIGM_TMP}"
    USE_PGXS=1 make -s 2>&1 | tail -3
    USE_PGXS=1 make -s install 2>&1 | tail -3
    cd /
    rm -rf "${PG_BIGM_TMP}"
    log "pg_bigm 编译安装完成"
fi

# 检查扩展是否已在数据库中创建
PG_BIGM_INSTALLED=$(PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tAc "${PG_BIGM_SQL}" 2>/dev/null || echo "")

if [ "${PG_BIGM_INSTALLED}" = "1" ]; then
    warn "pg_bigm 扩展已创建，跳过"
else
    PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -c "CREATE EXTENSION IF NOT EXISTS pg_bigm;" 2>/dev/null

    VERIFY=$(PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tAc "${PG_BIGM_SQL}" 2>/dev/null || echo "")
    if [ "${VERIFY}" = "1" ]; then
        log "pg_bigm 扩展已创建"
    else
        warn "pg_bigm 扩展创建失败，中文全文检索将回退为顺序扫描（不影响功能但较慢）"
    fi
fi

# —— db.SQL 数据导入 ——
# DB_SQL="${PROJECT_DIR}/db.SQL"
# if [ -f "${DB_SQL}" ]; then
#     log "发现 db.SQL，开始导入数据..."
#     PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DB_SQL}" 2>&1 | tail -5
#     log "db.SQL 导入完成"
# else
#     warn "未找到 db.SQL，跳过数据导入（全新空库）"
# fi

# ============================================================
# 3. 安装并启动 Redis
# ============================================================
echo ""
echo "[3/8] 安装 Redis..."

if command -v redis-cli &>/dev/null && redis-cli -p "${REDIS_PORT}" ping &>/dev/null; then
    warn "Redis 已在运行（端口 ${REDIS_PORT}），跳过安装"
else
    apt-get install -y -qq redis-server

    # 启动
    redis-server --daemonize yes --port "${REDIS_PORT}" 2>/dev/null || true

    if redis-cli -p "${REDIS_PORT}" ping &>/dev/null; then
        log "Redis 7 已安装并启动（端口 ${REDIS_PORT}）"
    else
        err "Redis 启动失败"
    fi
fi

# ============================================================
# 4. 安装 Chromium 浏览器（AI PoC URL 爬取用）
# ============================================================
echo ""
echo "[4/8] 安装 Chromium..."

if command -v chromium &>/dev/null && chromium --version &>/dev/null; then
    warn "Chromium 已安装（$(chromium --version 2>&1)），跳过"
else
    apt-get install -y -qq chromium chromium-driver
    log "Chromium 已安装（$(chromium --version 2>&1)）"
fi

# 安装 Puppeteer 所需系统库
apt-get install -y -qq \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libasound2 2>/dev/null || true

# ============================================================
# 5. 安装 Node.js 依赖（Puppeteer + Turndown）
# ============================================================
echo ""
echo "[5/8] 安装 Node.js 依赖..."

SCRIPTS_DIR="${PROJECT_DIR}/scripts"
if [ -f "${SCRIPTS_DIR}/package.json" ]; then
    cd "${SCRIPTS_DIR}"
    if [ -d node_modules ]; then
        warn "node_modules 已存在，跳过 npm install（如需重装请先 rm -rf scripts/node_modules）"
    else
        npm install --no-audit --no-fund 2>&1 | tail -3
    fi
    cd "${PROJECT_DIR}"

    # 快速验证 Chromium + Puppeteer
    if node -e "
        const p = require('${SCRIPTS_DIR}/node_modules/puppeteer');
        p.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-setuid-sandbox']})
         .then(b => b.version().then(v => {console.log(v); return b.close()}))
         .catch(e => {console.error('FAIL:', e.message); process.exit(1)})
    " 2>/dev/null; then
        log "Chromium + Puppeteer 验证通过"
    else
        warn "Chromium + Puppeteer 验证失败，AI PoC 爬取可能不可用"
    fi
else
    warn "scripts/package.json 不存在，跳过 Node.js 依赖安装"
fi

# ============================================================
# 6. 修复 git 跨平台权限问题
# ============================================================
echo ""
echo "[6/8] 修复 git 文件权限追踪..."

git config core.filemode false
git update-index --refresh 2>/dev/null || true
log "git core.filemode=false 已设置（避免 Windows/Docker 权限变更产生假 diff）"

# ============================================================
# 7. 安装并配置 Nginx
# ============================================================
echo ""
echo "[7/8] 安装 Nginx..."

NGINX_CONF_SRC="${PROJECT_DIR}/deploy/nginx/react-shell.conf"
NGINX_CONF_DST="/etc/nginx/sites-available/react-shell"

if command -v nginx &>/dev/null && nginx -t &>/dev/null; then
    warn "Nginx 已安装，跳过安装"
else
    apt-get install -y -qq nginx
    log "Nginx 已安装"
fi

# 部署站点配置（每次执行都更新，确保路径正确）
if [ -f "${NGINX_CONF_SRC}" ]; then
    # 替换配置文件中的项目路径占位符
    sed "s|/workspaces/cybersparker|${PROJECT_DIR}|g" "${NGINX_CONF_SRC}" > "${NGINX_CONF_DST}"
    ln -sf "${NGINX_CONF_DST}" /etc/nginx/sites-enabled/react-shell
    rm -f /etc/nginx/sites-enabled/default

    if nginx -t 2>/dev/null; then
        # 如果 nginx 已在运行，reload；否则启动
        if pgrep nginx &>/dev/null; then
            nginx -s reload 2>/dev/null || true
        else
            nginx 2>/dev/null || true
        fi
        log "Nginx 站点已部署并启动（端口 28600）"
    else
        warn "Nginx 配置语法有误，请检查 ${NGINX_CONF_DST}"
    fi
else
    warn "${NGINX_CONF_SRC} 不存在，跳过 Nginx 站点配置"
fi

# ============================================================
# 8. 安装 Python 依赖（可选，需确认）
# ============================================================
echo ""
echo "[8/8] Python 依赖..."

REQ_FILE="${PROJECT_DIR}/requirements.txt"
if [ -f "${REQ_FILE}" ]; then
    pip install -r ${REQ_FILE}
    python manage.py migrate
else
    warn "requirements.txt 不存在，跳过"
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo "============================================"
echo " 环境安装完成"
echo "============================================"
echo ""
echo "  PostgreSQL : localhost:${DB_PORT}/${DB_NAME}"
echo "  Redis      : localhost:${REDIS_PORT}"
echo "  Nginx      : port 28600"
echo "  Chromium   : $(chromium --version 2>&1 || echo '未安装')"
echo "  Node.js    : $(node --version 2>/dev/null || echo '未安装')"
echo ""
echo "  Nginx 已配置："
echo "    /react-shell/*  → React 编译产物（生产模式）"
echo "    /api/*           → Django :8999"
echo "    /login /logout   → Django :8999"
echo ""
echo "  普通用户身份启动 Django 开发服务："
echo "    cd ${PROJECT_DIR}"
echo "    pip install -r requirements.txt"
echo "    python manage.py runserver 0.0.0.0:8999"
echo ""
# echo "  启动 Celery Worker（单独终端）："
# echo "    celery -A cybersparker worker -Q auto_scan,batch_scan,result_writer,maintenance,dir_scan,poc_generation -l INFO"
# echo ""
echo "  普通用户身份启动 Celery Worker："
echo "    ./start_celery.sh"
# echo ""
echo "  root启动 redis（已启动）："
echo "    redis-server --port 6379 --daemonize yes"
echo ""
echo "  root启动 nginx（已启动）:"
echo "    nginx"