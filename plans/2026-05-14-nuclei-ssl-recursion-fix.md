# 2026-05-14 Nuclei HTTP 请求 SSL 递归修复

## 问题

Nuclei YAML 运行时执行 HTTP 请求时，`requests` 经代理建立 HTTPS 连接，进入 urllib3 创建 SSL context 流程后触发 `ssl.SSLContext.minimum_version` 递归，最终抛出 `RecursionError: maximum recursion depth exceeded`。

## D-lite 例外说明

本次是通过 `/project-control-plane` 进入的小范围运行时行为修复：预期只涉及请求运行时 patch / Nuclei HTTP 执行链路，不变更数据库 schema、公开 API、认证安全策略或跨模块契约；没有新增正式 backlog item，按 Mode D-lite 执行。

## 假设

- 报错根因更可能在请求运行时 monkey patch 对 `ssl.SSLContext` 或 requests 代理流程的改写，而不是 Nuclei YAML 模板解析。
- 修复应保持现有请求参数、代理、超时、证书验证语义不变，只消除递归 patch。

## 影响面

- GitNexus `_execute_http_request` upstream：LOW，直接调用者 `run_nuclei_template`，间接影响 `EXP_plugin/__yaml_runtime__/` 生成的 `_verify`。
- GitNexus `session_request` upstream：LOW，未发现索引内上游调用者。
- GitNexus `_ensure_gevent_patch` upstream：LOW，直接调用者 `_run_gevent_mode`，向上到 `Task_handler.run` / `run_task_in_subprocess`。

## 最小方案

1. 阅读 `hook_request.py` 中 SSL / requests monkey patch 逻辑与 `nuclei_runtime_engine.py` HTTP 执行逻辑。
2. 定位导致 `SSLContext.minimum_version` descriptor 自递归的 patch 点。
3. 仅替换为安全、幂等且不重入的实现。
4. 用定向脚本复现/验证 `create_urllib3_context()` 不再触发递归；运行 Django check 或相关导入检查。

## 风险

- 如果运行环境已有第三方库修改过 `ssl.SSLContext`，需要避免覆盖其预期行为。
- 如果测试环境无法访问真实代理，只能验证 SSL context 创建和请求参数链路，不做外部网络请求。

## 验证记录

- `python - <<'PY' ... create_urllib3_context() ... PY`：通过，输出 `SSLContext TLSv1_2`，说明 gevent patch 后 urllib3 TLS context 不再触发 `minimum_version` 递归。
- `python manage.py test app_cybersparker.tests.RequestRuntimePatchTests`：通过，5 tests OK，新增断言覆盖 `_ensure_gevent_patch()` 调用 `monkey.patch_all(thread=False, subprocess=False, ssl=False)`。
- `python manage.py check`：通过，System check identified no issues。
- `simplify` 审查：已完成；采纳“测试内惰性导入 Task_handler”建议。关于批量任务进度写库节流/百分比恢复精度的反馈属于本轮 SSL 修复以外的既有未提交进度改动，未在本次扩展修复；已记录到 `docs/后续开发事项.md`。

## 结果

- 已将协程模式的 `gevent.monkey.patch_all()` 改为跳过 SSL patch，避免在 Django/requests/ssl 已加载后重写 `ssl.SSLContext` 导致 Python 3.11 `minimum_version` descriptor 递归。
- 未修改 Nuclei YAML 请求构造、代理配置、证书验证参数或数据库模型。
- 未做真实外网/代理端到端请求验证；当前证据覆盖 SSL context 创建链路和 Django 单元测试。
