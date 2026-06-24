# SOCKS5 代理支持

- 状态：已完成
- 关联 Backlog：BL-PROXY-001（代理配置管理）
- 关联模块：05-代理与运行时配置

## 做什么

后台代理配置新增 SOCKS5 协议类型，让所有出站请求路径都支持 SOCKS5 代理。

## 为什么

当前仅支持 HTTP 代理，用户需要 SOCKS5 代理满足某些网络环境下的出站需求。

## 怎么做

### 1. 模型层 — `app_cybersparker/models.py`
- `ProxySetting.protocol_choices` 新增 `(4, "socks5")`，修正原注释拼写错误

### 2. 依赖 — `requirements.txt`
- 新增 `PySocks`（requests SOCKS 支持）
- 新增 `aiohttp-socks`（aiohttp SOCKS 支持）

### 3. requests 路径（全局 monkey patch + 空间测绘引擎）
- 无需代码改动。`_build_proxy_from_setting()` 动态获取协议名，生成 `socks5://` URL，requests+PySocks 原生支持。

### 4. aiohttp 自动扫描 — `auto_exp_task.py`
- `__init__`：新增 `self.proxy_is_socks5` 标记
- `_request_consumer_async`：SOCKS5 时 `ProxyConnector.from_url()` 替代 `TCPConnector`
- `_fetch_favicon`、请求段：SOCKS5 时跳过 per-request proxy（connector 已处理）

### 5. aiohttp 目录扫描 — `dirscan_worker.py`
- SOCKS5 时 `ProxyConnector.from_url()`，`proxy_url` 置 None 使 per-request 调用跳过

### 6. 模板 — `proxy_setting.html`
- 页面标题从"HTTP代理设置"改为"代理设置"

## 验证

- `python manage.py check` — 0 issues ✓
- ProxySetting `__str__` 返回 `socks5://127.0.0.1:1080` ✓
- `_build_proxy_from_setting` 返回 `{"http": "socks5://...", "https": "socks5://..."}` ✓
- 所有修改模块导入成功 ✓
- `proxy_type` 表单下拉自动包含 socks5（模型 choices 驱动）✓

## 风险

- 低。`aiohttp-socks` ProxyConnector 继承自 TCPConnector，现有参数直接兼容。
