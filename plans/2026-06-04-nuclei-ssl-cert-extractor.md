# Nuclei 引擎 ssl-cert 提取器支持

- 状态：已完成
- 关联模块：docs/modules/02-任务执行模块.md

## 做什么

给 Nuclei YAML 运行时引擎新增 `ssl-cert` 提取器类型，支持从 HTTPS 响应中提取 TLS 证书字段。

## 为什么

之前 `_apply_extractors()` 只支持 regex/kval/dsl/json/xpath 五种类型，`ssl-cert` 被当作未知类型跳过，返回空结果。用户无法在模板中提取证书信息。

## 怎么做

1. 新增 `_fetch_ssl_cert_data(host, port)` — 用 `ssl` + `socket` 直连目标拉取证书，stdlib 无额外依赖
2. 新增 `_extract_ssl_cert(extractor, ssl_data)` — 按 Nuclei 官方语义抽取 13 个字段
3. 新增 `_has_ssl_extractor(extractors)` — 预检是否有 ssl 提取器，避免无意义的证书请求
4. `_apply_extractors()` 新增 `ssl-cert` / `ssl` 分支
5. `_execute_http_request()` 在调用提取器前，仅当模板有 ssl 提取器且目标为 HTTPS 时才拉取证书

### 提取字段（对齐 Nuclei 官方）

| 字段 | 来源 |
|------|------|
| `tls_version` | `ssock.version()` |
| `subject_cn` | 证书 subject CN |
| `subject_dn` | 证书 subject 完整 DN |
| `subject_org` | 证书 subject O |
| `subject_an` | SAN DNS 列表 |
| `issuer_cn` | 证书 issuer CN |
| `issuer_dn` | 证书 issuer 完整 DN |
| `issuer_org` | 证书 issuer O |
| `not_before` / `not_after` | 证书有效期 |
| `serial` | 序列号 |
| `fingerprint_hash` | {md5, sha1, sha256} |
| `cipher` | `ssock.cipher()` |

### 期间修复的 bug

- `CERT_NONE` → `CERT_REQUIRED` + `load_default_certs()`：Python ssl 在 `CERT_NONE` 下 `getpeercert()` 返回空 dict
- `ssock.version()` / `ssock.cipher()` 移到 `with` 块内：退出 `with` 块后 socket 已关闭

## 风险

低。证书获取仅在模板有 ssl 提取器 + 目标为 HTTPS 时触发，普通模板零额外开销。

## 验证

- Probe 测试：对 `https://www.baidu.com` 全部 13 个字段提取成功
- Django check：0 issues
- 已有测试 15/15 通过
