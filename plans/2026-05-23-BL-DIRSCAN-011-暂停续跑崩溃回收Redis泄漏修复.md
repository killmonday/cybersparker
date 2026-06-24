# BL-DIRSCAN-011 暂停续跑 + 崩溃回收 + Redis 泄漏修复

- 日期：2026-05-23
- 状态：已完成

## 验证结果

- `python manage.py check` — 0 issues
- 改动文件：4 个（dirscan_engine.py + dirscan_worker.py + dirscan_task_manage.py + apps.py）
- 文档同步：backlog 状态 → 已完成、项目控制台同步、CHANGELOG 已更新

## 做什么

修复目录扫描任务状态管理的三个缺陷：
1. 暂停后恢复从零开始（recover() 未调用 + progress_done 硬编码为 0）
2. 崩溃后状态卡在"运行中"（僵尸回收遗漏 DirScanTask + heartbeat 不更新）
3. Redis key 泄漏（暂停→停止、暂停→重跑、崩溃回收三条路径无清理）

## 修改文件

1. `app_cybersparker/services/dirscan_engine.py` — 提取 `cleanup_task_redis(task_id)` 独立函数
2. `app_cybersparker/services/dirscan_worker.py` — recover() + progress_done + heartbeat
3. `app_cybersparker/views/expload/dirscan_task_manage.py` — stop/rerun/start 时清理 Redis
4. `app_cybersparker/apps.py` — 僵尸回收增加 DirScanTask + Redis 清理

## 验证

- `python manage.py check` 0 issues
- 代码 review：每处修改逐一对照验收条件
