#!/bin/sh
set -eu

# Cybersparker 全量恢复脚本
# 用法：bash deploy/restore.sh <备份日期戳，如 20260619_120000>
#       bash deploy/restore.sh latest  （自动选最新备份）

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

BACKUP_DIR="$PROJECT_DIR/backups"

if [ $# -lt 1 ]; then
    echo "用法: bash deploy/restore.sh <日期戳|latest>"
    echo "示例: bash deploy/restore.sh 20260619_120000"
    echo "      bash deploy/restore.sh latest"
    ls -1 "$BACKUP_DIR"/db_*.sql 2>/dev/null | head -5 || echo "  (无可用备份)"
    exit 1
fi

STAMP="$1"
if [ "$STAMP" = "latest" ]; then
    STAMP=$(ls -1 "$BACKUP_DIR"/db_*.sql 2>/dev/null | head -1 | sed 's/.*db_//' | sed 's/\.sql//')
    if [ -z "$STAMP" ]; then
        echo "错误：backups/ 目录无可用备份"
        exit 1
    fi
    echo "使用最新备份：$STAMP"
fi

DB_BACKUP="$BACKUP_DIR/db_${STAMP}.sql"
DATA_BACKUP="$BACKUP_DIR/data_${STAMP}.tar.gz"

echo "=== Cybersparker 全量恢复 ==="
echo "时间戳：$STAMP"

# 检查备份文件
if [ ! -f "$DB_BACKUP" ]; then
    echo "✗ 数据库备份不存在：$DB_BACKUP"
    exit 1
fi
if [ ! -f "$DATA_BACKUP" ]; then
    echo "✗ 数据备份不存在：$DATA_BACKUP"
    exit 1
fi

# 1. 解压数据文件
echo ""
echo "[1/3] 恢复数据文件..."
tar xzf "$DATA_BACKUP"
echo "  ✓ 数据文件已解压"

# 2. 恢复数据库
echo ""
echo "[2/3] 恢复 PostgreSQL 数据库..."
if docker compose exec -T postgres psql -U postgres cybersparker < "$DB_BACKUP" 2>/dev/null; then
    echo "  ✓ 数据库已恢复"
else
    if command -v psql >/dev/null 2>&1; then
        PGPASSWORD="${DB_PASSWORD:-nihao888}" psql -h localhost -p 5432 -U postgres cybersparker < "$DB_BACKUP"
        echo "  ✓ 数据库已恢复（宿主机 psql）"
    else
        echo "  ✗ 数据库恢复失败"
        exit 1
    fi
fi

# 3. 重新执行 migration（确保 schema 最新）
echo ""
echo "[3/3] 执行 Django migrate..."
if docker compose exec web python manage.py migrate --noinput 2>/dev/null; then
    echo "  ✓ migrate 完成"
else
    echo "  (如 web 服务未启动，请先 docker compose up -d web 然后重试 migrate)"
fi

echo ""
echo "=== 恢复完成 ==="
echo "  数据文件已恢复到项目目录"
echo "  数据库已恢复到 PostgreSQL"
echo ""
echo "下一步：docker compose up -d"
