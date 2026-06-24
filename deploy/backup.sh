#!/bin/sh
set -eu

# Cybersparker 全量备份脚本
# 用法：bash deploy/backup.sh
# 输出：backups/db_YYYYMMDD_HHMMSS.sql + backups/data_YYYYMMDD_HHMMSS.tar.gz

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"

DB_BACKUP="$BACKUP_DIR/db_${DATE}.sql"
DATA_BACKUP="$BACKUP_DIR/data_${DATE}.tar.gz"

echo "=== Cybersparker 全量备份 ==="
echo "时间：$(date '+%Y-%m-%d %H:%M:%S')"

# 1. 数据库备份
echo ""
echo "[1/2] 备份 PostgreSQL 数据库..."
if docker compose exec -T postgres pg_dump -U postgres cybersparker > "$DB_BACKUP" 2>/dev/null; then
    DB_SIZE=$(wc -c < "$DB_BACKUP" | numfmt --to=iec 2>/dev/null || wc -c < "$DB_BACKUP")
    echo "  ✓ 数据库已导出：$DB_BACKUP ($DB_SIZE)"
else
    # 回退：直接用宿主机 pg_dump
    if command -v pg_dump >/dev/null 2>&1; then
        PGPASSWORD="${DB_PASSWORD:-nihao888}" pg_dump -h localhost -p 5432 -U postgres cybersparker > "$DB_BACKUP"
        echo "  ✓ 数据库已导出（宿主机 pg_dump）：$DB_BACKUP"
    else
        echo "  ✗ 数据库备份失败：Docker 和宿主机均无可用 pg_dump"
        exit 1
    fi
fi

# 2. 数据文件备份
echo ""
echo "[2/2] 打包数据文件..."
tar czf "$DATA_BACKUP" \
    EXP_input \
    EXP_plugin \
    upload_files \
    db \
    2>/dev/null

DATA_SIZE=$(wc -c < "$DATA_BACKUP" | numfmt --to=iec 2>/dev/null || wc -c < "$DATA_BACKUP")

# 清理超过 7 天的旧备份
find "$BACKUP_DIR" -name "db_*.sql" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "data_*.tar.gz" -mtime +7 -delete 2>/dev/null || true

echo "  ✓ 数据已打包：$DATA_BACKUP ($DATA_SIZE)"

echo ""
echo "=== 备份完成 ==="
echo "  数据库: $DB_BACKUP"
echo "  数据文件: $DATA_BACKUP"
echo ""
echo "迁移到新 VPS："
echo "  1. 将 backups/ 目录拷贝到新 VPS 项目根目录"
echo "  2. 在新 VPS 执行：bash deploy/restore.sh $DATE"
