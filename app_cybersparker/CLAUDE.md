# app_cybersparker — 模块级约定与已知陷阱

## 数据模型依赖

- **`EXPTask` 不能删**：即使单任务页面（`exploadTask/*`）已删除，模型仍被 `scheduler_runtime_service.py`（调度诊断）、`apps.py`（僵尸回收）、`recover_zombie_tasks.py`（管理命令）、`tests.py`（测试 fixture）引用。
- **`auto_scan_indentify_result` 不能删**：即使 `all_Indentify_result` 页面已删除，模型仍被 `Dashboards.py`、`auto_scan_result.py`、`dirscan_*`、`result_event_service.py`、`asset_search_parser.py`、`tasks.py` 等十几处引用。
- **`EXPTask_result` 不能删**：批量任务（`task_type=2`）共用此表，`Dashboards.py`、`expResult.py`、`result_event_service.py` 均依赖。

## 测试陷阱

### ModelForm.is_valid() 会修改 instance 对象

`form.is_valid()` 的最后一步 `_post_clean()` 会调用 `construct_instance()`，把 `cleaned_data` 里所有字段的值逐个 `setattr` 写回到 `instance` 上。如果编辑表单用 `form = SomeForm(data=POST, instance=row_object)`，`is_valid()` 执行完后 `row_object.search_query` 等字段已经是 POST 里的新值，不再是数据库旧值。

**场景**：编辑任务时想判断"检索语句是否变了"：
```python
row_object = Task.objects.get(id=uid)          # search_query = 'vuln="*"'
form = TaskForm(data=request.POST, instance=row_object)
form.is_valid()                                # _post_clean() 把 row_object.search_query 改成了 'port="*"'
old = row_object.search_query                  # ← 拿到的是新值，不是旧值！
new = form.cleaned_data["search_query"]
if new != old:                                 # 永远为 False，变更检测失效
```

**规则**：需要对比编辑前后差异的字段值，必须在 `form.is_valid()` **之前**从数据库实例上捕获：
```python
row_object = Task.objects.get(id=uid)
old_query = row_object.search_query            # ← 在 is_valid() 之前读
old_parsed = row_object.parsed_query            # ← 同理
form = TaskForm(data=request.POST, instance=row_object)
if form.is_valid():
    if form.cleaned_data["search_query"] != old_query:  # 正确对比
        ...
```

此陷阱影响所有 `resolve_target_source` / `task_edit` 风格的任务编辑函数。已修复三个文件：`dirscan_task_manage.py`、`auto_scan_task.py`、`batch_exp_task.py`。

### `_run_auto_scan_task` 会关连接

`app_cybersparker/tasks.py` 的 `_run_auto_scan_task()` 在生产中是正确的——Celery worker fork 后必须 `close_old_connections()` + `connection.close()` 断开父进程遗留的 PG 连接。但测试 runner 用数据库事务包裹每个测试，函数内关掉连接后事务无法回滚，后续测试也会因连接不可用全挂。

**规则**：任何直接或间接调用 `_run_auto_scan_task` 的测试，必须在 `with patch(...)` 中 mock 掉：
```python
patch("app_cybersparker.tasks.close_old_connections")
patch("app_cybersparker.tasks.connection.close")
```
mock 这两个就够了。`_run_auto_scan_task` 内部 `connection.close()` 被 mock 后，Django test runner 的事务连接保持完好。

### SafeTestRunner ENGINE 切换不完整

`app_cybersparker/test_runner.py` 的 `_swap_to_safe_engine()` 在 `setup_databases` 时改了 `settings.DATABASES['ENGINE']` 和 `conn.settings_dict['ENGINE']`，但 **没有从 `connections._connections` 缓存中删除旧的 pool backend wrapper 实例**。等到 ORM 访问时，拿到的是已缓存的 `dj_db_conn_pool.backends.postgresql.DatabaseWrapper`，仍然走 pool 的 SQLAlchemy 连接——`assert self.dbapi_connection is not None` 断言失败。

**绕过方式**：在 `django.setup()` **之前** 直接改 `settings.DATABASES['default']['ENGINE'] = 'django.db.backends.postgresql'`。此时 Django 还未创建任何连接 wrapper，从源头就用原生 PG 后端。

### 测试 fixture 滞后于模型迁移

阶段五（`task_id` → `AssetTaskRelation` 多对多关系表）迁移后，`auto_scan_indentify_result` 不再有 `task_id` 字段。创建测试数据时不能再用 `task_id=xxx` 参数，应改用 `AssetTaskRelation.objects.create(task_id=xxx, identify_result=asset)`。

`AutoScanResultSearchTests.setUp`（`tests.py:1674`）当前仍用 `task_id=` 参数，导致 20 个 `TypeError`。需要更新。

## 模块删除检查清单

删除一个 Django 视图页面时，按序检查：

1. 视图文件 → 删
2. 模板文件 → 删
3. 关联 JS 文件 → 删（注意 `static/` 目录可能有副本）
4. URL 路由 → 删
5. `cybersparker/urls.py` 的 import → 删
6. `index.html` 侧边栏 → 删
7. `tests.py` 中引用该视图的测试 → 删
8. 相关模型 → **先 grep 全项目引用再决定**，不要顺手删
9. 相关执行引擎 → 同上
10. `scheduler_runtime_service.py` 的任务类型映射 → 对应清理
11. `apps.py` 僵尸回收 → 对应清理
12. `recover_zombie_tasks.py` → 对应清理
13. 死代码引用（如其他 JS 文件中对已删除路由的 AJAX 调用） → 清理
14. `docs/modules/` 和 `docs/当前实现总览.md` → 同步

## 分发链覆盖

`auto_scan_tasks.input_type` 改动时必须全量覆盖以下分发点，漏一个就出 bug：

| 文件 | 位置 | 用途 |
|------|------|------|
| `auto_scan_task.py` | `resolve_target_source()` | 输入源解析 |
| `auto_scan_task.py` | `ModelForm.Meta.fields` | 表单字段白名单 |
| `auto_scan_task_api.py` | `task_choices_api()` | 前端下拉菜单 |
| `auto_scan_task.py` | `Task_operate()` | 启动/停止分发 |
| `auto_scan_task.py` | `clear_engine_fields()` | 引擎字段清理 |
| `auto_scan_task.py` | `edit()` | 编辑时回填

## 时间写入规范（硬性）

项目 `USE_TZ=True`，`TIME_ZONE='Asia/Shanghai'`。**所有写入数据库的时间必须带 UTC 时区**，Django 会在展示时自动转为上海时间。

### 禁止

- **禁止 `datetime.now()`**：返回 naive 本地时间（无时区），写入 `DateTimeField` 会被 Django 当 UTC 吞掉，实际差 8 小时。
- **禁止 `datetime.now().strftime(...) → strptime(...) → .replace(tzinfo=utc)`**：把本地时间的数字直接贴 UTC 标签，没有做时区转换。例子：`datetime.now()` 在 CST 返回 `14:30` → `.replace(tzinfo=utc)` 变成 `14:30 UTC`（实际是 `22:30 CST`，比正确时间早 8 小时）。

### 必须

- **Django 模型层**：`from django.utils import timezone` → `timezone.now()`
- **非 Django 环境或已有 `from datetime import datetime, timezone`**：`datetime.now(timezone.utc)`
- **模型字段**：优先用 `auto_now_add=True`（创建时）和 `auto_now=True`（更新时），Django 自动填入正确 UTC。

### 常见陷阱

| 写法 | 结果 | 判定 |
|------|------|------|
| `datetime.now()` | naive 本地时间，无时区 | ❌ |
| `datetime.now().replace(tzinfo=utc)` | 本地时间数字 + UTC 标签，未转换 | ❌ |
| `datetime.now(timezone.utc)` | 正确 UTC | ✅ |
| `django.utils.timezone.now()` | 正确 UTC | ✅ |