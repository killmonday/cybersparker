# Nuclei 协议支持边界与模板清理

## 本次决策

- 当前项目里的 Nuclei YAML 运行时 **只支持** `http/requests` 和 `tcp/network` 两类协议块。
- 库中凡是顶层带以下任一协议块的模板，统一视为**当前不支持模板**：
  - `code`
  - `javascript`
  - `headless`
  - `file`
  - `dns`
  - `ssl`
  - `websocket`
  - `whois`
- 这些模板本次统一从数据库删除，并同步删除 `EXP_plugin/` 下对应 YAML 文件。
- `import_nuclei_templates` 已更新：以后再次导入时，这些模板会直接跳过，不再写入数据库。

## 为什么这样处理

当前引擎的执行模型很简单：

1. 读取 YAML
2. 解析请求块
3. 按固定逻辑发 HTTP 请求，或者直接发 TCP/network 原始数据
4. 用 matcher / extractor 判断命中

所以它能跑的前提，是模板的核心动作必须落在：

- 发网页请求
- 连端口发原始数据

超出这两类的模板，即使导入进来，也只是列表里多一条记录，执行时跑不起来。

## 各协议是什么意思

### `http` / `requests`

就是普通网页请求模板。

典型场景：
- 请求 `/login`
- 带 header / cookie / body
- 看状态码、正文、JSON 字段、响应头

这是我们当前**支持**的主路径。

### `tcp` / `network`

就是直接连端口发原始字节，不走 HTTP。

典型场景：
- 连 Redis / MySQL / 自定义端口
- 发探测包
- 看返回 banner 或固定字节串

这是我们当前**支持**的另一条路径。

### `code`

模板里要额外执行一段代码/脚本逻辑，不只是按 YAML 固定字段发请求。

典型场景：
- 先生成签名
- 再拼 payload
- 再按返回决定下一步

当前不支持原因：我们没有这层代码执行环境。

### `javascript`

模板里要执行 JavaScript 逻辑。

典型场景：
- JS 里算 token
- JS 里拼请求参数
- JS 里做流程控制

当前不支持原因：运行时里没有 JS 执行环境。

### `headless`

要起无头浏览器，像真实浏览器一样打开页面、执行前端脚本、读取渲染后的 DOM。

典型场景：
- 页面内容靠前端 JS 渲染
- 需要点击、等待跳转、读最终页面

当前不支持原因：没有浏览器执行环境。

### `file`

模板要检查文件系统，而不是对远程目标发网络请求。

典型场景：
- 检查本地配置文件
- 读取某个文件内容

当前不支持原因：我们的系统是网络探测器，不是主机文件审计器。

### `dns`

模板要发 DNS 查询，不是普通 HTTP/TCP 漏洞请求。

典型场景：
- 查 NS/TXT/A 记录
- 判断域名解析配置

当前不支持原因：没有独立 DNS 查询执行器。

### `ssl`

模板要检查 TLS/SSL 握手和证书信息。

典型场景：
- 证书主题
- 过期时间
- TLS 版本
- 握手配置

当前不支持原因：虽然我们能访问 HTTPS 页面，但没有独立的证书/握手检查执行器。

### `websocket`

模板要建立 WebSocket 长连接，发消息、收消息再做判断。

典型场景：
- 连接 `/ws`
- 发 websocket message
- 检查服务端推送

当前不支持原因：没有 WebSocket 握手和消息帧执行器。

### `whois`

模板要查询域名 WHOIS 信息。

典型场景：
- 查注册商
- 查到期时间
- 查 WHOIS 字段

当前不支持原因：没有 WHOIS 查询执行器。

## 本次实际操作口径

只要一个模板顶层带了上述任一不支持协议块，就统一按“不支持模板”处理。

注意：这意味着有些模板即使同时带了 `http`，只要又带了 `code/headless/...`，本次也一样删除。

原因很简单：
- 这类模板的真实语义已经超出我们当前引擎边界
- 继续保留会让用户误以为它能跑
- 与其保留一批“看起来在库里、实际上跑不完整”的模板，不如口径统一：当前不支持就不进库

## 相关命令

### 导入

```bash
python manage.py import_nuclei_templates --source /tmp/nuclei-templates
```

现在会自动跳过不支持协议模板。

### 清理历史数据

```bash
python manage.py cleanup_nuclei_unsupported_templates
```

仅查看统计，不实际删除：

```bash
python manage.py cleanup_nuclei_unsupported_templates --dry-run
```
