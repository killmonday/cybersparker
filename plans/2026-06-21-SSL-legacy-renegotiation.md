# SSL 兼容性修复：允许旧式 SSL 重新协商

## 做什么

自动扫描任务 HTTP 请求层创建 SSL context 时追加 `OP_LEGACY_SERVER_CONNECT` (0x4) 标志，兼容使用旧式 SSL 重新协商的老旧 HTTPS 服务器。

## 为什么

Celery worker 日志报错：
```
Cannot connect to host xzfy.sft.gxzf.gov.cn:443 ssl:False
[[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED] unsafe legacy renegotiation disabled (_ssl.c:992)]
```
OpenSSL 3.x 默认禁用旧式重新协商。需在 SSL context 层面显式开启。

## 怎么做

修复分两层：

1. 在 `auto_exp_task.py` 中新增 `_create_permissive_ssl_context()` 函数，创建 SSL context 时追加 `ctx.options |= 0x4`（`OP_LEGACY_SERVER_CONNECT`）
2. `_request_consumer_async`：`TCPConnector` 和 `ProxyConnector` 改用自定义 SSL context
3. `_fetch_certificate_info`：改为调用新函数
4. **关键修复**：`request_scan()` 的 `request_kwargs` 中移除 `"ssl": False`——aiohttp 在 per-request 层传 `ssl=False` 时会**忽略 connector 的自定义 SSL context**，自己新建默认 context（不带 0x4），导致 legacy renegotiation 错误再现。隔离探测确认：connector 自定义 context ✓ / connector 自定义 + `ssl=False` ✗

## 风险

- 低。`OP_LEGACY_SERVER_CONNECT` 仅允许旧式重新协商，不影响加密强度。
- 移除 `ssl=False` 后证书验证行为不变——connector 的 context 已有 `check_hostname=False` + `verify_mode=CERT_NONE`。

## 验证结果

- SSL 隔离探测：5 个 probe 确认根因（Probe A OK / Probe B FAIL → ssl=False 覆盖 connector context）
- aiohttp 隔离探测：4 个场景验证修复有效
- 新增 1 个测试（`SslContextLegacyRenegotiationTests`）
- 全量 444 tests 0 fail, 0 errors
- Django check 0 issues

## 修改文件

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`：新增 `_create_permissive_ssl_context()`，更新 3 处 context 创建 + 移除 `request_kwargs["ssl"]`
- `app_cybersparker/tests.py`：新增 `SslContextLegacyRenegotiationTests`
- `CHANGELOG.md`：已记录
