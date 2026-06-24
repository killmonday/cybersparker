# BL-BATCH-007 批量任务投递迁移到 Celery

## 做什么
- 将 `POST /batch_exploadTask/operate` 的批量任务启动路径改为写 DB 运行态并投递 `batch_scan` Celery task。
- 批量任务 worker 暂时复用现有 `startTask()` / `Task_handler` / gevent 子进程模式，不改执行模型。
- 为批量任务接入 `dispatch_token/owner` 运行态与最小 stop bridge。

## 为什么
- `BL-SCHED-002` 已提供 Celery 队列、dispatch 硬闸门和终态 CAS helper；`BL-AUTO-002` 已验证自动识别入口迁移路径可行。
- 批量任务当前同样由 Django 请求线程直接起长生命周期线程/子进程，必须解耦到 worker。
- 此项先迁入口，后续 `BL-SCHED-005/006` 再做资源令牌和结果缓冲。

## 怎么做
1. 新增 `run_batch_scan_task` Celery task，接收 `task_id + dispatch_token`。
2. 在 `batch_exp_task.operate()` 启动/续跑分支写入 `queued/dispatch_token/owner/stop_requested` 并投递 `batch_scan`。
3. 在 worker 侧 claim 当前 token，对旧 token / 重复消息直接 no-op。
4. stop 路径写 DB `stop_requested` 与 Redis stop signal；本机句柄缓存仅做同进程快速停止。
5. 正常结束 / 停止 / 异常结束统一走 CAS helper。
6. 补测试：请求线程不再直接起长线程、重复消息 no-op、eager 路径执行、gevent/线程模式兼容、stop bridge 生效。

## 风险
- gevent 子进程模式目前用 `terminate()` fallback，stop bridge 只能做到最小保障，cooperative stop 仍留后续 backlog。
- `startTask()` 现有逻辑会在内部读取/刷新 target 文件，迁移时不能破坏续跑和空间测绘输入源行为。
- 批量任务既支持单 UID 也支持批量 UID 列表，迁移后要保持返回结构兼容。

## 当前状态
- [已完成] 读取批量任务入口、执行器和已有测试。
- [已完成] 迁移批量任务启动路径到 Celery。
- [已完成] 接入最小 stop bridge 与 CAS 终态。
- [已完成] 增加测试并完成文档同步。

## 验证
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.BatchScanCeleryDispatchTests`：通过（6/6）。
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanCeleryDispatchTests app_cybersparker.tests.BatchScanCeleryDispatchTests`：通过（11/11）。
- `DB_HOST=192.168.1.11 python manage.py check`：通过，0 issues。
- `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`：通过，无迁移漂移。
- `python -m py_compile` 覆盖 `batch_exp_task.py`、`batch_task_executor.py`、`tasks.py`：通过。

## 结果
- 批量任务启动/续跑路径已切换为写 DB 运行态并投递 `run_batch_scan_task` 到 `batch_scan` 队列。
- worker 侧接入 `dispatch_token/owner` claim、重复消息 no-op、终态 CAS 写入。
- 批量执行器新增最小 stop bridge：轮询 DB `stop_requested` 与 Redis stop signal，命中后设置 `exit_flag/stop_requested`。
- `BATH_TASK_DIC` 保留为本机执行器句柄缓存，不再作为终态真源。

## 下一步
- 已链式进入 `BL-SCHED-005`。
