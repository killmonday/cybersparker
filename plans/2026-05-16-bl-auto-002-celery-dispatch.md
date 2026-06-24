# BL-AUTO-002 自动识别任务投递迁移到 Celery

## 做什么
- 将 `POST /Identify_task/operate` 的自动识别启动路径改为写 DB 运行态并投递 `auto_scan` Celery task。
- 为自动识别任务接入 `dispatch_token/owner` 运行态与最小 stop bridge（DB `stop_requested` + Redis stop flag）。
- 让 Celery worker 暂时复用现有 `Auto_exploit_Task_handler`，并通过 CAS helper 保护终态写入。

## 为什么
- `BL-SCHED-002` 已提供 Celery 队列、dispatch 硬闸门和终态 CAS helper；下一步需要先把自动识别任务从 Django 请求线程里剥离出去。
- 自动识别任务执行时间长、线程数高，最先受益于 Web/worker 解耦。
- 此项先迁入口，不改 HTTP async 层，能最小化风险并为后续 `BL-AUTO-003/004` 铺路。

## 怎么做
1. 在 `app_cybersparker/tasks.py` 增加 `auto_scan` worker task，接收 `task_id + dispatch_token`。
2. 在 `auto_scan_task.py` 的启动接口写入 `queued/dispatch_token/owner/stop_requested` 并通过 `dispatch_task(..., queue='auto_scan')` 投递。
3. 在 worker 侧 claim 当前 token，对旧 token / 重复消息直接 no-op。
4. 在 `Auto_exploit_Task_handler` 内增加最小 stop bridge：周期检查 DB `stop_requested` 与 Redis stop flag，命中后置 `exit_flag`。
5. 正常结束 / 停止 / 异常结束统一走 CAS helper 写终态。
6. 补测试：不再由请求线程直接起长线程、重复消息 no-op、eager 路径执行、stop bridge 生效、异常恢复为 failed/stopped。

## 风险
- 需要保持旧的 `KILL_AUTO_TASK_DIC` 兼容本机句柄缓存，但不能再作为终态真源。
- stop bridge 的检查点必须足够频繁，避免 UI 已请求停止但执行器长时间无感。
- 不能在 stop 请求里直接覆盖终态，否则会破坏旧 token/迟到 stop 质量门。

## 当前状态
- [已完成] 收尾 BL-SCHED-002 文档并切到 BL-AUTO-002。
- [已完成] 迁移自动识别任务启动路径到 Celery。
- [已完成] 接入最小 stop bridge 与 CAS 终态。
- [已完成] 增加测试并完成验证；文档已进入同步收尾。

## 验证
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanCeleryDispatchTests`：通过（5/5）。
- `DB_HOST=192.168.1.11 python manage.py check`：通过，0 issues。
- `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`：通过，无迁移漂移。
- `python -m py_compile` 覆盖 `auto_scan_task.py`、`auto_exp_task.py`、`tasks.py`、`task_state_cas_service.py`、`task_runtime_signal_service.py`：通过。

## 结果
- `Task_operate` 启动路径改为写 DB 运行态并投递 `run_auto_scan_task` 到 `auto_scan` 队列，请求线程不再直接起长生命周期扫描线程。
- worker 侧接入 `dispatch_token/owner` claim、重复消息 no-op、终态 CAS 写入。
- 自动识别执行器新增最小 stop bridge：轮询 DB `stop_requested` 与 Redis stop signal，命中后设置 `exit_flag/stop_requested`。
- `KILL_AUTO_TASK_DIC` 保留为本机执行器句柄缓存，不再作为终态真源。

## 下一步
- 继续 `BL-BATCH-007`。
