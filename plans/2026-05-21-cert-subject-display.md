# 资产检索页 UI 增强：证书展示精简、状态码区分、漏洞 IP 红色高亮

## 做什么
1. **证书展示精简**：两个资产检索结果页的证书信息从显示 `O / OU / CN` 改为只显示 `证书主体`（CN），O/OU 移至每个资产的网站标题右侧，超长省略号截断
2. **证书 tooltip 条件显示**：仅在文本溢出被截断时鼠标悬浮显示完整内容
3. **状态码视觉区分**：200 显示 `#eaf0ef` 背景，其他透明融入容器
4. **漏洞资产 IP 红色高亮**：存在关联漏洞的资产 IP 显示红色 `#dc2626`

## 修改文件
1. `app_cybersparker/templates/project/expload/task_manage/_result_items.html` — server 渲染：证书主体、网站标题右侧 cert org/unit、状态码条件 class、漏洞 IP 红色 class
2. `app_cybersparker/templates/project/expload/task_manage/auto_scan_identify_result_standalone.html` — standalone/全局检索：CSS（ri-cert/ri-sc-ok/ri-ip-vuln）、JS renderResults 同步、updateCertTooltips 溢出检测
3. `app_cybersparker/templates/project/expload/task_manage/auto_scan_identify_result.html` — legacy 项目内结果页：同上，inline style 方式
4. `CHANGELOG.md` / `docs/当前实现总览.md` — 文档同步

## 风险
- 低风险：纯展示调整，不涉及数据模型、API 契约变更
- 视图层已回退为干净状态（未修改 auto_scan_result.py）

## 结果
- Django 系统检查：0 issues
- 测试：均为已有问题，本次未引入新失败
