#!/usr/bin/env bash
# ============================================================
# PostgreSQL 15 → 17 迁移脚本
# 用法：以 root 执行  bash deploy/migrate-pg15-to-pg17.sh
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

DB_PORT="5433"
DB_NAME="cybersparker"
DB_USER="postgres"
DB_PASS="nihao888"
BACKUP_FILE="/tmp/cybersparker_pg15_backup.dump"

echo "============================================"
echo " PostgreSQL 15 → 17 迁移"
echo " 数据库: ${DB_NAME}"
echo " 端口: ${DB_PORT}"
echo "============================================"

# ============================================================
# 1. 备份 PG15 数据
# ============================================================
echo ""
echo "[1/8] 备份 PG15 数据库..."

if pg_isready -p "${DB_PORT}" &>/dev/null; then
    PGPASSWORD="${DB_PASS}" pg_dump -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" \
        -d "${DB_NAME}" -Fc -f "${BACKUP_FILE}"
    log "备份完成: $(ls -lh ${BACKUP_FILE} | awk '{print $5}')"
else
    warn "PG15 未运行，使用已有的 /tmp/cybersparker_backup_20260608.dump"
    BACKUP_FILE="/tmp/cybersparker_backup_20260608.dump"
    if [ ! -f "${BACKUP_FILE}" ]; then
        err "未找到备份文件，请先启动 PG15 再做备份"
    fi
    log "使用已有备份: $(ls -lh ${BACKUP_FILE} | awk '{print $5}')"
fi

# ============================================================
# 2. 停止并卸载 PG15
# ============================================================
echo ""
echo "[2/8] 卸载 PostgreSQL 15..."

pg_ctlcluster 15 main stop 2>/dev/null || true
apt-get purge -y -qq postgresql-15 postgresql-client-15 postgresql-server-dev-15 2>/dev/null || true
apt-get autoremove -y -qq 2>/dev/null || true
log "PostgreSQL 15 已卸载"

# ============================================================
# 3. 添加 PostgreSQL 官方 apt 源
# ============================================================
echo ""
echo "[3/8] 配置 PostgreSQL apt 源..."

PGDG_SOURCE="/etc/apt/sources.list.d/pgdg.sources"

if [ -f "${PGDG_SOURCE}" ]; then
    warn "PGDG 源已存在，跳过"
else
    curl -sS https://www.postgresql.org/media/keys/ACCC4CF8.asc | \
        gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > "${PGDG_SOURCE}"
    apt-get update -qq
    log "PGDG 源已添加"
fi

# ============================================================
# 4. 安装 PostgreSQL 17
# ============================================================
echo ""
echo "[4/8] 安装 PostgreSQL 17..."

apt-get install -y -qq postgresql-17 postgresql-client-17 postgresql-server-dev-17
log "PostgreSQL 17 已安装"

# ============================================================
# 5. 编译安装 pg_bigm（PGDG 无预编译包，需源码编译）
# ============================================================
echo ""
echo "[5/8] 编译安装 pg_bigm..."

apt-get install -y -qq git make gcc

PG_BIGM_TMP="/tmp/pg_bigm_build"
if [ -d "${PG_BIGM_TMP}" ]; then rm -rf "${PG_BIGM_TMP}"; fi

git clone --depth 1 https://github.com/pgbigm/pg_bigm.git "${PG_BIGM_TMP}" 2>/dev/null
cd "${PG_BIGM_TMP}"
USE_PGXS=1 make -s 2>&1 | tail -3
USE_PGXS=1 make -s install 2>&1 | tail -3
cd /
rm -rf "${PG_BIGM_TMP}"

# 验证 .so 文件已安装
if [ -f "/usr/lib/postgresql/17/lib/pg_bigm.so" ]; then
    log "pg_bigm 编译安装完成"
else
    err "pg_bigm 编译失败，请检查 postgresql-server-dev-17 是否安装"
fi

# ============================================================
# 6. 配置 PG17（端口 5433）并启动
# ============================================================
echo ""
echo "[6/8] 配置 PostgreSQL 17..."

PG_CONF="/etc/postgresql/17/main/postgresql.conf"
if grep -q "^port = 5432" "${PG_CONF}"; then
    sed -i "s/^port = 5432/port = ${DB_PORT}/" "${PG_CONF}"
fi

pg_ctlcluster 17 main start 2>/dev/null || true

for i in $(seq 1 10); do
    if pg_isready -p "${DB_PORT}" &>/dev/null; then
        break
    fi
    sleep 1
done

if ! pg_isready -p "${DB_PORT}" &>/dev/null; then
    err "PostgreSQL 17 启动失败"
fi
log "PostgreSQL 17 已启动（端口 ${DB_PORT}）"

# ============================================================
# 7. 创建数据库和扩展
# ============================================================
echo ""
echo "[7/8] 创建数据库和扩展..."

# 设置 postgres 用户密码
su - postgres -c "psql -p ${DB_PORT} -c \"ALTER USER ${DB_USER} PASSWORD '${DB_PASS}';\"" 2>/dev/null || true

# 创建数据库
su - postgres -c "psql -p ${DB_PORT} -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" 2>/dev/null | grep -q 1 || psql -p ${DB_PORT} -c \"CREATE DATABASE ${DB_NAME};\"" 2>/dev/null

log "数据库 ${DB_NAME} 已就绪"

# 创建扩展（pg_trgm 是 PG 自带；pg_bigm 已编译安装）
PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
SQL

# 验证扩展
EXT_LIST=$(PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tAc "SELECT string_agg(extname, ', ' ORDER BY extname) FROM pg_extension")
log "已安装扩展: ${EXT_LIST}"

# ============================================================
# 8. 恢复数据 + 运行迁移
# ============================================================
echo ""
echo "[8/8] 恢复数据..."

PGPASSWORD="${DB_PASS}" pg_restore -h 127.0.0.1 -p "${DB_PORT}" -U "${DB_USER}" \
    -d "${DB_NAME}" --no-owner --no-privileges -j 4 "${BACKUP_FILE}" 2>&1 | tail -5

log "数据恢复完成"

# 运行 Django 迁移（创建 bigm/trigram/tsvector 索引等）
cd /workspaces/cybersparker
python manage.py migrate --no-input 2>&1 | tail -5
log "Django 迁移完成"

# ============================================================
# 完成
# ============================================================
echo ""
echo "============================================"
echo " 迁移完成"
echo "============================================"
echo ""
echo "  PostgreSQL: 17 (端口 ${DB_PORT})"
echo "  扩展: ${EXT_LIST}"
echo "  数据库: ${DB_NAME}"
echo ""
echo "  验证:"
echo "    PGPASSWORD=${DB_PASS} psql -h 127.0.0.1 -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME} -c 'SELECT extname FROM pg_extension;'"
echo ""
