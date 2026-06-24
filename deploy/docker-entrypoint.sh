#!/bin/sh
set -e

# 首次运行时，将构建好的静态文件从 static_baked 复制到共享卷 /app/static
if [ ! -f /app/static/.populated ]; then
    echo "[entrypoint] populating static files to shared volume..."
    if [ -d /app/static_baked ]; then
        cp -r /app/static_baked/* /app/static/
    fi
    touch /app/static/.populated
    echo "[entrypoint] static files populated"
fi

echo "[entrypoint] running django migrations..."
python manage.py migrate --noinput

# ---- 种子数据导入（仅首次部署时执行）----
SEED_FILE="/app/deploy/seed/seed_data.sql"
if [ -f "$SEED_FILE" ]; then
    # 用 fingerprint 表是否为空来判断是否需要导入种子数据
    DB_PASS="${DB_PASSWORD:-nihao888}"
    FINGERPRINT_COUNT=$(PGPASSWORD="$DB_PASS" psql -h postgres -U postgres -d cybersparker -tA -c "SELECT COUNT(*) FROM app_cybersparker_fingerprint;" 2>/dev/null || echo "0")
    if [ "$FINGERPRINT_COUNT" -eq 0 ] 2>/dev/null; then
        echo "[entrypoint] importing seed data (fingerprint table is empty)..."
        if PGPASSWORD="$DB_PASS" psql -h postgres -U postgres cybersparker < "$SEED_FILE" 2>&1; then
            echo "[entrypoint] seed data imported successfully"
        else
            echo "[entrypoint] WARNING: seed data import failed (non-fatal, continuing)"
        fi
    else
        echo "[entrypoint] seed data already present (fingerprint count=$FINGERPRINT_COUNT), skipping import"
    fi
else
    echo "[entrypoint] seed file not found at $SEED_FILE, skipping import"
fi

echo "[entrypoint] starting: $@"
exec "$@"
