# BL-DIRSCAN-016 漏洞验证 URL 改为根路径

- 日期：2026-06-15
- 状态：已完成

## 做什么

目录扫描 Phase2 漏洞验证阶段，把传给 POC verify 的 target URL 从 `协议://host:端口/path` 改为 `协议://host:端口`。

## 为什么

大部分 POC 的 verify 方法是对目标根路径做检测（如默认口令、未授权访问等），传带 path 的完整 URL 反而可能不命中。

## 怎么做

改 `app_cybersparker/services/dirscan_worker.py` 第 540 行：

```python
# 旧
target = row.target or f"{row.protocol}://{row.host}:{row.port}{row.uri_path}"

# 新
target = f"{row.protocol}://{row.host}:{row.port}"
```

`row.target` 存储的是 `final_url`（HTTP 请求该路径的最终响应 URL），也带 path，所以一并去掉。

## 风险

- 极少数 POC 如果依赖 path 构造攻击 payload，行为可能变化。但这类 POC 通常是少数，且根 URL 才是更通用的测试目标。

## 验证

- `python manage.py check`
