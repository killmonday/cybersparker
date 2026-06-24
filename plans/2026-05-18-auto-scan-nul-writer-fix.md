# 自动扫描 NUL 写库报错修复

- 日期：2026-05-18
- 状态：已完成

## 做什么

修复自动扫描结果写库时，字符串里包含 NUL (`\x00`) 导致 PostgreSQL 拒绝写入、writer 任务失败、自动扫描卡在 99% 的问题。

## 为什么

- Celery `run_result_writer_task` 报错：`ValueError: A string literal cannot contain NUL (0x00) characters.`
- 报错落点在 `result_event_service._write_identify_event()` 创建 `auto_scan_indentify_result`。
- 只要单条识别结果里任一字符串字段带 `\x00`，整条 writer task 就会异常退出，剩余 backlog 无法继续入库。

## 根因

- `build_identify_event_payloads()` / `_write_identify_event()` 之前直接把 `title/header/html/target/ip/protocol/...` 原样写入 PostgreSQL。
- PostgreSQL 文本列不接受 `NUL (0x00)`。
- 单条脏数据会把整批结果入库链路卡死，进而表现为任务 99% 卡住、结果页不增长。

## 已执行修复

- `app_cybersparker/services/result_event_service.py`
  - 新增 `_strip_nul()`，统一清理字符串中的 `\x00`。
  - `_write_identify_event()`：对 `target/product/ip/protocol/country/area/area_name_zh/title/header/html` 清理 NUL 后再写库。
  - `_write_auto_exp_event()`：对 `target/product/result/plugin_name` 清理 NUL。
  - `_write_batch_event()`：对 `target/plugin_name/result` 清理 NUL。
- `app_cybersparker/tests.py`
  - 新增 `test_identify_events_strip_nul_before_db_write`，覆盖带 NUL 的识别结果仍能成功入库。

## 验证

- `python manage.py test --keepdb --noinput app_cybersparker.tests.ResultEventServiceTests.test_identify_events_strip_nul_before_db_write app_cybersparker.tests.ResultWriterTaskTests -v 2`：5/5 通过。
- `python manage.py check`：0 issues。
