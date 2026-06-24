# Nuclei YAML 模板生成提示词

根据漏洞描述，生成符合以下规范的 Nuclei YAML 漏洞检测模板。

> 注意：目标平台使用自研轻量引擎，只支持官方 Nuclei 模板规范的一个子集。以下列出的能力之外的功能均不可用。

---

## 模板格式规范

### 支持的协议

| 协议 | 写法 | 用途 |
|------|------|------|
| HTTP | `http:` | 发 HTTP/HTTPS 请求 |
| TCP | `network:` | 连 TCP 端口发原始字节 |

**禁止使用**：`code`, `javascript`, `headless`, `file`, `dns`, `ssl`, `websocket`, `whois`。模板中只要包含任一禁止协议即无效。

### HTTP 请求定义

**path + method 方式**：

```yaml
http:
  - method: GET
    path:
      - "{{BaseURL}}/api/info"
```

**raw 方式**（多步请求或自定义请求头时使用）：

```yaml
http:
  - raw:
      - |
        POST /api/login HTTP/1.1
        Host: {{Hostname}}
        Content-Type: application/json

        {"username": "admin"}
      - |
        GET /api/admin HTTP/1.1
        Host: {{Hostname}}
```

### 支持的 Matcher 类型

| type | 说明 | 关键字段 |
|------|------|---------|
| `word` | 关键词匹配 | `words: [...]`, `part: body/header`, `condition: and/or` |
| `regex` | 正则匹配 | `regex: [...]`, `part: body/header` |
| `status` | 状态码匹配 | `status: [200, 301]` |
| `size` | 响应大小匹配 | `size: [1024]` |
| `binary` | 十六进制字节匹配 | `binary: ["0a0d"]` |
| `dsl` | 表达式匹配 | `dsl: ['status_code == 200']` |
| `xpath` | XPath 匹配 HTML/XML | `xpath: ["//element"]` |

所有 matcher 支持 `condition: and/or`（默认 `or`），支持 `negative: true` 取反。

### 支持的 Extractor 类型

| type | 说明 | 关键字段 |
|------|------|---------|
| `regex` | 正则提取 | `regex: [...]`, `group: 1` |
| `kval` | 键值提取（从响应头/Cookie） | `kval: ["key"]` |
| `json` | JSON 路径提取 | `json: [".data.token"]` |
| `dsl` | 表达式计算 | `dsl: ["expression"]` |
| `xpath` | XPath 提取 HTML/XML 节点 | `xpath: ["//element"]` |
| `ssl-cert` | TLS 证书字段提取 | 仅 HTTPS 可用 |

所有 extractor 支持 `internal: true`（提取结果传递给后续请求使用）。

### 内置变量

| 变量 | 说明 | 示例值 |
|------|------|--------|
| `{{BaseURL}}` | 目标完整 URL | `http://example.com:8080` |
| `{{RootURL}}` | 协议+主机+端口 | `http://example.com:8080` |
| `{{Hostname}}` | 主机名:端口 | `example.com:8080` |
| `{{Scheme}}` | 协议 | `http` |
| `{{Host}}` | 主机名 | `example.com` |
| `{{Port}}` | 端口 | `80` |
| `{{Path}}` | URL 路径目录部分 | `/admin` |
| `{{File}}` | URL 文件名部分 | `index.php` |
| `{{IP}}` | 目标 IP | `93.184.216.34` |

自定义变量通过 `variables:` 声明。OOB/DNSLog 检测使用 `{{ceye_url}}` 或 `{{interactsh_url}}` 变量。

### DSL 上下文变量

在 DSL matcher/extractor 中可直接使用：

| 变量 | 说明 |
|------|------|
| `status_code` | HTTP 响应状态码 |
| `body` | 响应体（字符串） |
| `header` | 响应头 |
| `content_type` | Content-Type |
| `duration` | 请求耗时（秒） |

多请求时用 `_N` 后缀区分：`status_code_1`、`body_2`、`duration_2` 等。

### DSL 可用函数

`contains`, `contains_all`, `contains_any`, `regex`, `starts_with`, `ends_with`, `line_starts_with`, `line_ends_with`, `md5`, `sha256`, `base64`, `base64_decode`, `hex_encode`, `hex_decode`, `url_encode`, `url_decode`, `to_lower`, `to_upper`, `concat`, `join`, `rand_base`, `rand_int`, `rand_text_alpha`, `rand_text_alphanumeric`, `rand_text_numeric`, `replace`, `replace_regex`, `trim`, `gzip`, `gzip_decode`, `date_time`, `unix_time`, `generate_java_gadget`, `compare_versions`, `len`, `str`, `int`, `float`, `abs`, `min`, `max`, `sum`, `bool`

### Payloads

```yaml
payloads:
  key:
    - value1
    - value2
attack: batteringram   # 或 pitchfork
```

- `batteringram`：逐个取值逐个请求（笛卡尔积）
- `pitchfork`：同位置的值组合成一对（一一对应）

### TCP/Network 模板

```yaml
network:
  - host:
      - "{{Hostname}}"
    inputs:
      - data: "PING\r\n"
        type: text         # text 或 hex
        name: response     # 可选，命名该次读取的数据
        read: 1024         # 可选，发送前先读多少字节
    read_size: 1024
    read_all: false
    matchers:
      - type: word
        words:
          - "PONG"
```

### 多请求 Flow

```yaml
flow: http(1) && http(2)   # 两个请求必须都匹配才算命中
```

默认为 OR 模式（任一请求匹配即命中，`stop-at-first-match: true` 时匹配第一个后停止）。

---

## 完整示例

### 示例 1：HTTP GET + 关键词匹配

```yaml
id: example-info-leak

info:
  name: Example App - Configuration Information Leak
  author: security-researcher
  severity: medium
  description: Example App exposes sensitive configuration without authentication.
  tags: exposure,config,misconfig

http:
  - method: GET
    path:
      - "{{BaseURL}}/api/config"

    matchers-condition: and
    matchers:
      - type: status
        status:
          - 200
      - type: word
        part: body
        words:
          - "password"
          - "secret"
        condition: or
```

### 示例 2：带 Extractor（正则提取版本号，传递给后续请求）

```yaml
id: app-version-detect

info:
  name: Example App - Version Detection
  author: security-researcher
  severity: info
  description: Detects version from response footer.
  tags: detect,version

http:
  - method: GET
    path:
      - "{{BaseURL}}/"

    matchers-condition: and
    matchers:
      - type: word
        part: body
        words:
          - "Powered by Example App"
      - type: status
        status:
          - 200

    extractors:
      - type: regex
        name: version
        part: body
        group: 1
        regex:
          - 'Version ([0-9.]+)'
        internal: true
```

### 示例 3：Raw 请求 + DSL 多步匹配

```yaml
id: CVE-2024-XXXXX-auth-bypass

info:
  name: SomeApp - Authentication Bypass (CVE-2024-XXXXX)
  author: security-researcher
  severity: critical
  description: SQL injection in login API allows authentication bypass.
  tags: cve,cve2024,auth-bypass,sqli

http:
  - raw:
      - |
        POST /api/login HTTP/1.1
        Host: {{Hostname}}
        Content-Type: application/json

        {"username": "admin", "password": "' OR '1'='1"}
      - |
        GET /api/admin/users HTTP/1.1
        Host: {{Hostname}}
        Cookie: session={{session_token}}

    stop-at-first-match: true
    matchers-condition: and
    matchers:
      - type: dsl
        dsl:
          - 'status_code_2 == 200'
          - 'contains(body_2, "admin")'
          - 'contains(body_2, "email")'
        condition: and

    extractors:
      - type: json
        name: session_token
        json:
          - ".token"
        internal: true
```

### 示例 4：Payloads Fuzzing

```yaml
id: path-traversal-detect

info:
  name: Generic Path Traversal Detection
  author: security-researcher
  severity: high
  description: Detects path traversal vulnerabilities.
  tags: lfi,path-traversal,generic

http:
  - method: GET
    path:
      - "{{BaseURL}}/{{file_path}}"

    payloads:
      file_path:
        - ../../etc/passwd
        - ....//....//etc/passwd
        - ..%2f..%2f..%2fetc%2fpasswd

    attack: batteringram
    stop-at-first-match: true
    matchers-condition: or
    matchers:
      - type: word
        part: body
        words:
          - "root:"
      - type: regex
        part: body
        regex:
          - 'root:.*:0:0:'
```

---

## 输出格式

生成 YAML 模板后，在模板下方以如下格式输出必要参数（程序会解析这些字段来自动创建插件）：

```yaml
# 以下字段由你（AI）提供：
title: "CVE-2024-XXXXX - SomeApp Auth Bypass"   # 必填，模板展示名称（程序会自动添加 hash 后缀）
CVE: "CVE-2024-XXXXX"                            # 可选，从模板内容也能自动提取
severity: "critical"                             # 必填，与模板 info.severity 保持一致
tags: "cve,cve2024,auth-bypass,sqli"             # 必填，与模板 info.tags 保持一致
```

> 以下字段由程序自动设置，你不需要提供：`plugin_language`（固定为 2）、`Type`（固定为 12）、`extentions`（固定为 [1]）、`poc_content`（程序计算 SHA256）。
