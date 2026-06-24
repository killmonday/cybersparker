# 批量任务协程模式暂停失效修复

- 状态：已完成
- 关联 Backlog：BL-BATCH-010, BL-BATCH-011
- 关联模块：docs/modules/02-任务执行模块.md

## 做什么

修复批量任务在协程模式（run_mode=2）下暂停后状态显示"完成"、进度 100%、无续跑按钮的 bug。

## 为什么

`ProcessTaskKiller` 类没有从子进程回传 `pause_requested` / `stop_requested` 属性，导致 `tasks.py` 的 `_run_batch_scan_task` 在判定终态时永远走到 `"success"` 分支，CAS 将状态写成 `status=1`（完成）。

## 怎么做

1. `ProcessTaskKiller` 新增 `pause_requested` / `stop_requested` 属性，通过 `multiprocessing.Value` 从 gevent 子进程回传
2. `startTask()` 协程路径创建 shared Value 并传给两方
3. `run_gevent_task_in_subprocess` 子进程退出前写入状态
4. `Task_handler.run()` finally 块去掉 `dispatch_token is None` 条件，作为 CAS 路径的兜底

## 风险

低。改动局限在协程模式的状态回传链路，线程模式行为不变。

## 验证

- `python manage.py check`：0 issues
- 批量任务测试 18/18 通过
