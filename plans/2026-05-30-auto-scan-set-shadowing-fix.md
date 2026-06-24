# 2026-05-30 自动扫描 `set` 名字冲突修复

## 做什么
- 修复 `app_cybersparker/views/expload/task_manage/auto_exp_task.py` 中 `cybersparker.settings as set` 与 Python 内置 `set()` 的名字冲突。
- 补 1 条回归测试，覆盖自动扫描漏洞消费线程执行 `severity=info` 过滤分支时不会再崩溃。
- 更新 `CHANGELOG.md`。

## 为什么
- 自动扫描任务在漏洞消费线程里执行 `info_exp_ids = set(...)` 时，实际调用到了 `cybersparker.settings` 模块，线程直接报 `'module' object is not callable`。
- 这个问题会让自动扫描在进入 `severity=info` 过滤分支后中断，后续漏洞结果无法继续入队。

## 怎么做
1. 把 `auto_exp_task.py` 中的 settings 别名从 `set` 改成不会和内置函数冲突的名字。
2. 同步替换该文件里所有 `set.` 引用。
3. 在 `app_cybersparker/tests.py` 增加回归测试：构造一个自动扫描 handler，让 `exp_consumer()` 真实跑到 `set(...)` 过滤分支，断言线程不报错且结果正常入队。
4. 运行定向测试验证。

## 风险
- 改动范围只在单文件内的模块别名替换，风险低。
- 若有遗漏的 `set.` 引用，会在导入或运行时直接暴露。

## 验证
- 定向测试通过：新增回归测试 + 相关自动扫描测试。
- 如有必要，再补 `python manage.py check`。

## 结果
- 已完成：`auto_exp_task.py` 中的 settings 别名已从 `set` 改为 `app_settings`，消除了与 Python 内置 `set()` 的名字冲突。
- 已补 1 条回归测试，覆盖自动扫描漏洞消费线程命中 `severity=info` 过滤分支时仍能正常继续入队。
- 已完成定向验证：`python manage.py test --keepdb --noinput app_cybersparker.tests.AutoScanAsyncRequestTests.test_exp_consumer_filters_info_templates_without_set_name_conflict app_cybersparker.tests.AutoScanAsyncRequestTests.test_exp_consumer_normalizes_nuclei_result_before_queueing` 通过。

## 文档
- 不需要更新 `docs/`：这次仅是内部线程代码名字冲突修复，没有功能、接口、数据模型变化。
