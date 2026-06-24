# 2026-05-28 批量任务停止信号延迟退出修复

## 做什么
- 修复批量任务在收到 stop 信号后，当前目标剩余插件仍继续执行的问题。
- 增加回归测试，覆盖“同一目标多插件场景下 stop 信号应尽快中断后续插件执行”。

## 为什么
- 现象是用户点击停止后，Celery 日志仍持续输出，容易误判为停止失效。
- 根因是 `consumer_exp()` 只在拿下一条目标前检查一次 stop bridge，进入当前目标的插件循环后不再检查，导致当前目标挂了多个插件时会把整轮跑完。

## 怎么做
1. 在 `batch_task_executor.py` 的 `consumer_exp()` 插件循环内增加 stop 检查。
2. 保持现有 stop/续跑状态模型不变，只做最小行为收口。
3. 在 `app_cybersparker/tests.py` 增加回归测试，验证 stop 后不会继续执行同一目标剩余插件。
4. 运行定向测试与必要自检。

## 风险
- 改动位于批量任务执行主链路，会影响启动后的停止收敛时机。
- 需要确保正常完成时不误提前退出，也不能影响单插件场景。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_thread_handler_stop_bridge_sets_exit_flag app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_consumer_stops_before_remaining_plugins_on_stop_signal`：通过
- `python manage.py check`：通过，0 issues

## 结果
- 已完成：当前目标进入插件循环后也会再次检查 stop 信号，停止后不会把同一目标剩余插件继续跑完。

## 后续
- 若验证通过，同步 backlog / 模块文档 / CHANGELOG。
