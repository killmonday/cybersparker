# 批量任务代理 HTTPS 请求 SSLSocket TypeError 修复

- 状态：已完成
- 创建时间：2026-06-04

## 做什么

修复批量任务扫描时 `gevent.monkey.patch_all(ssl=False)` + 代理 + HTTPS 目标触发的 `TypeError: _wrap_socket() argument 'sock' must be _socket.socket, not SSLSocket`。

## 为什么

`ssl=False` 让 gevent 只替换 socket 模块不替换 ssl 模块。urllib3 做 CONNECT 穿透 + SSL 包装时，gevent socket 和原生 `_socket.socket` 类型不一致，C 层 `_wrap_socket` 类型检查失败。

## 怎么做

1. `batch_task_executor.py` 和 `gevent_batch_runner.py`：`ssl=False` → `ssl=True`，追加 `urllib3.util.ssl_.SSLContext` 引用修复防止 TLS setter 递归。
2. `hook_request.py`：`conf.get("proxies", {})` 加 `dict()` 拷贝，用新建 dict 替代原地修改 `conf.proxies`。
3. `request_runtime_config_service.py`：`get_proxy_type_display()` 改为显式映射表 `_proxy_scheme()`，未知值回退 http。
4. `tests.py`：测试断言同步更新。

## 验证

- Django check 0 issues
- RequestRuntimePatchTests / BatchTaskDaemonGuardTests 10/10 通过
- Proxy 相关测试 12/13 通过（1 个预存 fixture 问题）
- Manually confirmed: gevent ssl=True + SSLContext fix → create_urllib3_context no recursion, HTTPS requests OK
