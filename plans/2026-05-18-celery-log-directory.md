# Celery 日志目录接入

- 日期：2026-05-18
- 状态：已完成

## 做什么

把 Celery worker 日志同步写入专门目录，便于后续排查自动扫描、writer、数据库连接异常。

## 为什么

- 当前 Celery 主要把日志打到终端，历史日志不易留存。
- 本次会话已经多次依赖 Celery 日志定位问题，需要稳定的落盘日志。

## 已执行改动

- 新增 `start_celery.sh`
  - 本地直接执行时，将日志写入 `error_log/celery/worker.log`
  - 同时保留终端输出
- 更新 `docker-compose.yml` 的 `worker.command`
  - 启动前自动创建 `/app/error_log/celery`
  - Celery 输出通过 `tee -a /app/error_log/celery/worker.log` 同步落盘

## 验证

- `sh -n start_celery.sh`：通过
- `docker-compose.yml` 已包含 `/app/error_log/celery/worker.log` 和 `tee -a`
