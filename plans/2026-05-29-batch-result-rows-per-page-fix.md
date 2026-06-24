# 2026-05-29 批量任务结果页 rows_per_page 参数报错修复

## 做什么
- 修复批量任务结果页在切换每页条数时，把 `rows_per_page` 错误当成 ORM 过滤字段，导致 500 的问题。
- 补一条定向回归测试，覆盖 `?page=&rows_per_page=20` 场景。

## 为什么
- `task_result()` 当前在收集搜索参数时只排除了 `page` 和 `per_page`，没有排除前端实际传的 `rows_per_page`。
- 结果就是：请求 `/batch_exploadTask/61/result?page=&rows_per_page=20` 时，代码把 `rows_per_page=20` 放进 `search_dict`，后面拼成 `Q(rows_per_page__icontains='20')`。
- `EXPTask_result` 模型并没有 `rows_per_page` 字段，所以 Django 抛 `FieldError: Cannot resolve keyword 'rows_per_page' into field`。

## 怎么做
1. 在 `batch_exp_task.py` 的 `task_result()` 中，把 `rows_per_page` 一并加入分页参数排除名单。
2. 补一条结果页定向测试：带 `rows_per_page` 参数访问批量任务结果页时应返回 200，不再报 500。

## 风险
- 只影响批量任务结果页搜索参数白名单，不改分页组件本身，也不影响实际查询字段。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchResultViewTests.test_task_result_ignores_rows_per_page_query_param`：1/1 通过
- `python manage.py check`：通过，0 issues

## 结果
- 已完成：批量任务结果页现在会把 `rows_per_page` 视为分页参数，不再误当成 ORM 过滤字段。
- 已完成：补 1 条定向回归测试，覆盖 `/batch_exploadTask/<uid>/result?page=&rows_per_page=20` 场景。

## 后续
- 已同步 backlog / 模块文档 / CHANGELOG。
