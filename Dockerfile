FROM python:3.11-slim

WORKDIR /app

# 系统依赖：Chromium（Puppeteer 爬虫）、Node.js（AI PoC）、PostgreSQL 客户端（备份恢复用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    nodejs npm \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libcups2 libdrm2 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/package.json scripts/package-lock.json* scripts/
RUN cd /app/scripts && npm install

COPY . .

# 构建前端 React 产物
RUN npm config set registry https://registry.npmmirror.com
RUN npm --prefix frontend install && npm --prefix frontend run build

# 收集 Django 静态文件（含 React 构建产物）
RUN python manage.py collectstatic --noinput

# 将构建好的静态文件备份到 static_baked，运行时由 entrypoint 写入共享卷
# /app/static 在运行时会挂载 Docker 命名卷，会遮盖构建产物，
# 所以先把构建产物移到 static_baked，entrypoint 启动时再复制回卷
RUN mv /app/static /app/static_baked && mkdir -p /app/static

# 创建必要目录
RUN mkdir -p EXP_input upload_files AI_PoC error_log/celery result_spool shuffle_files

COPY deploy/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "cybersparker.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "--access-logfile", "-"]
