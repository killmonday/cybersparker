# BL-DIRSCAN-004 目录扫描 Web 扫描阶段

## 做什么

实现 Phase 1 Web 扫描：aiohttp 异步 HTTP + Content-Type 预检 + 流式截断 + body 去重 + 指纹识别 + 结果写入。

## 怎么做

1. 创建 `app_cybersparker/services/dirscan_worker.py`（Web 扫描 worker）
2. 在 `app_cybersparker/tasks.py` 中添加 `run_dir_scan_task` Celery 任务
3. 在 `cybersparker/celery.py` 中添加路由

## 风险

- 中：aiohttp 异步编程 + Redis 操作
- 依赖 `Identifyner` 指纹识别器（已存在）
