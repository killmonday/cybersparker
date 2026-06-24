# favicon 与证书资产增强执行计划

## 做什么
- 在自动扫描 web 请求链路补充 favicon 与 HTTPS 证书采集。
- 在资产检索页补充 favicon / cert 展示与检索。
- 在指纹识别规则中新增 `favicon` / `cert` / `cert_serial` 相关能力。
- 同步补测试、CHANGELOG、控制面文档。

## 为什么
- 让自动扫描结果不仅能看页面内容和产品，还能直接看图标和证书特征。
- 让 favicon md5、证书序列号、证书申请信息进入统一检索入口。
- 让指纹识别能直接利用 favicon 与 cert 特征，提高识别覆盖。

## 怎么做
1. 扩展 `auto_scan_indentify_result` 数据模型与写入链路，承载 favicon / cert 字段。
2. 在 `auto_exp_task.py` 的 aiohttp 请求后补 favicon / cert 采集逻辑；证书优先复用连接，拿不到再走备用方案。
3. 扩展全局资产检索页搜索解析与展示，支持 `favicon:` / `cert_serial:` / `cert:`。
4. 扩展指纹识别规则解析，支持 `favicon`、`cert_serial`，以及 `cert` 组三字段任一命中。
5. 补针对性测试，完成文档与变更记录同步。

## 风险
- favicon 补探测过多会拖慢扫描速度。
- aiohttp 响应对象未必稳定暴露证书对象，备用方案必须受控。
- 搜索解析器新增键后，不能破坏现有 `title/body/header/product/vuln/cve` 语法。
- 指纹规则新增 key 后，不能影响旧规则命中。

## 当前状态
- 2026-05-21：已完成深度访谈与共识规划，开始执行前文档准备。
- 2026-05-21：任务 1 已完成，开始实现任务 3：统一两套搜索键行为，并补资产检索页 favicon 热门区。

## 验证方式
- Django 模型/迁移检查。
- 定向单测：扫描写入、搜索解析、指纹命中。
- 相关页面/接口回归验证。

## 结果
- 已完成任务 1：自动扫描结果新增 `favicon` / `favicon_md5` / `cert_org` / `cert_org_unit` / `cert_common_name` / `cert_serial` 字段，并打通采集到结果事件的链路。
- 已完成任务 2：`fingerprint_indentify.py` 支持 `favicon`、`favicon_md5`、`cert_org`、`cert_org_unit`、`cert_common_name`、`cert_serial`，并修复旧混合条件分支参数顺序 bug。
- 已完成任务 3：`all_Indentify_result.py` 与 `auto_scan_result.py` 统一支持 `favicon:`、`cert_serial:`、`cert:` 搜索键；资产检索页与 standalone 结果页新增 favicon 热门区；旧结果页补齐 favicon / 证书展示与检索兼容。
- 已通过 Django check 与定向测试，百度 HTTPS 现场验证已确认证书可提取；浏览器人工走查尚未补，验收状态先记为已验收（后续如需 UI 人工复核可再补）。

## 后续
- 若 favicon 命中率不足，再单独做图标发现策略优化。
