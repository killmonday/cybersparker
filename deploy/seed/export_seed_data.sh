#!/usr/bin/env bash
# ============================================================
# 种子数据导出脚本
# 用法：bash deploy/seed/export_seed_data.sh
#
# 从开发环境 PostgreSQL 导出参考数据（指纹/PoC/标签等 9 张表）
# 输出：deploy/seed/seed_data.sql
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="${SCRIPT_DIR}/seed_data.sql"

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-nihao888}"
DB_NAME="${DB_NAME:-cybersparker}"

# 要导出的 9 张参考数据表
TABLES=(
    app_cybersparker_fingerprint
    app_cybersparker_exp
    app_cybersparker_exp_relate_fingerprint
    app_cybersparker_tag
    app_cybersparker_exp_tags
    app_cybersparker_cveextensions
    app_cybersparker_dirscandictgroup
    app_cybersparker_dirscandict
    app_cybersparker_dirscandict_groups
)

echo "导出种子数据..."
echo "  来源: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "  输出: ${OUTPUT}"
echo ""

# 生成表头注释
GENERATED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
cat > "${OUTPUT}" <<HEADER
-- ============================================================
-- Cybersparker 种子数据（Docker 部署用）
-- ============================================================
-- 生成时间：${GENERATED_AT}
-- 来源：开发环境 PostgreSQL 参考数据
--
-- 包含的表及行数：
HEADER

# 先统计每张表的行数
for table in "${TABLES[@]}"; do
    COUNT=$(PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tA -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null || echo "?")
    printf -- "--   %-50s %s\n" "${table}" "${COUNT}" >> "${OUTPUT}"
done

cat >> "${OUTPUT}" << 'HEADER'
--
-- Docker 启动时自动创建（无需导入）：
--   auth_user / user_profile — migration 0073 自动创建 admin/admin
--   assetzone（公网）        — migration 0075 自动创建 code=public
--
-- 不包含（需部署后手动配置）：
--   代理配置、测绘引擎密钥、AI 模型密钥、ceye 配置
--   所有运行时数据（任务/结果/资产/文件托管等）
--
-- 导入命令（必须先 migrate 创建表结构，再导入数据）：
--   docker compose exec -T postgres psql -U postgres cybersparker < deploy/seed/seed_data.sql
-- ============================================================
HEADER

# 导出数据
PGPASSWORD="${DB_PASS}" pg_dump \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
    --data-only --no-comments \
    $(for t in "${TABLES[@]}"; do echo "-t ${t}"; done) \
    --rows-per-insert=1000 \
    >> "${OUTPUT}"

SIZE=$(du -h "${OUTPUT}" | cut -f1)
echo "完成: ${OUTPUT} (${SIZE})"
echo ""
echo "验证："
for table in "${TABLES[@]}"; do
    COUNT=$(PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tA -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null || echo "?")
    printf "  %-50s %s 行\n" "${table}" "${COUNT}"
done
