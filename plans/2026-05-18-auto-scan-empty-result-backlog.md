# 自动扫描结果页空白与 writer backlog 排查

- 日期：2026-05-18
- 状态：已完成

## 做什么

修复自动扫描任务已产出识别事件，但结果页查库为空的问题。

## 为什么

- 任务 144 已跑完（`status=1/process=100%/phase=3`），但 `auto_scan_indentify_result(task_id=144)=0`。
- 直接检查 Redis `identify_result` stream，已能看到 `task_id=144` 的识别事件，说明扫描和指纹匹配真实发生了。
- 结果页 `Task_result()` 只是按 `task_id` 查 `auto_scan_indentify_result`，没有额外过滤，所以页面空白不是前端问题。
- 当前 `identify_result` backlog 很大（`stream_depth=26398`、`pending=2676`），说明 writer 没有把 backlog 及时 drain 完。

## 当前判断

- `run_result_writer_task()` 每次只调用一次 `process_result_streams()`。
- `process_result_stream()` 每次最多消费 `RESULT_EVENT_BATCH_SIZE`（默认 100）条。
- 当自动扫描在短时间内产出大量事件时，一个 writer task 只处理其中一小批；如果此后没有新的调度触发，剩余 backlog 会留在 stream/pending 中，数据库里就长期看不到该任务结果。

## 最小修复方案

1. `run_result_writer_task()` 改为在单次任务内循环 drain：只要本轮还有 `processed > 0`，就继续下一轮 `process_result_streams()`。
2. 汇总返回总处理数和最终 pending，保持日志可读。
3. 补测试：把 `RESULT_EVENT_BATCH_SIZE` 压到 1，发布 3 条结果事件，执行一次 writer task 后应全部入库，而不是只处理 1 条。

## 风险

- 不能引入无限循环；当本轮 `processed == 0` 必须立即退出。
- 不能破坏现有 `DatabaseError/OperationalError` pending 保留语义。

## 验证计划

1. `ResultWriterTaskTests` 新增/更新 drain backlog 回归。
2. 复跑 `ResultEventServiceTests + ResultWriterTaskTests`。
3. `python manage.py check`。

## 结果

### 根因结论

- 任务 144 已跑完，但数据库结果为空，不是页面过滤问题；`Task_result()` 只是按 `task_id` 直接查 `auto_scan_indentify_result`。
- 直接检查 Redis `identify_result` stream，能看到 `task_id=144` 的识别事件，且样本里已有 `jquery`、`Microsoft(ISA Server)` 等匹配结果，说明扫描和指纹匹配都真实发生了。
- 当前 `identify_result` backlog 很大（排查时 `stream_depth=26398`、`pending=2676`），说明问题在“结果事件 → writer → 数据库”链路。
- `run_result_writer_task()` 之前每次只调用一次 `process_result_streams()`；而 `process_result_stream()` 单次只吃一批（默认 100 条）。当自动扫描短时间产出大量事件时，一个 writer task 只会处理其中一小批，剩余 backlog 会继续留在 stream/pending 里，导致页面查库长期为空或严重滞后。

### 已执行修复

- `app_cybersparker/tasks.py`
  - `run_result_writer_task()` 改为在单次任务内循环 drain backlog：只要本轮还有 `processed > 0`，就继续下一轮 `process_result_streams()`。
  - 返回值改为汇总结构：`processed_total` + 最终 `streams` 状态。
- `app_cybersparker/tests.py`
  - 更新原有 writer 测试，使其校验 `processed_total`。
  - 新增 `test_result_writer_task_drains_backlog_in_single_run`，将 `RESULT_EVENT_BATCH_SIZE=1`，验证单次 writer task 能把 3 条 backlog 全部吃完，而不是只处理 1 条。

### 验证结果

- `python manage.py test --keepdb --noinput app_cybersparker.tests.ResultWriterTaskTests app_cybersparker.tests.ResultEventServiceTests -v 2`：10/10 通过。
- `python manage.py check`：0 issues。

### 建议

- 部署新代码后，重新启动 Celery worker，并观察 `run_result_writer_task` 日志中的 `processed_total` 是否持续下降 backlog。
- 对已积压的 `identify_result` stream，可手动触发一次 writer task，让 backlog 先 drain 完，再刷新结果页确认任务 144 是否入库可见。
