# ERR_NO_BUFFER_SPACE — socket 连接累积修复

## 问题

任务跑起来后，哪怕只开 35 个线程，过几分钟主机浏览器访问任意页面出现 `ERR_NO_BUFFER_SPACE`。

## 根因（修正后）

第一次分析错了方向——`force_close=True` 反而让问题更严重。

**真正原因**：自动扫描每个 URL 不只一次 HTTP 请求——主请求 + favicon 候选（最多 5 个）+ JS 跳转（最多 1 个），每个 URL 可达 7 次 `session.get()`。

- `force_close=True` → 7 次请求各走独立 TCP + TLS 握手 → 35 并发 × 7 = **245 个连接/批次** → 大量 TIME_WAIT → 更快打满内核缓冲区
- `keepalive_timeout=2.0` → 同一 host 的 favicon/跳转复用同一条连接 → 35 并发 × 1 = **35 个连接/批次** → 连接闲置 2 秒后关闭 → 不累积

此外 `aiohttp 3.14.1` 的 `enable_cleanup_closed` 默认 `False`，被远端关闭的连接会残留不被回收。

## 修复（第二轮）

### fix 1 — `auto_exp_task.py`：`force_close=True` → `keepalive_timeout=2.0`
- TCPConnector 加 `keepalive_timeout=2.0` + `enable_cleanup_closed=True`
- ProxyConnector（SOCKS5）加 `keepalive_timeout=2.0`
- **保留** `_fetch_certificate_info` 的 `ensure_future` + `cancel` 防超时泄漏

### fix 2 — `dirscan_worker.py`：同样把 `force_close=True` 改为 `keepalive_timeout=2.0`
- 目录扫描全击中同一 host，keep-alive 复用价值最大

### fix 3 — `fingerPrint_debug.py`：证书连接超时泄漏修复（保留）

## 风险

低。连接复用不改变 HTTP 语义，TLS 握手减少反而降低 CPU 开销。

## 已有测试回归

226 测试中 10 fail + 3 error，全部是修改前就存在的已有问题。
