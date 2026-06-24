# 自动扫描测绘输入 target 为空修复

- 日期：2026-05-18
- 状态：已完成

## 做什么

修复自动扫描任务输入来源为网络空间测绘引擎时，Celery worker 路径漏掉目标准备，导致 `target` 为空仍被标记成功完成的问题。

## 为什么

- 任务 156 已完成但 `target=''`、数据库结果 0 条。
- 任务输入来源是网络空间测绘引擎，按设计启动前应抓取资产并落成目标文件。
- 说明测绘输入的目标准备逻辑在 Celery 路径上被漏掉了。

## 根因

- `Task_operate()` 只负责写运行态并投递 Celery。
- 真正执行发生在 `app_cybersparker/tasks.py::_run_auto_scan_task()`。
- 该函数之前直接读取 `row_dict` 并调用 `startTask()`，没有像旧 Web 线程路径那样先执行 `prepare_engine_target_before_start()`。
- 导致 `input_type=4` 时 `target` 可能仍为空字符串，但任务仍被继续执行并最终被标记成功。

## 已执行修复

- `app_cybersparker/tasks.py`
  - 在 `_run_auto_scan_task()` claim 成功后，先加载 `task_obj`。
  - 调用 `auto_scan_task.prepare_engine_target_before_start(task_obj, is_restart=is_restart)`。
  - 如果准备失败，直接将任务标记为 `failed`，不再继续启动扫描。
  - 准备成功后，再重新读取最新 `target` 进入 `row_dict`，保证 `startTask()` 用到的是已生成的目标文件路径。
- `app_cybersparker/tests.py`
  - 新增 `test_run_auto_scan_task_prepares_engine_target_before_start`，覆盖 Celery worker 路径会先准备测绘 target。

## 验证

- `python manage.py test --keepdb --noinput app_cybersparker.tests.AutoScanCeleryDispatchTests.test_run_auto_scan_task_prepares_engine_target_before_start -v 2`：1/1 通过。
- `python manage.py check`：0 issues。
