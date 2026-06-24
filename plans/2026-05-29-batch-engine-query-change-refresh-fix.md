# 2026-05-29 批量任务检索语句变更后强制重抓修复

## 做什么
- 修复批量任务使用空间测绘引擎时，编辑任务并修改检索语句后，重新开始仍复用旧抓取结果的问题。
- 保持原有“复用数据”开关语义不变，但增加两个硬例外：检索语句变了就必须重新抓；空间测绘引擎切换了也必须重新抓。
- 补请求级回归测试，覆盖“编辑改查询强制失效”“查询不变继续复用”“同查询但切换引擎强制失效”三个边界。

## 为什么
- 现在后端在编辑保存时会比较“旧查询”和“新查询”，但传入的旧任务对象和表单实例实际是同一个对象。
- 结果是：表单校验把新查询写回实例后，再去读“旧查询”时，读到的已经也是新值了。
- 具体场景：任务原来查询 `app="nginx"`，第一次抓到旧 TXT；用户编辑成 `app="apache"`，同时界面还选了“复用已有数据”；后端本应识别出查询已变化并清空 target，等下次启动时重新调引擎抓新数据，但实际上把它误判成“查询没变”，于是旧 TXT 被继续复用。

## 怎么做
1. 在批量任务编辑保存链路里，把旧 `engine_query` / 旧 `target` 在 `form.is_valid()` 之前先单独取出来，不再从会被表单覆盖的同一个实例上回读。
2. `resolve_target_source()` 改为接收独立的旧引擎类型、旧查询、旧 target 值，复用判断只基于这些快照值比较。
3. 补三条测试：编辑时改查询语句必须失效；查询不变时继续复用；同查询但切换引擎也必须失效。
4. 跑定向测试 + `python manage.py check`，再同步 backlog / 模块文档 / 当前实现总览 / CHANGELOG。

## 风险
- 改动只在批量任务 `input_type=4` 的编辑保存分支，启动/续跑执行器链路不动。
- 自动扫描任务里存在同样写法，但本次先不顺手改，避免扩大范围；如果用户要一起收口，再单独处理。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchEngineForceRefreshTests app_cybersparker.tests.BatchScanCeleryDispatchTests.test_batch_restart_engine_task_dispatches_force_refresh_when_reuse_disabled app_cybersparker.tests.BatchScanCeleryDispatchTests.test_run_batch_scan_task_passes_force_refresh_to_start_task`：7/7 通过
- `python manage.py check`：通过，0 issues
- 请求级回归点：编辑任务时把 `engine_query` 从 `app="nginx"` 改成 `app="apache"`，即使提交 `reuse_engine_data=true`，保存后也会落成 `reuse_engine_data=False` 且 `target=None`
- 边界回归点：编辑任务时 `engine_query` 不变且提交 `reuse_engine_data=true`，保存后继续保留旧 `target` 和复用配置
- 引擎切换回归点：编辑任务时 `engine_query` 不变，但 `engine_type` 从 `fofa` 切到 `hunter`，即使提交 `reuse_engine_data=true`，保存后也会落成 `reuse_engine_data=False` 且 `target=None`

## 结果
- 已完成：批量任务编辑 `input_type=4` 任务时，复用判断改为比较编辑前快照的旧 `engine_type` / `engine_query` / `target`，不再读被表单覆盖后的同一实例。
- 已完成：只要检索语句变化，或空间测绘引擎发生切换，就强制清空旧 target，下一次启动/重跑重新抓取。
- 已完成：新增 3 条请求级回归测试，分别锁定“改查询强制失效”“查询不变继续复用”“切引擎强制失效”三个边界。
