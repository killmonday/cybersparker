# 2026-05-29 批量任务跳过不支持的 nuclei code 协议

## 做什么
- 修复批量任务执行 Nuclei YAML 插件时，`protocol=code` 这类当前不支持的模板被误当成成功结果入库的问题。
- 让这类模板在批量任务里直接跳过，不进入结果队列。
- 补回归测试，覆盖“不支持协议跳过”和“正常命中仍能入队”两种场景。

## 为什么
- 现在 YAML 包装层 `_build_yaml_wrapper()._verify()` 在遇到 `unsupported nuclei protocol: code` 时，会返回 `RuntimeMethodResult({"matched": False, "result": "unsupported ..."})`。
- 自动扫描链路在 `call_runtime_method()` 之后先 `if not result: continue`，因此 `matched=False` 的 YAML 返回会直接跳过。
- 批量任务 `Task_handler.consumer_exp()` 没有这层判断，只要拿到 dict 就会 `queue_output.put(result)`；后面的 `save_TaskResult()` 又只看 `target/result` 是否存在，于是把“未命中但带错误文字”的结果当成了有效验证结果入库。
- 具体场景：用户拿 `OSS Bucket Public Accessible` 这类 `protocol=code` 的 nuclei 模板跑批量任务，页面看到“成功验证”，数据库里结果是 `unsupported nuclei protocol: code`，这与预期“直接跳过、不参与任务”相反。

## 怎么做
1. 仅修改批量任务 `batch_task_executor.py` 的 `Task_handler.consumer_exp()`：
   - 调 `call_runtime_method()` 后，先判断 `if not result: continue`。
   - 这样 `RuntimeMethodResult({'matched': False, ...})` 不再进入 `queue_output`。
2. 保留现有 `python3` 插件和 `nuclei_yaml` 真命中入队逻辑，不改 `save_TaskResult()` 入库格式。
3. 补 3 条定向测试：
   - `protocol=code` / `matched=False` 的 YAML 返回不会入队
   - `matched=True` 的 YAML 返回仍会入队并带上 plugin 名
   - python3 普通 `dict` 即使带 `matched=False` 字段也不受影响，仍按原逻辑入队

## 风险
- 只影响批量任务结果入队判定，不改 nuclei 引擎本身，也不改自动扫描/单任务链路。
- 如果写错条件，可能把 python3 命中结果也跳过，所以要用回归测试明确卡住 dict 命中场景。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchRuntimeResultCompatibilityTests.test_batch_consumer_accepts_runtime_method_result_subclass app_cybersparker.tests.BatchRuntimeResultCompatibilityTests.test_batch_consumer_skips_unmatched_runtime_method_result app_cybersparker.tests.BatchRuntimeResultCompatibilityTests.test_batch_consumer_keeps_plain_dict_result_even_if_matched_false`：3/3 通过
- `python manage.py check`：通过，0 issues
- 独立复核后再次收紧判定：仅跳过 `RuntimeMethodResult` 且 `matched=False` 的 YAML 返回，不误伤 python3 普通 dict

## 结果
- 已完成：批量任务 `consumer_exp()` 现在只会跳过 `RuntimeMethodResult` 且 `matched=False` 的 YAML 返回，`protocol=code` 这类当前不支持的 nuclei 模板不再进入结果队列。
- 已完成：保留 `matched=True` 的 YAML 真命中入队逻辑，也保留 python3 普通 dict 的原有入队行为，不改 `save_TaskResult()` 入库格式。
- 已完成：补 3 条定向回归测试，覆盖“不支持协议跳过”“正常命中仍入队”“python3 普通 dict 不误伤”。

## 后续
- 已同步 `docs/backlog/02-任务执行.md`、`docs/modules/02-任务执行模块.md`、`CHANGELOG.md`。
