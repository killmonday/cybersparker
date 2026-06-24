# 自动扫描漏洞结果格式兼容修复

- 日期：2026-05-18
- 状态：已完成

## 做什么

修复自动扫描开启漏洞扫描时，`save_exp_result()` 只按 Python POC 结果格式取值，导致 Nuclei YAML 返回结构不兼容而报错的问题。

## 为什么

- 现场日志显示 `save_exp_result()` 在 `target = result_info["target"]` 处报错。
- 说明 `queue_EXP_result` 里的某些结果不是 Python POC 传统结构。
- 自动扫描在开启漏洞扫描时，既会跑 Python POC，也会跑 Nuclei YAML，需要统一适配。

## 根因

- 旧逻辑默认认为 `result_info` 至少包含：`exp_id/target/product/result`。
- 这只适用于 Python POC 风格。
- Nuclei YAML 返回结果更接近 `host/url/matched/detail/output` 组合，不一定有 `target/result`。
- 结果保存阶段直接按 Python POC 格式取值，会在遇到 Nuclei 结果时抛错。

## 已执行修复

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
  - 新增 `_normalize_exp_result()`
  - 同时兼容：
    - Python POC 格式：`exp_id/target/product/result`
    - Nuclei 风格：`exp_id + host/url/target + matched/detail/output`
  - `save_exp_result()` 改为先归一化，再统一调用 `save_exp_result_to_db()`

## 说明

- 本轮是运行时兼容修复，避免两种插件结果结构不同导致自动扫描在漏洞结果保存阶段炸掉。
- 若后续发现新的模板结果字段形状，只需继续扩展 `_normalize_exp_result()`。

## 补充修正

- 现场再次出现 `KeyError('target')`，说明某些 Nuclei 运行时结果并不是 `{target, result}`，而是更接近 `matched-at/matched_at/template-id/template_id/info/extracted-results` 的结构。
- 已将 `_normalize_exp_result()` 扩展为更宽松兼容：优先取 `host/url/matched-at/matched_at/target` 作为目标，`detail/output/template-id/template_id/info/extracted-results` 作为结果详情；完全拿不到目标时，再尝试从 detail 文本里提取 URL。

## 最终根因修正

- 继续排查后确认：问题不只是 `save_exp_result()` 兼容字段名不全，而是更早一层 `exp_consumer()` 在把 Nuclei 结果塞进 `queue_EXP_result` 时，直接透传了 runtime 原始返回对象。
- `nuclei_runtime_engine.run_nuclei_template()` 的真实返回更接近 `list[dict]` / `False`，字典里主要是模板命中信息、payload/extractor 结果和 `extra_info`，并不保证天然带 `target/result`。
- 这意味着仅在 `save_exp_result()` 里猜字段名是不稳定的。真正稳妥的修复点应该放在 `exp_consumer()`：按插件类型先统一结果结构，再入队。

## 最终修复

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`
  - `exp_consumer()` 现在按 `plugin_language` 分流：
    - Python POC：保留旧格式，补 `exp_id/product`
    - Nuclei YAML：直接用当前循环里的 `url` 作为 `target`，把 runtime 返回对象序列化成 `result`，再入队为统一结构 `{exp_id,target,product,result}`
  - `save_exp_result()` / `_normalize_exp_result()` 继续作为兜底兼容层。

## 最终验证

- 直接执行 `AutoScanAsyncRequestTests.test_exp_consumer_normalizes_nuclei_result_before_queueing`：通过。
- 直接执行 `AutoScanAsyncRequestTests.test_save_exp_result_accepts_nuclei_shape`：通过。
- `python manage.py check`：0 issues。
