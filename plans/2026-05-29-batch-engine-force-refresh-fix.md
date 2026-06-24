# 2026-05-29 批量任务空间测绘重复拉取配置失效修复

## 做什么
- 修复批量任务 `input_type=4` 时，“是，重新获取数据”配置在第二次启动/重跑时不生效的问题。
- 让批量任务启动链路显式传递“这次是否强制重新拉取”信号，不再靠旧 TXT 是否存在来猜。
- 补充定向测试，覆盖投递参数透传、worker 透传、旧文件强制刷新三层。

## 为什么
- 现在编辑页虽然能保存 `reuse_engine_data=false`，但真正启动时 `prepare_engine_target_before_start()` 只看旧 target 文件在不在。
- 结果就是：任务第一次跑完后，第二次即使用户明确配置“重新获取”，后端仍直接复用上一次生成的 TXT。
- 具体场景：任务 A 查询 `app="nginx"`，第一次生成 `engine_assets/a.txt`；用户在编辑页选择“是，重新获取数据”；第二次点击重跑，本应重新调用引擎 API 拉新结果，但代码只看到 `a.txt` 还在，于是直接跳过获取。

## 怎么做
1. 给批量任务启动链路补上 `force_refresh_engine` 参数：`operate()` → `run_batch_scan_task()` → `_run_batch_scan_task()` → `startTask()` → `prepare_engine_target_before_start()`。
2. 非续跑启动时，若任务配置 `reuse_engine_data=false`，则把 `force_refresh_engine=True` 传入 worker。
3. `prepare_engine_target_before_start()` 参考自动扫描已修好的实现：收到 `force_refresh=True` 时先删旧 engine target，再重新 `fetch_and_dump_targets()`。
4. 补三条定向测试：
   - 重跑时是否把 `force_refresh_engine=True` 投到队列
   - worker 是否把该参数继续传给 `startTask()`
   - 强制刷新时是否删旧文件并取新文件

## 风险
- 只影响批量任务 `input_type=4` 启动/重跑/续跑链路，不动历史文件、检索语句等其他输入源。
- 若把续跑也误判成强制刷新，会导致用户原本想接着跑，却被重新拉了一份新目标，所以要单独卡住 resume 分支。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_restart_engine_task_dispatches_force_refresh_when_reuse_disabled app_cybersparker.tests.BatchScanCeleryDispatchTests.test_run_batch_scan_task_passes_force_refresh_to_start_task app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_resume_engine_task_does_not_dispatch_force_refresh app_cybersparker.tests.BatchEngineForceRefreshTests.test_prepare_engine_target_before_start_force_refresh_fetches_new_file app_cybersparker.tests.BatchEngineForceRefreshTests.test_prepare_engine_target_before_start_reuses_existing_file_when_not_forced`：5/5 通过
- `python manage.py check`：通过，0 issues
- 独立代码复核：通过（重点确认启动/重跑链路已修到、resume 未误伤）

## 结果
- 已完成：批量任务启动链路新增 `force_refresh_engine` 显式透传，`reuse_engine_data=false` 时启动/重跑会删旧 TXT 并重新调用空间测绘引擎。
- 已完成：`resume` 续跑保持原目标文件，不触发重新拉取。
- 已完成：补 5 条定向回归测试，覆盖重跑强制刷新、worker 透传、resume 不重拉、强制刷新删旧取新、非强制继续复用。

## 后续
- 已同步 `docs/backlog/02-任务执行.md`、`docs/modules/02-任务执行模块.md`、`docs/当前实现总览.md`、`CHANGELOG.md`。
