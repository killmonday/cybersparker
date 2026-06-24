# Celery missing 与 result_writer 数据库异常排查

- 日期：2026-05-17
- 状态：已完成

## 做什么

排查并修复两类 Celery 运行时问题：
1. `run_auto_scan_task` 返回 `{'status': 'missing', 'task_id': 129}`
2. `run_result_writer_task` 抛出 `DatabaseError('error with status PGRES_TUPLES_OK and no message from the libpq')`

## 为什么

- 当前 Celery 日志已有用户可见异常。
- `missing` 需要确认是任务记录真的不存在，还是执行链路取错库/取错记录。
- `result_writer` 是结果入库链路单点，数据库异常会导致事件 pending 累积。

## 当前结论

- `auto_scan_tasks(id=129)` 在当前数据库中不存在，但 `auto_scan_indentify_result(task_id=129)` 仍有 1 条结果，说明 129 更像是历史任务被删除后，旧消息或旧结果残留，不是当前执行器主链路把存在的任务读丢了。
- `run_result_writer_task` 是结果写库入口，但没有像 `run_auto_scan_task` / `run_batch_scan_task` 一样先 `close_old_connections()`、结束后 `connection.close()`。
- `process_result_stream()` 只把 `OperationalError` / `TimeoutError` 当作暂时性 DB 故障；当前真实报错是 `DatabaseError`，因此会直接打爆 worker，而不是保留 pending 事件等待下次重试。

## 最小修复方案

1. `run_result_writer_task` 开头补 `close_old_connections()`，结束补 `connection.close()`。
2. `process_result_stream()` 将 `DatabaseError` 纳入暂时性 DB 失败分支，保留未处理事件，不 ack 失败事件。
3. 补测试：
   - writer 任务会先清理旧连接；
   - `DatabaseError` 时 pending 事件保留，后续可继续处理。
4. `missing task_id=129` 先不改主流程，只记录为“任务记录已被删除后的旧消息/残留结果”现象；若用户要求，再单独补删除清理策略。

## 风险

- writer 链路是结果统一入库单点，改动要保持“已成功事件 ack、失败事件保留 pending”语义不变。
- 现有测试库环境有脏状态，回归时优先跑最小定向测试。

## 验证计划

1. 定向测试 `ResultEventServiceTests` / `ResultWriterTaskTests` 新增用例。
2. `python manage.py check`。
3. 如环境允许，再触发一次 writer 任务验证不再因 `DatabaseError` 直接炸 worker。

## 结果

### 根因结论

1. `run_auto_scan_task(... task_id=129)` 返回 `missing` 的根因不是 Celery 取错任务，而是当前数据库中已经不存在 `auto_scan_tasks(id=129)` 这条任务记录。之前短暂存在的 `auto_scan_indentify_result(task_id=129)` 旧结果也已不存在，说明这是历史任务删除后的残留消息现象，不是当前自动扫描主执行链路读丢任务。
2. `run_result_writer_task` 的数据库异常更像是 worker 进程拿到了脏/失效连接后继续写库。该任务之前没有像 auto/batch 两条 Celery 任务那样在入口先 `close_old_connections()`，因此更容易踩到连接池里的坏连接。
3. `process_result_stream()` 原先只把 `OperationalError` / `TimeoutError` 视为可重试数据库故障，但现场真实异常是 `DatabaseError('error with status PGRES_TUPLES_OK and no message from the libpq')`，导致 writer 直接抛异常退出，而不是保留 pending 事件等待下次重试。

### 已执行修复

- `app_cybersparker/tasks.py`
  - `run_result_writer_task()` 入口补 `close_old_connections()`。
  - 任务退出时仅在真实 worker 场景（`request.is_eager=False`）关闭连接，避免测试 eager 模式污染当前测试线程连接。
- `app_cybersparker/services/result_event_service.py`
  - `process_result_stream()` 将 `DatabaseError` 纳入与 `OperationalError` 同级的暂时性数据库故障处理分支：失败事件不 ack，保留 pending，等待后续重试。
- `app_cybersparker/tests.py`
  - 新增 `test_pending_events_survive_database_error`。
  - 新增 `test_result_writer_task_closes_stale_connections_before_processing`。
  - `ResultWriterTaskTests` 改为 `TransactionTestCase`，避免 eager Celery 任务影响同线程事务/连接池状态。

### 验证结果

- `python manage.py test --keepdb --noinput app_cybersparker.tests.ResultEventServiceTests.test_pending_events_survive_writer_failure app_cybersparker.tests.ResultEventServiceTests.test_pending_events_survive_database_error app_cybersparker.tests.ResultWriterTaskTests.test_result_writer_task_closes_stale_connections_before_processing -v 2`：3/3 通过。
- `python manage.py test --keepdb --noinput app_cybersparker.tests.ResultEventServiceTests app_cybersparker.tests.ResultWriterTaskTests -v 2`：9/9 通过。
- `python manage.py check`：0 issues。
- `python manage.py shell -c "... task129 / identify129 ..."`：确认 `task129=0`、`identify129=0`，当前已不存在 129 任务及其识别结果残留。

### 备注

- `task_id=129 missing` 现阶段归类为历史已删除任务的旧消息现象，不修改自动扫描主流程；若后续仍频繁出现，可单独补“删除任务时清理 Redis pending / 结果事件”的治理项。
