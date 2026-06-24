# Pocsuite3 Requests 库 Patch 改造详解

本文档详细记录了 pocsuite3 对 Python `requests` 库的 patch 改造，包括各个 patch 的功能、实现原理和使用注意事项。

## 目录

1. [Patch 概述](#1-patch-概述)
2. [各 Patch 详细说明](#2-各-patch-详细说明)
3. [常见问题解答](#3-常见问题解答)
4. [使用示例](#4-使用示例)

---

## 1. Patch 概述

### 1.1 Patch 加载机制

```python
# pocsuite3/lib/request/__init__.py
import requests
from pocsuite3.lib.request.patch import patch_all

patch_all()  # 导入时自动应用所有 patches
```

### 1.2 Patch 列表

| Patch 文件 | 功能说明 |
|-----------|---------|
| `remove_ssl_verify.py` | 全局禁用 SSL 证书验证 |
| `remove_warnings.py` | 禁用 urllib3 不安全请求警告 |
| `hook_request.py` | 重写 `Session.request` 方法 |
| `add_httpraw.py` | 添加原始 HTTP 报文发送功能 |
| `hook_request_redirect.py` | 修复重定向 Location 编码问题 |
| `hook_urllib3_parse_url.py` | 重写 URL 解析函数 |
| `unquote_request_uri.py` | 修改 URL 编码/解码逻辑 |

---

## 2. 各 Patch 详细说明

### 2.1 SSL 验证禁用 (`remove_ssl_verify.py`)

```python
import ssl

def remove_ssl_verify():
    ssl._create_default_https_context = ssl._create_unverified_context
```

**作用**：全局创建不验证证书的 HTTPS 上下文。

**注意**：注释中提到 `It doesn't seem to work. 09/07/2022`，实际 SSL 验证主要通过 `Session.request` 的 `verify=False` 参数控制。

---

### 2.2 警告禁用 (`remove_warnings.py`)

```python
from urllib3 import disable_warnings
disable_warnings()
```

**作用**：关闭 urllib3 的不安全请求警告输出。

---

### 2.3 Session.request 重写 (`hook_request.py`)

这是最重要的 patch，完全替换了 `requests.Session.request` 方法。

#### 2.3.1 默认参数变更

```python
def session_request(self, ..., verify=False, ...):
```

| 参数 | 原生默认值 | Patch 后 | 说明 |
|-----|-----------|---------|------|
| `verify` | `True` | `False` | 默认不验证 SSL 证书 |

#### 2.3.2 Header 合并逻辑 - `_merge_retain_none`

```python
def _merge_retain_none(request_setting, session_setting, dict_class=OrderedDict):
    if session_setting is None:
        return request_setting
    if request_setting is None:
        return session_setting
    if not (isinstance(session_setting, Mapping) and isinstance(request_setting, Mapping)):
        return request_setting

    merged_setting = dict_class(to_key_val_list(session_setting))
    merged_setting.update(to_key_val_list(request_setting))
    return merged_setting
```

**问题背景**：原生 requests 合并 headers 时会过滤掉值为 `None` 的 header。

```python
# 原生行为
requests.get(url, headers={'X-Auth': None})
# 实际上不会发送 X-Auth header

# Patch 后：如果 conf.http_headers = {'X-Auth': None}
# 会保留这个 header，服务器收到 X-Auth: （空值）
```

**用途**：某些 WAF/IDS 检测逻辑中，header 存在但为空 vs header 不存在，行为可能不同。

#### 2.3.3 全局配置集成

```python
# Cookie 合并（三层）
merged_cookies = merge_cookies(
    merge_cookies(RequestsCookieJar(), self.cookies),  # Session cookies
    cookies or conf.get('cookie', None)                 # 请求参数 + 全局配置
)

# Header 合并（优先级：请求参数 > 全局配置）
headers=_merge_retain_none(headers, conf.get('http_headers', {}))

# 随机 User-Agent（当未指定时）
if not conf.get('agent', '') and HTTP_HEADER.USER_AGENT not in conf.http_headers:
    conf.http_headers[HTTP_HEADER.USER_AGENT] = generate_random_user_agent()

# 代理配置
if proxies is None:
    proxies = conf.get('proxies', {})

# 超时时间（默认 10 秒）
timeout = timeout or conf.get("timeout", 10)
```

**架构设计**：通过 `conf` 对象实现全局配置，避免每个请求重复传参。

#### 2.3.4 协议修复（关键功能）

```python
pr = urlparse(url)
if pr.scheme.lower() not in ['http', 'https']:
    url = pr._replace(
        scheme='https' if str(pr.port).endswith('443') else 'http'
    ).geturl()
```

**场景**：用户输入 `ftp://target.com:8080/path` 或 `unknown://target.com`

| 输入 | 修复后 | 说明 |
|------|--------|------|
| `ftp://x.com:443/path` | `https://x.com:443/path` | 443 端口 → https |
| `ftp://x.com:8080/path` | `http://x.com:8080/path` | 其他端口 → http |
| `unknown://x.com/path` | `http://x.com/path` | 未知协议 → http |

**目的**：避免 `No connection adapters were found for 'ftp://...'` 错误。

#### 2.3.5 响应编码自动检测

```python
if resp.encoding == 'ISO-8859-1':
    encodings = get_encodings_from_content(resp.text)
    if encodings:
        encoding = encodings[0]
    else:
        encoding = resp.apparent_encoding
    resp.encoding = encoding
```

**问题背景**：
- requests 默认使用 `ISO-8859-1`（Latin-1）解码响应
- 中文网站会显示乱码

**修复逻辑**：
1. 检查 HTTP Response header 中的 `Content-Type: text/html; charset=utf-8`
2. 如果没有，使用 chardet 检测页面实际编码
3. 设置 `resp.encoding`，后续 `resp.text` 使用正确编码

---

### 2.4 HTTP Raw 请求支持 (`add_httpraw.py`)

新增 `requests.httpraw()` 方法，支持发送原始 HTTP 报文。

#### 2.4.1 函数签名

```python
def httpraw(raw: str, ssl: bool = False, **kwargs) -> Response
```

#### 2.4.2 使用方法

```python
import requests
from pocsuite3.api import init_pocsuite

init_pocsuite()  # 必须先初始化

# 原始 HTTP 报文字符串
raw = '''
POST /api/login HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded
X-Custom-Header: value

username=admin&password=123456
'''

# 发送请求
response = requests.httpraw(raw, ssl=True)  # ssl=True 表示 HTTPS
```

#### 2.4.3 自动解析逻辑

```python
# 1. 解析请求行：METHOD PATH PROTOCOL
POST /api/login HTTP/1.1
#    ↑方法  ↑路径        ↑协议（可省略）

# 2. 解析 Headers（空行之前）
Host: target.com          → 提取 Host 构建完整 URL
Content-Type: xxx         → 作为请求 headers

# 3. 解析 Body（空行之后）
# GET 请求：没有 body
# POST 请求：
#   - 如果能 json.loads() 成功 → 作为 json 参数发送
#   - 否则 → 作为 data 参数发送
```

#### 2.4.4 使用场景

1. **复制浏览器请求**：直接从浏览器 DevTools 复制为 raw HTTP 格式
2. **测试 HTTP 请求走私**：精确控制 header 和 body 的分隔
3. **发送畸形请求**：构造非标准的 HTTP 报文
4. **快速复现 POC**：避免用代码拼接复杂请求结构

---

### 2.5 重定向编码修复 (`hook_request_redirect.py`)

修复 GitHub issue #4926：Location header 编码问题。

```python
def get_redirect_target(self, resp):
    if resp.is_redirect:
        location = resp.headers['location']
        if is_py3:
            location = location.encode('latin1')

        # 尝试多种编码解码
        encoding_list = ['utf-8']
        if resp.encoding and resp.encoding not in encoding_list:
            encoding_list.append(resp.encoding)
        if resp.apparent_encoding and resp.apparent_encoding not in encoding_list:
            encoding_list.append(resp.apparent_encoding)
        encoding_list.append('latin1')

        for encoding in encoding_list:
            try:
                return to_native_string(location, encoding)
            except Exception:
                pass
    return None
```

**场景**：
- 服务器返回 `Location: /登录`（UTF-8 中文）
- 服务器返回 `Location: /%C4%E3`（GBK 编码）

原生 requests 只尝试 latin1 解码，可能乱码或失败；patch 后尝试多种编码。

---

### 2.6 URL 解析修复 (`hook_urllib3_parse_url.py`)

完全重写 `urllib3.util.parse_url` 函数，修复 urllib3 issue #1790。

**改进点**：
- 更好的 IPv6 支持
- 处理 auth 信息
- 特殊字符的 URL 解析

通过直接替换 `__code__` 实现 monkey patch：

```python
def patch_urllib3_parse_url():
    try:
        urllib3.util.parse_url.__code__ = patched_parse_url.__code__
    except Exception:
        pass
```

---

### 2.7 URL 编码处理 (`unquote_request_uri.py`)

修改 URL 编码/解码逻辑，这是**最核心的安全测试相关 patch**。

#### 2.7.1 修改的函数

| 函数 | 原生行为 | Patch 后行为 |
|-----|---------|-------------|
| `requote_uri` | 完全解码 → 重新编码 | 只解码 unreserved 字符 |
| `_encode_target` | 对 path 进行 `%XX` 编码 | **原样返回，不编码** |

#### 2.7.2 关键代码

```python
def patched_encode_target(target):
    return target  # 直接返回，不做任何编码！

def unquote_request_uri():
    requests.utils.requote_uri.__code__ = patched_requote_uri.__code__
    urllib3.util.url._encode_target.__code__ = patched_encode_target.__code__
```

#### 2.7.3 编码差异对比

| 输入 URL | 原生 requests 发送 | Patch 后发送 |
|---------|-------------------|-------------|
| `http://x.com/a b` | `GET /a%20b` | `GET /a b`（空格不编码） |
| `http://x.com/%2520` | `GET /%20`（解码一次） | `GET /%2520`（保持双编码） |
| `http://x.com/<script>` | `GET /%3Cscript%3E` | `GET /<script>`（原样） |
| `http://x.com/你好` | `GET /%E4%BD%A0%E5%A5%BD` | `GET /你好`（中文不编码） |
| `http://x.com/a#b` | `GET /a`（#截断） | `GET /a#b`（#保留） |

#### 2.7.4 渗透测试场景价值

```python
# 场景1：命令注入
requests.get("http://target.com/lookup;id")
# 原生：分号编码为 %3B，服务器收到 lookup%3Bid
# Patch：分号原样，服务器收到 lookup;id → 触发注入

# 场景2：路径遍历的双编码绕过
requests.get("http://target.com/%252e%252e%252fetc%252fpasswd")
# 原生：变成 %2e%2e%2fetc%2fpasswd（单层编码）
# Patch：保持 %252e%252e%252fetc%252fpasswd（双层编码，绕过某些过滤）

# 场景3：HTTP 请求走私
raw_path = "/ HTTP/1.1\r\nHost: evil.com\r\n\r\nGET /admin"
# Patch 允许发送这种畸形 path
```

#### 2.7.5 注意事项

- **params 参数仍然编码**：`requests.get("http://x.com/search", params={"q": "a b"})` 会发送 `q=a%20b`
- **手动拼接才不编码**：`requests.get("http://x.com/search?q=a b")` 发送 `q=a b`
- **兼容性问题**：不符合 RFC 标准，某些严格的服务器可能返回 400

---

### 2.8 Chunked 传输修复 (`__init__.py`)

```python
def _update_chunk_length(self):
    if self.chunk_left is not None:
        return
    line = self._fp.fp.readline()
    line = line.split(b";", 1)[0]
    if not line:
        self.chunk_left = 0
        return
    try:
        self.chunk_left = int(line, 16)
    except ValueError:
        # Invalid chunked protocol response, abort.
        self.close()
        raise PocsuiteIncompleteRead(line)
```

**问题背景**：原生 urllib3 处理 chunked 传输时，如果服务器返回非标准的 chunk size 行（不是纯十六进制数字），会抛出 `ValueError`。

**改进**：增加了错误处理，抛出自定义异常 `PocsuiteIncompleteRead`，让错误更可追踪。

**场景**：某些 WAF、CDN 或畸形响应会返回非标准 chunk size。

---

## 3. 常见问题解答

### Q1: Chunked 分块传输本来有编码解析问题吗？

**答**：原生的 urllib3 在处理 chunked 传输时，**如果服务器返回了非标准的 chunk size 行（比如不是纯十六进制数字）**，urllib3 会抛出 `ValueError` 导致解析失败。

pocsuite3 的 patch 增加了 try-except 错误处理，捕获 `ValueError` 并抛出更具体的 `PocsuiteIncompleteRead` 异常。

```python
try:
    self.chunk_left = int(line, 16)
except ValueError:
    self.close()
    raise PocsuiteIncompleteRead(line)
```

---

### Q2: URL 编码处理现在是不会自动 URL 编码了吗？

**答**：patch 后 **path 部分不自动编码**，但其他部分仍有编码处理。

详细变化：

1. **`_encode_target` 直接返回原值**：path 中的特殊字符（空格、中文、`#` 等）不会被自动编码
2. **`requote_uri` 保守处理**：只解码 unreserved 字符（`A-Za-z0-9-._~`），保留 reserved 字符编码

**注意**：`params` 参数仍然会自动编码：

```python
# 这个不受影响，仍然编码
requests.get("http://x.com/search", params={"q": "a b"})
# 发送 q=a%20b

# 手动拼接才是不编码的
requests.get("http://x.com/search?q=a b")
# 发送 q=a b
```

---

### Q3: `httpraw` 如何使用？

**答**：详细用法如下：

```python
import requests
from pocsuite3.api import init_pocsuite

init_pocsuite()  # 必须先初始化，加载 patches

# 原始 HTTP 报文字符串（空行分隔 headers 和 body）
raw = '''
POST /api/login HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded
X-Custom-Header: value

username=admin&password=123456
'''

# 发送请求
response = requests.httpraw(raw, ssl=True)  # ssl=True 表示 HTTPS
print(response.status_code)
print(response.text)
```

**参数说明**：

| 参数 | 类型 | 说明 |
|-----|------|------|
| `raw` | str | 原始 HTTP 请求报文（包含请求行、headers、可选 body） |
| `ssl` | bool | 是否使用 HTTPS，默认 False |
| `**kwargs` | - | 额外的 requests 参数（timeout、proxies 等） |

**自动解析逻辑**：
1. 解析请求行：`METHOD PATH PROTOCOL`
2. 解析 Headers（空行之前）
3. 解析 Body（空行之后）：
   - GET 请求：没有 body
   - POST 请求：
     - 如果能 `json.loads()` 成功 → 作为 json 参数发送
     - 否则 → 作为 data 参数发送

---

### Q4: Patch 后的 URL 编码，对 HTTP 请求的发送和响应中的 URL 的编码分别有什么变化？

**答**：

#### 请求发送的变化

**关键变化在 `_encode_target`**：

```python
def patched_encode_target(target):
    return target  # 直接返回，不做任何编码！
```

| 输入 URL | 原生 requests 发送 | Patch 后发送 |
|---------|-------------------|-------------|
| `http://x.com/a b` | `GET /a%20b` | `GET /a b`（空格不编码） |
| `http://x.com/%2520` | `GET /%20`（解码一次） | `GET /%2520`（保持双编码） |
| `http://x.com/<script>` | `GET /%3Cscript%3E` | `GET /<script>`（原样） |
| `http://x.com/你好` | `GET /%E4%BD%A0%E5%A5%BD` | `GET /你好`（中文不编码） |
| `http://x.com/a#b` | `GET /a`（#截断） | `GET /a#b`（#保留） |

#### 响应中 URL 的处理

**重定向 Location Header**：

`hook_request_redirect.py` 修复了编码解码问题：

```python
# 问题：服务器返回非标准编码的 Location
Location: /登录      # UTF-8 编码的中文
Location: /%C4%E3   # GBK 编码（非标准）

# 原生 requests：只尝试 latin1 解码，可能乱码或失败
# Patch 后：尝试多种编码
encoding_list = ['utf-8', resp.encoding, resp.apparent_encoding, 'latin1']
```

**响应体中的 URL**：

Patch 不影响，需要手动处理：

```python
response = requests.get("http://target.com")
html = response.text
# 从中提取的 URL 需要自己编码/解码处理
```

#### URL 各部分的处理

| URL 部分 | Patch 处理 | 示例 |
|---------|-----------|------|
| scheme | 小写化 | `HTTP://` → `http://` |
| host | 小写化 | `EXAMPLE.COM` → `example.com` |
| **path** | **不编码，原样发送** | `/a b` → `/a b` |
| query | 依赖 requote_uri | `/a%20b` → `/a%20b`（保留） |
| fragment | 可能被保留 | `#frag` → `#frag` |

---

### Q5: `Session.request` 方法的修改点有哪些？

**答**：详细修改点如下：

#### 1. 默认参数变更

```python
def session_request(self, ..., verify=False, ...):
```

| 参数 | 原生默认值 | Patch 后 |
|-----|-----------|---------|
| `verify` | `True` | `False` |

#### 2. Header 合并逻辑 - `_merge_retain_none`

保留值为 `None` 的 header，不被过滤。

#### 3. 全局配置集成

```python
# Cookie 合并（三层优先级）
merged_cookies = session.cookies + conf.cookie + 参数cookies

# Header 合并（优先级：请求参数 > 全局配置）
headers = _merge_retain_none(headers, conf.http_headers)

# 随机 User-Agent
if not conf.agent and HTTP_HEADER.USER_AGENT not in conf.http_headers:
    conf.http_headers[HTTP_HEADER.USER_AGENT] = generate_random_user_agent()

# 代理配置
if proxies is None:
    proxies = conf.get('proxies', {})

# 超时时间（默认 10 秒）
timeout = timeout or conf.get("timeout", 10)
```

#### 4. 协议修复

```python
pr = urlparse(url)
if pr.scheme.lower() not in ['http', 'https']:
    url = pr._replace(
        scheme='https' if str(pr.port).endswith('443') else 'http'
    ).geturl()
```

自动修复非标准协议 URL。

#### 5. 响应编码自动检测

```python
if resp.encoding == 'ISO-8859-1':
    encodings = get_encodings_from_content(resp.text)
    resp.encoding = encodings[0] if encodings else resp.apparent_encoding
```

#### 修改前后对比表

| 特性 | 原生 requests | Patch 后 |
|------|--------------|----------|
| SSL 验证 | 默认启用 | 默认禁用 |
| Header 为 None | 被过滤 | 保留发送 |
| User-Agent | 默认 `python-requests/xxx` | 随机生成 |
| 非标准协议 URL | 抛出异常 | 自动修复为 http/https |
| 中文编码 | 可能乱码 | 自动检测 |
| Cookie 管理 | 仅 session + 参数 | 增加全局配置层 |
| 代理 | 仅参数/env | 增加全局配置 |
| 超时 | 无默认 | 默认 10 秒 |

---

### Q6: 执行 requests 时传入了参数 `proxies`，此时会使用传入的 `proxies` 还是全局 `conf` 定义的代理？

**答**：使用传入的参数，全局配置作为 fallback。

代码逻辑：

```python
if proxies is None:
    proxies = conf.get('proxies', {})
```

**优先级：参数传入 > 全局配置**

| 调用方式 | 最终使用的代理 |
|---------|--------------|
| `requests.get(url)` | `conf.proxies` |
| `requests.get(url, proxies=None)` | `conf.proxies` |
| `requests.get(url, proxies={})` | `{}` (空字典，不使用代理) |
| `requests.get(url, proxies={'http': 'http://1.2.3.4:8080'})` | 传入的代理 |

只有当 `proxies` 参数为 `None`（未传入或显式传 None）时，才会使用 `conf.proxies`。

---

## 4. 使用示例

### 4.1 基本使用

```python
from pocsuite3.api import requests, init_pocsuite

init_pocsuite()

# 自动使用全局配置（代理、超时、随机 UA 等）
response = requests.get("https://target.com/api")
```

### 4.2 发送原始 HTTP 报文

```python
raw = '''
GET /admin HTTP/1.1
Host: target.com
X-Forwarded-For: 127.0.0.1

'''
response = requests.httpraw(raw, ssl=True)
```

### 4.3 利用不编码特性发送 Payload

```python
# 命令注入 - 分号不会编码
requests.get("http://target.com/lookup;id")

# 双编码绕过
requests.get("http://target.com/%252e%252e%252fetc%252fpasswd")

# 特殊字符
requests.get("http://target.com/search?q=<script>alert(1)</script>")
```

### 4.4 配置全局代理

```python
from pocsuite3.lib.core.data import conf

conf.proxies = {
    'http': 'http://127.0.0.1:8080',
    'https': 'https://127.0.0.1:8080'
}

# 后续请求自动使用代理
requests.get("http://target.com")  # 走代理

# 单个请求覆盖
requests.get("http://target.com", proxies={})  # 不走代理
```

---

## 5. 注意事项

1. **RFC 兼容性**：path 不编码的改动不符合 RFC 标准，某些严格的服务器可能返回 400
2. **需要编码时要手动处理**：
   ```python
   from urllib.parse import quote
   safe_path = quote(user_input, safe='/')
   requests.get(f"http://x.com{safe_path}")
   ```
3. **必须先调用 `init_pocsuite()`** 才能使用 `httpraw` 等功能
4. **Session 复用**：`session_reuse.py` 提供了连接池功能（虽然本次分析未详细展开）

---

## 6. 总结

Pocsuite3 的 requests patch 主要服务于渗透测试场景：

| 目标 | 实现方式 |
|-----|---------|
| 发送非常规请求 | `_encode_target` 不编码 |
| 绕过 WAF | 双编码保持、特殊字符原样发送 |
| 全局配置管理 | `conf` 对象集成 |
| 协议兼容性 | 自动修复非标准 URL |
| 编码问题 | 响应自动检测、重定向多编码尝试 |
| 便捷性 | `httpraw` 原始报文发送 |

**设计意图**：将 requests 改造为更适合渗透测试的工具，允许发送各种"非常规"请求来触发漏洞或绕过防护。