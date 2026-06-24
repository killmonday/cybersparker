# 2026-05-29 自动扫描空间测绘复用规则补修

## 做什么
- 检查自动扫描任务、目录扫描任务是否存在与批量任务相同的空间测绘旧数据误复用问题。
- 修复自动扫描任务在编辑 input_type=4 时：只要检索语句变化，或空间测绘引擎发生切换，就必须清空旧 target，等待下次启动/重跑重新抓取。
- 说明目录扫描任务为何不存在同类复用链路，避免误改。
- 补自动扫描请求级回归测试，并同步文档。

## 为什么
- 自动扫描 `auto_scan_task.py` 的 `edit()` + `resolve_target_source()` 仍然保留了与批量任务修复前相同的写法：复用判断直接读取会被表单覆盖的旧实例字段。
- 这会导致两类误判：
  1. 查询变了却仍判成“没变”；
  2. 引擎切了但查询字符串一样，仍复用旧引擎抓下来的 TXT。
- 目录扫描任务当前输入源只有手动选任务 / 全选 / 检索语句，没有直接从空间测绘引擎抓取并复用旧 target 文件的配置，因此这条问题不适用。

## 怎么做
1. 在自动扫描 `edit()` 里于 `form.is_valid()` 前先快照旧 `engine_type` / `engine_query` / `target`。
2. 将 `resolve_target_source()` 的复用条件收紧为：同引擎 + 同查询 + 旧 target 文件仍存在。
3. 补请求级测试：改查询失效、同查询继续复用、切引擎失效。
4. 跑定向测试与 `python manage.py check`，同步计划、CHANGELOG、模块文档、实现总览。

## 风险
- 只动自动扫描 `input_type=4` 编辑保存分支，不碰其启动/暂停/续跑执行器主链。
- 目录扫描仅做结论记录，不改代码。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.AutoScanCeleryDispatchTests app_cybersparker.tests.BatchEngineForceRefreshTests app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_restart_engine_task_dispatches_force_refresh_when_reuse_disabled app_cybersparker.tests.BatchScanCeleryDispatchTests.test_run_batch_scan_task_passes_force_refresh_to_start_task`：17/17 通过
- `python manage.py check`：通过，0 issues
- 自动扫描请求级回归点：
  - 改查询语句：`reuse_engine_data=true` 也会落成 `reuse_engine_data=False` 且 `target=None`
  - 查询不变：继续保留旧 `target` 和复用配置
  - 同查询但切换引擎：也会落成 `reuse_engine_data=False` 且 `target=None`
- 目录扫描检查结论：当前输入源只有手动选任务 / 全选 / 检索语句，没有直接从空间测绘引擎抓取并复用旧 target 文件的配置，未发现同类问题

## 结果
- 已完成：自动扫描任务 `edit()` + `resolve_target_source()` 改为比较编辑前快照的旧 `engine_type` / `engine_query` / `target`，不再读被表单覆盖后的同一实例。
- 已完成：自动扫描允许复用的前提收紧为“同引擎 + 同查询 + 旧文件仍存在”；只要查询变化或引擎切换，就强制清空旧 target。
- 已完成：新增 3 条自动扫描请求级回归测试，锁定“改查询失效 / 同查询继续复用 / 切引擎失效”。
- 已完成：目录扫描任务已检查，未发现同类空间测绘复用旧 target 的链路，因此没有代码改动。
