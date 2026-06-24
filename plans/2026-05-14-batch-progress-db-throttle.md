# 2026-05-14 批量任务进度写库策略收敛

## 问题

批量任务执行器当前在 worker 完成目标后和主循环轮询中都可能调用 `get_progress()`，而 `get_progress()` 每次都会写 `batch_EXPTask.process`。大批量目标时会产生高频 ORM `update()`，增加 SQLite/WAL 写压力。

## D-lite 例外说明

本次是通过 `/project-control-plane` 进入的小范围行为优化：只调整批量任务执行器进度落库策略和测试，不变更数据库 schema、公开 API、认证安全策略或跨模块契约；按 Mode D-lite 执行。

## 目标

- worker 完成目标后以内存 `completed_count` 作为进度真源。
- 数据库只在百分比变化、时间窗口到期、任务完成/退出兜底时写入。
- 避免从截断后的百分比字符串恢复时明显回退。

## 影响面

- GitNexus `get_progress` upstream：LOW，直接调用者 `_run_thread_mode`、`_run_gevent_mode`。
- GitNexus `producer` upstream：LOW。
- GitNexus `consumer_exp` upstream：LOW。

## 最小方案

1. 在 `Task_handler` 中增加上次落库百分比与落库时间状态。
2. 将 `get_progress()` 改为统一 flush 方法：默认按百分比变化或时间窗口写库，`force=True` 时强制写库。
3. worker 完成目标后只更新 `completed_count` 并尝试 flush；主循环保留兜底 flush。
4. 修复百分比恢复：对历史百分比换算完成条数时使用 `round()` 并边界裁剪。
5. 增加测试覆盖重复进度不重复写库、force 写 100%、百分比恢复不回退。

## 风险

- UI 仍从数据库读取进度，节流时间过长会让页面刷新看到的进度略滞后；本次采用短时间窗口并保留百分比变化触发。
- 当前执行器仍依赖进程内内存状态；子进程崩溃时只能恢复到最近一次落库进度。

## 验证记录

- `python manage.py test app_cybersparker.tests.RequestRuntimePatchTests`：通过，8 tests OK，覆盖 SSL patch、进度节流、终态强制落库一次、历史百分比恢复真实 `producer()` 路径。
- `python manage.py test app_cybersparker.tests.RequestRuntimePatchTests app_cybersparker.tests.NucleiRuntimeRequestChainTests app_cybersparker.tests.BatchTaskGeventRunnerTests`：通过，12 tests OK。
- `python manage.py test app_cybersparker`：通过，13 tests OK。
- `python manage.py check`：通过，System check identified no issues。
- `gitnexus_detect_changes(scope="all")`：通过，risk_level=low，affected_processes=[]。
- `simplify` 审查：已完成；采纳终态重复 force 写库、节流状态并发穿透、恢复测试只测表达式三项反馈。

## 结果

- 批量任务执行器进度以内存 `completed_count` 为真源，默认只在整数百分比 bucket 变化或 3 秒窗口到期时写库。
- 任务正常结束只由 `_finalize_run()` 做一次终态兜底 flush，`get_progress(force=True)` 对已写入 100% 的状态不重复写终态。
- 节流判断、状态更新和 ORM `update()` 在同一把 `progress_lock` 内执行，避免多 worker 同 bucket 并发穿透重复写库。
- 历史进度恢复从百分比换算完成条数时使用 `round()` 并裁剪边界，降低小文件百分比截断导致的明显回退。
