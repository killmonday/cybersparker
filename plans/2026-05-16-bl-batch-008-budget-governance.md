# BL-BATCH-008 批量任务全局预算与结果事件治理

## 做什么
- 线程模式（`_run_thread_mode`）的 `consumer_exp` 线程数受全局 `threads` 资源预算约束。
- gevent 模式（`_run_gevent_mode`）的 greenlet 数受全局 `coroutines` 资源预算约束。
- 结果事件缓冲（`save_TaskResult` → `STREAM_BATCH_EXP` → DB writer）已在 BL-SCHED-006 完成，本项只验证。
- stop bridge 已在 BL-BATCH-007 完成，本项只验证。

## 为什么
- BL-BATCH-007 已将批量任务迁移到 Celery，但 worker 内部仍无视全局线程/协程预算创建消费者。
- 本项让批量任务的实际线程/协程占用不超出其已申请的全局预算。

## 怎么做
1. `__init__` 中从 `resource_leases` 解析 threads/coroutines 预算。
2. `_run_thread_mode` 中 `consumer_exp` 启动数受预算上限约束。
3. `_run_gevent_mode` 中 pool size 受协程预算上限约束。
4. 补测试：线程预算、协程预算、结果事件、stop bridge。
5. 同步 backlog、控制台、CHANGELOG。

## 风险
- 预算默认值远大于 `thread_num`，约束仅在高负载或多任务叠加时生效。
- gevent 预算约束后可能影响吞吐，但 `GLOBAL_COROUTINE_LIMIT` 默认 8000，实际不会触发。

## 当前状态
- [已完成] 代码实现（`_read_budget_from_leases()` + `_run_thread_mode` + `_run_gevent_mode` 预算约束）。
- [已完成] 补充 6 个测试（线程预算、协程预算、fallback、结果事件、stop bridge、无界增长）。
- [已完成] 最终验证全部通过。

## 验证
- `py_compile` + `pyright` + test + check + makemigrations

## 下一步
- 实现 → 测试 → 验证 → 文档 → 等待指示。
