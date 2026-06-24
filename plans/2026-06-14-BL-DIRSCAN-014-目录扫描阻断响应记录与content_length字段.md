# BL-DIRSCAN-014 目录扫描阻断响应记录与 content_length 字段

## 做什么

目录扫描 Web 阶段遇到二进制/大文件 URL 时，当前逻辑阻断下载（不浪费带宽），但也不记录任何信息到数据库——导致不知道这个 URL 曾返回过什么。

新增 `content_length` 字段，并将被 Content-Type / Content-Length 阻断的响应也写入 `auto_scan_directory_result`（保留状态码、响应头、内容长度等元信息，body 为空）。

## 为什么

**场景**：目录扫描扫到一个 `/download/xxx.exe`，服务器返回 `200 OK`，`Content-Type: application/octet-stream`，`Content-Length: 3180856`。当前 `_http_get` 识别到 Content-Type 不在白名单 → 返回 body="" → `_fingerprint_and_write` 里 `body_len < 50` → 跳过写库 → 这条 URL 在结果页完全看不到，用户不知道这个路径曾返回过一个 3MB 的 exe 文件。

## 怎么做

### 数据模型

`auto_scan_directory_result` 新增 `content_length = IntegerField(null=True, blank=True)`。

### 核心逻辑改动

1. `_http_get`：提取 Content-Length 头，返回值从 4 元组改为 5 元组（增加 content_length）
2. `_fingerprint_and_write`：区分"阻断响应"（status>0 但 body 为空）和"网络错误"（status=0）。阻断响应跳过 hash 去重直接写库，写入时带 content_length
3. `_sync_fingerprint_and_write`：接收并存储 content_length 到 ORM
4. API 序列化点：两个返回 directory_result 的接口加 `content_length` 字段

### 文件清单

| 文件 | 改动 |
|------|------|
| `models.py` | 新增 content_length IntegerField |
| `migrations/0055_*` | 自动生成迁移 |
| `dirscan_worker.py` | `_http_get` 返回 5 元组、`_fingerprint_and_write` 阻断路径写库、`_sync_fingerprint_and_write` 存 content_length、所有调用点传参更新 |
| `auto_scan_result.py` | 两个 API 响应序列化加 content_length |
| `probe_test_binary_block.py` | 独立 Probe 验证脚本（不入库） |

## 风险

- 低。改动仅在 `dirscan_worker.py` 内部，不影响其他模块。新增字段可为 null，向后兼容。
- 阻断响应跳过 hash 去重，同 URL 重复扫到仍走 `update_or_create`（by unique key），不会产生重复记录。

## 验证

- [x] Django migration 成功（0055_add_dirscan_content_length）
- [x] Python 语法检查通过
- [x] Probe 脚本验证：对目标 URL 正确识别 Content-Type 阻断、Content-Length 阻断、模拟 _fingerprint_and_write 判定为 WRITE_BLOCKED
- [x] Django check 0 issues

## 状态

- 2026-06-14：实现完成并验证通过。
