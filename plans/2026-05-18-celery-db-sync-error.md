# Celery PostgreSQL 连接同步错误修复

- 日期：2026-05-18
- 状态：已完成

## 做什么

修复 Celery worker 中 PostgreSQL 连接失步（`lost synchronization with server`）导致自动扫描线程异常、结果写库失败的问题。

## 为什么

- Celery 日志出现 `OperationalError: lost synchronization with server`、`ProgrammingError: no results to fetch`、`InterfaceError: connection already closed`。
- 栈追踪落在自动扫描线程的 `check_stop_bridge()`，说明坏连接不只影响 writer，也会影响执行器内部心跳/停止兜底查询。
- 当前 worker 是 prefork + 连接池，最可疑的是子进程/线程复用了脏连接。

## 最小修复方案

1. Celery `worker_process_init` 时执行 `close_old_connections()` + `pool_container.dispose()`，确保子进程不继承父进程的脏连接池。
2. `heartbeat_resource_leases_if_needed()` 在 DB 写 `heartbeat_at` 失败时吞掉 `OperationalError/DatabaseError`，避免线程直接炸掉。
3. `check_stop_bridge()` / `check_pause_signal()` 的 DB fallback 失败时降级返回 `False`，优先依赖 Redis stop/pause 信号继续运行。
4. `compare_and_set_terminal_state()` 只在模型确实有 `phase` 字段时才写 `phase`，兼容 `batch_EXPTask`。
5. 补基础回归测试。

## 风险

- 不能让 stop/pause 真正失效；Redis 通道仍保留即时停止能力，DB 仅是兜底降级。
- 不能误伤 eager/test 模式的连接行为。

## 验证计划

1. `CeleryRuntimeInfrastructureTests` 覆盖 worker 子进程连接重置。
2. `check_stop_bridge`/心跳降级相关测试通过。
3. `python manage.py check` 0 issues。

## 结果

### 根因结论

- `OperationalError: lost synchronization with server`、`ProgrammingError: no results to fetch`、`InterfaceError: connection already closed` 不是业务 SQL 逻辑错误，而是 Celery prefork worker/线程拿到了脏 PostgreSQL 连接。
- 这类坏连接不只影响 result writer，也会影响自动扫描线程内部的 DB fallback（如 `check_stop_bridge()`、`check_pause_signal()`、`heartbeat_at` 写回），从而造成线程异常退出、进度停滞、结果页空白。

### 已执行修复

- `cybersparker/celery.py`
  - 新增 `worker_process_init` 钩子：子进程启动时执行 `close_old_connections()` + `pool_container.dispose()`，避免 prefork 子进程继承父进程里的脏连接池。
- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
  - `heartbeat_resource_leases_if_needed()` 在 DB 写 `heartbeat_at` 失败时降级，不再炸线程。
  - `check_stop_bridge()` / `check_pause_signal()` 的 DB fallback 失败时降级返回 `False`，继续依赖 Redis stop/pause 信号运行。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py`
  - 批量任务的 `heartbeat_resource_leases_if_needed()` / `check_stop_bridge()` 做了同样的 DB 异常降级。
- `app_cybersparker/services/task_state_cas_service.py`
  - `compare_and_set_terminal_state()` 只在模型存在 `phase` 字段时才写 `phase`，兼容 `batch_EXPTask`。
- `app_cybersparker/tests.py`
  - 新增 worker 子进程连接重置测试。
  - 新增 auto/batch stop bridge 忽略 DB 连接失败测试。

### 验证结果

- `python manage.py test --keepdb --noinput app_cybersparker.tests.CeleryRuntimeInfrastructureTests.test_worker_process_init_resets_db_connections app_cybersparker.tests.CeleryRuntimeInfrastructureTests.test_auto_scan_stop_bridge_ignores_db_connection_failure app_cybersparker.tests.CeleryRuntimeInfrastructureTests.test_batch_stop_bridge_ignores_db_connection_failure -v 2`：3/3 通过。
- `python manage.py test --keepdb --noinput app_cybersparker.tests.CeleryRuntimeInfrastructureTests.test_terminal_cas_ignores_old_token_duplicate_and_late_stop -v 2`：通过。
- `python manage.py check`：0 issues。

### 说明

- 这次修复是“连接损坏时不继承、不炸线程、可降级继续跑”。
- 它不能替代数据库/网络层稳定性本身，但能明显降低自动扫描与 writer 因单个坏连接直接崩链路的概率。
