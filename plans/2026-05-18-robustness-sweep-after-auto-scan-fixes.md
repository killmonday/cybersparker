# 自动扫描后续鲁棒性扫描与加固

- 日期：2026-05-18
- 状态：已完成

## 做什么

继续排查并修复任务执行链路里与近期问题同型的鲁棒性缺陷，重点覆盖自动扫描、批量任务、result writer、Celery worker 连接管理。

## 为什么

- 已连续暴露多类同型问题：消费者线程因空队列超时提前退出、result writer backlog 未及时 drain、Celery worker 线程/子进程拿到脏 DB 连接后炸线程。
- 当前自动扫描主路径看起来恢复正常，但同类模式如果还散落在其他位置，后续仍会以“结果空白”“任务假活着真停滞”“重启后异常”形式反复出现。

## 检查范围

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py`
- `app_cybersparker/tasks.py`
- `app_cybersparker/services/result_event_service.py`
- `cybersparker/celery.py`

## 关注模式

1. `queue.get(..., timeout)` 超时后直接 `break`。
2. Redis 主通道正常，但 DB fallback 查询失败时直接炸线程。
3. 结果事件/调度触发失败后缺少补偿触发。
4. Celery prefork 子进程继承脏连接池。

## 验证计划

1. 扫描并列出高风险点。
2. 只修高风险、主链路相关点。
3. 补最小回归测试。
4. `python manage.py test ...` 与 `python manage.py check`。

## 结果

### 扫描结论

本轮同类问题扫描后，优先修复了 3 个高风险薄弱点：
1. 自动扫描 `save_exp_result()` 单条异常时整线程退出。
2. 批量任务 `enqueue_batch_task()` 先写 queued 再 dispatch，投递失败无回滚。
3. 批量任务 `save_TaskResult()` 对结果队列 `get()` 无超时，异常收尾时可能永久卡死。

### 已执行修复

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
  - `save_exp_result()`：单条 `result_info` 解析/写入异常后改为 `continue`，不再整线程退出，确保后续结果仍能继续入队 writer。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py`
  - `enqueue_batch_task()`：`dispatch_task()` 失败时回滚运行态，写回 `status=3`、`queued=False`、`failed=True`、`last_error='dispatch failed'`、`endTime`。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py`
  - `save_TaskResult()`：结果队列改为 `get(..., 10)` + 空队列超时重试，仅在 `exit_flag` 且队列排空时真正退出，避免晚到结果无人处理。
- `app_cybersparker/tests.py`
  - 新增 `test_save_exp_result_continues_after_single_payload_failure`
  - 新增 `test_batch_start_rolls_back_runtime_state_when_dispatch_fails`
  - 新增 `test_save_task_result_waits_for_late_queue_output`
  - 批量任务相关测试类改为 `TransactionTestCase`，避免连接池/事务残留干扰。

### 验证结果

- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchTaskGeventRunnerTests app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_start_rolls_back_runtime_state_when_dispatch_fails app_cybersparker.tests.AutoScanAsyncRequestTests.test_save_exp_result_continues_after_single_payload_failure -v 2`：7/7 通过。
- `python manage.py check`：0 issues。

### 说明

- 本轮只处理 reviewer 扫出的高风险主链路问题，没有扩大到低风险清理。
- 其余未处理项可在后续继续按同样思路补强。
