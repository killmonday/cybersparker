# 自动扫描任务固定进度卡住排查

- 日期：2026-05-17
- 状态：已完成

## 做什么

修复自动扫描任务在 Web 扫描阶段卡在固定进度（如 19.10%）不再刷新、Celery 日志停止推进的问题。

## 为什么

- 运行中任务 `id=143` 长时间停在 `process=19.10%`、`phase=1`、`current_line=82`。
- `heartbeat_at` 持续刷新，说明 worker 还活着，但识别结果表 `auto_scan_indentify_result(task_id=143)` 仍为 0，属于执行器内部假活着真停滞。
- 现场日志显示请求错误后没有新的 `request_consumer get line` / 结果写库推进日志，怀疑下游消费者提前退出导致队列回压。

## 当前判断

- `fingerpoint_consumer_thread()` 使用 `queue_fingerpoint_input.get(True, 10)`，一旦 10 秒内暂时没有响应结果就直接 `break` 退出。
- 若所有指纹消费者都在请求结果回来前提前退出，后续成功返回的响应会堆进 `queue_fingerpoint_input`。
- `_request_consumer_async()` 看到 `queue_fingerpoint_input.full()` 后会停止继续投递；producer 也会因 `queue_fingerpoint_input.full()` 停止读新 URL，最终进度固定不动。
- 需同时检查 `exp_consumer()` 是否存在同类“空队列超时即退出”的问题。

## 最小修复方案

1. 指纹消费者：空队列超时后不再直接退出。
2. 仅在“producer 已结束 + request scheduler 已结束 + `queue_fingerpoint_input` 为空”时才自然退出。
3. 若 `exp_consumer()` 存在同类退出条件，按同样原则收紧。
4. 补回归测试：模拟前 10 秒没有响应、稍后才有响应时，消费者不会提前退出，任务仍能继续消费结果。

## 风险

- 需要避免修成永久空转线程，必须保留明确的自然退出条件。
- 不能影响 pause/stop 逻辑，也不能破坏现有 `queue.join()` 收敛。

## 验证计划

1. 定向测试 `AutoScanAsyncRequestTests` 新增“指纹消费者不会因暂时空队列提前退出”。
2. 复跑现有 async/backpressure 相关测试。
3. `python manage.py check`。

## 结果

### 根因结论

- `fingerpoint_consumer_thread()` 使用 `queue_fingerpoint_input.get(True, 10)`，10 秒内暂时没有响应结果时会直接 `break` 退出。
- `exp_consumer()` 和 `save_exp_result()` 对 `queue_EXP_input` / `queue_EXP_result` 也有同样的“空队列超时即退出”行为。
- 一旦这些下游消费者在线路初期提前退出，请求调度器后续返回的数据会逐步塞满下游队列；`_request_consumer_async()` 看到 `queue_fingerpoint_input.full()` 后停止继续投递，producer 也因 `queue_fingerpoint_input.full()` 停止读新 URL，最终进度固定在某个百分比（如 19.10%）不再刷新，但 worker 心跳仍在，形成“假活着真停滞”。

### 已执行修复

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
  - `fingerpoint_consumer_thread()`：空队列超时后改为继续等待；仅在 `producer_done` 且上游/本队列都排空时才自然退出。
  - `exp_consumer()`：同样改为“暂时空队列继续等，阶段真正结束才退出”。
  - `save_exp_result()`：同样改为“暂时空队列继续等，结果阶段真正结束才退出”。
- `app_cybersparker/tests.py`
  - 新增 `test_fingerprint_consumer_waits_for_late_response_instead_of_exiting`，覆盖“前 10 秒没数据、稍后才到结果”场景，确保指纹消费者不会提前退出。

### 验证结果

- `python manage.py test --keepdb --noinput app_cybersparker.tests.AutoScanAsyncRequestTests.test_fingerprint_consumer_waits_for_late_response_instead_of_exiting app_cybersparker.tests.AutoScanAsyncRequestTests -v 2`：6/6 通过。
- `python manage.py check`：0 issues。

### 说明

- 当前回归是执行器级定向验证，证明消费者不会再因暂时空队列提前退出。
- 如需进一步确认现场任务恢复情况，建议用新代码重启对应自动扫描任务并观察 `process/current_line/identify_count` 是否继续推进。
