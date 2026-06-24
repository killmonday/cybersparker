# BL-AUTO-004 自动识别指纹与漏洞验证并发治理

## 做什么
- 指纹识别消费者线程数从无条件 `thread_num` 改为受全局 `threads` 资源预算约束。
- 漏洞验证消费者（`exp_consumer`）线程数同样纳入预算，不做异步改造。
- 指纹队列满时保持上游 async fetcher 背压（BL-AUTO-003 已实现），本项只验证不退化。
- 识别/漏洞结果继续走 event buffer → DB writer（BL-SCHED-006 已实现），本项只验证不断路。

## 为什么
- BL-AUTO-003 已收口网络层并发，但指纹匹配和漏洞验证线程仍可能随 `thread_num` 线性增长，与全局 `threads` 预算脱节。
- 本项让自动识别任务的实际线程占用不超出其已申请的全局预算，防止高负载下线程无限扩张。

## 怎么做
1. `__init__` 中从 `self.resource_leases` 解析 `threads` 资源已申请量，计算可用 worker 线程数。
2. `run()` 中 `fingerpoint_worker_count` 和 `exp_consumer` 启动数受预算上限约束。
3. 补测试：线程预算约束、fingerprint queue 背压保持、event 发布路径畅通、高负载无界增长检查。
4. 同步 backlog、项目控制台、模块文档、CHANGELOG。

## 风险
- 预算约束可能导致指纹/漏洞消费线程少于 `thread_num`，降低吞吐。当前 `GLOBAL_THREAD_LIMIT` 默认 1800，远大于 `thread_num`，实际不会触发。
- 不需要改插件执行模型，风险低。

## 当前状态
- [已完成] 加载上下文，创建计划。
- [已完成] 实现指纹线程预算控制（`__init__` 中 `_read_thread_budget_from_leases()` + `run()` 中 `_thread_budget`/`exp_worker_count` 约束）。
- [已完成] 补充 6 个测试：预算读取、预算约束、fallback、exp consumer 分半预算、backpressure、无界增长。
- [已完成] 最终验证全部通过。

## 验证结果

| 命令 | 结果 |
|---|---|
| `python -m py_compile auto_exp_task.py` | 通过 |
| `python -m py_compile tests.py` | 通过 |
| `pyright --pythonpath /opt/venv/bin/python auto_exp_task.py tests.py` | 0/0/0 |
| `python manage.py test --keepdb AutoScanThreadBudgetTests AutoScanAsyncRequestTests AutoScanCeleryDispatchTests` | 16/16 OK |
| `python manage.py check` | 0 issues |
| `python manage.py makemigrations --check --dry-run` | No changes |

## 结果
- 指纹识别消费者线程数现在受全局 `threads` 资源预算约束（从 `resource_leases` 读取），不再无条件使用 `thread_num`。
- 漏洞验证消费者（`Vulnerability_scanning=1`）纳入 `thread_budget // 2` 子预算，避免与指纹线程叠加超限。
- 无 lease 时回退到 `thread_num`，保证向后兼容。

## 下一步
- 等待指示。
