# fix: auto scan 任务自动使用系统环境代理

## 问题
`requests` 库的 `merge_environment_settings()` 会从系统环境变量（`HTTP_PROXY`/
`HTTPS_PROXY`）读取代理，通过 `proxies.setdefault()` 注入。即使业务层明确不配置代理
（`proxies={}`），环境变量中的代理仍会被合并进去。

## 修复位置
`app_cybersparker/lib/request_runtime/patch/hook_request.py:80-86`

当 `proxies` 为空（无 DB 代理配置、无显式代理）时，显式将 `http`/`https` 键设为 `None`，
使 `setdefault` 跳过这些键，阻止环境代理注入。

## 风险
低。仅影响 monkey patch 的代理合并逻辑，不影响其他配置（verify/cookies/headers）。

## 结果
- 修复：`hook_request.py` 增加 3 行（空代理时设 http/https=None）
- 测试：`tests.py` 更新 1 条断言（空代理期望着含 None 键），15/15 全部通过
- 影响分析：LOW 风险，monkey patch 无直接调用者依赖
