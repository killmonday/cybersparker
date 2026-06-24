# BL-FINGER-005 指纹调试页全异步增强

## 做什么

指纹调试页 `mate()` 改为全异步执行，增加 favicon 爬取、HTTPS 证书抓取、JS 跳转检测，支持 cert/favicon/uri_path 指纹匹配。

## 为什么

- 当前调试页只拿 header+body+title，无法验证 cert/favicon 规则
- 生产引擎缺 uri_path 匹配支持
- 同步 httpx 会阻塞 Django 进程；改为 async + 并发可把 30s 采集压缩到 5-8s

## 怎么改

### 1. `fingerprint_indentify.py`（1 行变更）
- `_context_rule_values()` 增加 `uri_path` 字段

### 2. `auto_exp_task.py`（1 行变更）
- `_build_fingerprint_context()` 增加 `uri_path` 字段

### 3. `fingerPrint_debug.py`（大规模重写）
- `mate()` → `async def`，使用 `httpx.AsyncClient`
- 新增 favicon/cert/JS跳转 三个 async 采集函数
- `asyncio.gather()` 并发执行采集
- `check_rule()` / `handle()` / `evaluate_fingerprint()` / `collect_library_matches()` 增加 context 参数
- 新增 `_match_context_rule()` / `_context_rule_values()` 上下文匹配逻辑
- 采集结果返回 JSON

### 4. `fingerprint_debug.html` + JS
- 新增 favicon 缩略图 / 证书 / URI 路径展示卡片
- 更新规则输入提示文字

## 风险

| 风险 | 缓解 |
|------|------|
| 代码复制双写（调试 vs 生产） | 现状就是两套，不新增问题 |
| `ssl._ssl._test_decode_cert` 是 CPython 内部 API | 生产已用同样逻辑 |
| 调试端点无频率限制 | 内部工具，不新增风险 |
| favicon 多候选 + 证书 + 跳转 = 多 HTTP 请求 | 每步独立超时，单步失败不阻塞 |

## 验证

1. `python manage.py check` 0 issues ✅
2. 14/14 测试通过（7 个已有 + 7 个新增）✅
3. 新增测试覆盖：context matching（cert_org/favicon_md5/uri_path）、inputFingerIsTrue 扩展、资产特征返回、fallback 行为 ✅

## 改动文件

| 文件 | 变更 |
|------|------|
| `fingerPrint_debug.py` | mate() 改为 async，新增 3 个 async 采集函数、context matching 逻辑、前端返回新字段 |
| `fingerprint_indentify.py` | _context_rule_values 增加 uri_path（1 行） |
| `auto_exp_task.py` | _build_fingerprint_context 增加 uri_path（1 行） |
| `fingerprint_debug.html` | 新增资产特征展示卡片、更新 JS 渲染、更新提示文字 |
| `tests.py` | 适配 async 测试 + 新增 7 个 context matching 测试 |
| `docs/backlog/03-指纹与自动识别.md` | 更新 BL-FINGER-005 状态 |
| `CHANGELOG.md` | 新增条目 |
