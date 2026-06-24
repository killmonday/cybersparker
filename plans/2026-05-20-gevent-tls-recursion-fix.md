# 批量任务 gevent TLS 递归崩溃修复

- 状态：已完成
- 创建时间：2026-05-20

## 做什么

修复批量任务 `run_mode=2` 在 Celery worker 中执行 requests/urllib3 HTTPS 请求时，触发 `SSLContext.minimum_version` 无限递归并最终 `RecursionError` 的问题。

## 为什么

最新错误栈发生在 `nuclei_runtime_engine.py -> requests -> urllib3 -> ssl.py`。项目里之前其实已经修过同类问题，结论是 gevent patch 不能再碰 SSL；但当前代码又回到了 `monkey.patch_all(thread=False, subprocess=False)`，等于把 SSL patch 又打开了，所以在 Python 3.11 下再次触发 TLS setter 递归。

## 怎么做

1. 对照历史修复记录，确认 gevent monkey patch 的 `ssl=False` 约束被回退。
2. 将 `batch_task_executor.Task_handler._ensure_gevent_patch()` 和 `gevent_batch_runner.py` 的 patch 参数统一改回 `ssl=False`。
3. 同步更新对应测试断言，确认 gevent patch 参数和 TLS context 创建链路都符合预期。
4. 用 `/opt/venv/bin/python` 跑定向回归。

## 风险

- 这条链路同时涉及 gevent、requests、urllib3 和项目自己的 request runtime patch，误改容易放大影响。
- 本次修复只收口 gevent patch 参数，不改 Nuclei 运行时请求构造、代理传递、超时和证书验证语义。
- 当前没有真实外网目标端到端复测，证据以代码级和定向测试为主。

## 验证

- [x] `/opt/venv/bin/python manage.py test app_cybersparker.tests.RequestRuntimePatchTests app_cybersparker.tests.BatchTaskDaemonGuardTests --keepdb --noinput -v 2` 10/10 通过。
- [x] `/opt/venv/bin/python - <<'PY' ... create_urllib3_context() ... PY` 通过，能正常输出 `SSLContext`，不再递归。
- [x] `/opt/venv/bin/python manage.py check` 0 issues。

## 结果

- gevent monkey patch 已统一改为 `thread=False, subprocess=False, ssl=False`。
- 批量任务 `run_mode=2` 的 daemon worker 防护仍保留，和这次 TLS 修复不冲突。
- `RequestRuntimePatchTests` 的 gevent patch 断言已同步更新，`BatchTaskDaemonGuardTests` 继续覆盖 daemon worker 防护分支。

## 风险复盘

- 这次根因不是 Nuclei YAML 本身，也不是业务请求参数，而是 gevent SSL patch 被回退后重新影响了 Python 3.11 的 TLS context setter。
- 定向测试中顺手修了一个旧的测试辅助对象构造问题，使回归集能稳定跑完；这不是新功能变更。

## 下一步

- 建议你在真实 worker 环境再跑一遍之前会报错的 `run_mode=2` 批量任务，重点看 HTTPS 目标是否还会出现 `minimum_version` 递归堆栈。
