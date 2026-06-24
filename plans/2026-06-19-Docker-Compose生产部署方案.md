# Docker Compose 生产部署方案

> 2026-06-19 | 状态：已完成

## 现状问题

| 问题 | 现有 | 影响 |
|------|------|------|
| 无 PostgreSQL 服务 | compose 只有 redis + web + worker | 需要外部手工装 PG，无法一键部署 |
| Python 3.9 | Dockerfile `FROM python:3.9.6` | 项目文档要求 3.11+ |
| 无 Beat 服务 | compose 无 beat | 定时清理任务不会执行 |
| 无 Nginx | compose 无 nginx | 生产需要 Nginx 提供 React 壳页 + 反代 API |
| 无 fd limits 调优 | 未配置 | 大量网络扫描时 fd 不够用 |
| 两个 CMD | Dockerfile 最后两行都是 CMD | 只有最后一条生效 |
| Volume 缺失 | 缺少 upload_files/ AI_PoC/ db/ | 重启丢数据 |
| compose v2 格式 | `version: '2'` | 不支持现代特性 |
| 无备份迁移工具 | 不存在 | 迁移 VPS 靠手工 |

## 方案设计

### 1. Docker Compose 服务编排

```
┌──────────────────────────────────────────────┐
│                  Nginx :80                    │
│   React 壳页 + /api/* → Django :8000         │
│   /files/* → Django :8000                     │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│              Django Web :8000                  │
│   manage.py runserver（或 gunicorn）          │
└──────┬──────────────┬──────────────┬─────────┘
       │              │              │
   ┌───┴───┐    ┌─────┴─────┐  ┌────┴─────┐
   │ Redis │    │PostgreSQL │  │ Celery   │
   │ :6379 │    │   :5432   │  │ Worker   │
   └───────┘    └───────────┘  │ + Beat   │
                               └──────────┘
```

6 个服务：nginx、web、worker、beat、redis、postgres

### 2. 文件描述符限制调优

- `/etc/security/limits.conf` 风格的无用（容器内不读这个）
- Docker Compose `ulimits` 直接生效：
  - `nofile: soft=65535 hard=1048576`
- 容器内 `ulimit -n` 启动前设到 65535
- 影响服务：web、worker（worker 做大量网络扫描）

### 3. 数据目录与卷挂载

| 目录 | 内容 | 需备份 | 说明 |
|------|------|:---:|------|
| `EXP_input/` | 用户上传的任务目标文件 | ✓ | 任务输入 |
| `EXP_plugin/` | 用户保存的 POC 插件 | ✓ | 核心资产 |
| `upload_files/` | 文件托管上传的文件 | ✓ | 公开/鉴权下载 |
| `AI_PoC/` | AI 生成 PoC 的任务资料 | ✗ | 临时资料可重建 |
| `error_log/` | 运行日志 | ✗ | 运维排查用 |
| `db/` | qqwry.dat IP 库 | ✓ | 需重新下载也可 |

### 4. 数据库备份与迁移

**备份（pg_dump）**：
```bash
docker compose exec postgres pg_dump -U postgres cybersparker > backup.sql
```

**恢复（pg_restore / psql）**：
```bash
docker compose exec -T postgres psql -U postgres cybersparker < backup.sql
```

**定时备份**：crontab 每日凌晨执行 pg_dump，保留最近 7 天

### 5. 全量迁移脚本

`deploy/backup.sh`：
1. pg_dump 导出数据库 → `backups/db_YYYYMMDD.sql`
2. tar 打包数据目录（EXP_input/ EXP_plugin/ upload_files/ db/）→ `backups/data_YYYYMMDD.tar.gz`
3. 输出一句话：备份文件在哪、大小

`deploy/restore.sh`：
1. 从 tar.gz 解压数据目录
2. psql 导入 SQL 到 PostgreSQL
3. Django migrate 确保 migration 最新

### 6. 不做

- 不预设 CI/CD 流水线（用户手工 git pull + docker compose up -d --build）
- 不做数据库主从/读写分离
- 不做 HTTPS（用户自行在前面挂 Nginx/Caddy 反代加证书）
- 不做健康检查自动重启（依赖 Docker 自带 restart: unless-stopped）

## 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `Dockerfile` | 重写 | Python 3.11、删双 CMD、加 start script |
| `docker-compose.yml` | 重写 | 6 服务、volumes、ulimits |
| `deploy/nginx/default.conf` | 新建 | Nginx 反代 + React 壳页 |
| `deploy/backup.sh` | 新建 | 全量备份脚本 |
| `deploy/restore.sh` | 新建 | 全量恢复脚本 |
| `deploy/docker-entrypoint.sh` | 新建 | 容器启动入口（migrate + collectstatic） |
| `docs/项目控制台.md` | 更新 | 加 BL-DEPLOY-002 |
| `docs/设计总览.md` | 更新 | 加 DD-017 部署架构决策 |
| `docs/项目启动文档.md` | 更新 | Docker Compose 部署章节更新 |

## 待确认

1. Web 服务用 gunicorn 还是 Django runserver？（生产推荐 gunicorn）
2. PostgreSQL 数据要不要挂载到宿主机指定目录？还是用 Docker named volume？
3. 备份脚本要不要加密？（如 gpg 加密 pg_dump 输出）
