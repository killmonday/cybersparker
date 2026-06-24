# 自动扫描识别结果独立页面 + 美化

- 日期：2026-05-15
- Backlog ID：BL-UX-001
- 类型：UI Enhancement
- 风险：LOW（纯前端+路由，不修改业务逻辑）

## 需求

用户要求将 `/Identify_task/<id>/result` 自动扫描任务的结果查看页从后台（含侧边栏）中独立出来，作为新窗口打开的独立页面，并美化（响应式、浅色专业风配色）。

## 实现方案

- 新增 `auto_scan_identify_result_standalone.html` 独立模板（不 extend `project/index.html`）
- 浅色专业风：白底 `#f0f2f5`，卡片 `#fff`，主色蓝 `#3b82f6`，文字灰 `#374151`
- CSS Grid 布局：280px 统计侧栏 + 1fr 结果区，1024px 以下统计面板折叠
- 原有搜索语法、字段统计分组、显示设置、导出 CSV 功能完整保留
- 新增路由 `/Identify_task/<id>/result/standalone`，原有路由保持不变
- 任务列表页新增独立窗口链接（新标签页打开）

## 修改文件

| 文件 | 变更 |
|------|------|
| `auto_scan_identify_result_standalone.html` | 新建独立模板 |
| `auto_scan_result.py` | `Task_result` 新增 `standalone` kwarg，独立模式查 task_name + 用新模板 |
| `cybersparker/urls.py` | 新增 `Identify_task/<uid>/result/standalone` 路由 |
| `auto_scan_task_list.html` | 新增独立窗口链接按钮 |

## 验证

- Django 系统检查：0 issues
- 测试：15/15 通过
- URL 路由：两个路由均正确解析

## v2 重设计 (2026-05-15)

基于 frontend-design skill 完全重写独立模板。

**设计方向**："Warm Laboratory" — 暖灰底色 `#f5f3f0` + 编辑风格衬线字体 Spectral + 单一青色强调色 `#0d9488`

**改动**：
- 去除多色框架，统一暖灰+白+青配色
- 移除卡片盒模型，结果改为可展开行列表（subtle divider 分隔）
- 左侧边栏新增漏洞统计：查询 `auto_scan_exp_result` 按 CVE 聚合
- 搜索维度折叠面板（替代展开的统计卡片）
- 字体：Spectral（衬线标题）+ DM Sans（UI 数据）

**后端变更**：`Task_result` standalone 分支新增 `vuln_stats` / `vuln_total` 上下文

**验证**：Django 检查 0 issues，15 tests OK，URL 路由正常

## v3 交互增强 (2026-05-15)

### 新增功能

1. **展开/收起全部切换按钮**：搜索栏新增"展开全部"/"收起全部"按钮，一键切换所有资产卡片的抽屉状态
2. **对齐优化**：收起栏从 `flex-wrap` 改为 CSS Grid `grid-template-columns: 180px 72px 72px 1fr 24px`，协议/端口列宽固定，行间元素垂直对齐
3. **查看完整 HTML**：每个资产卡片展开后显示"查看 HTML"按钮，点击弹出全屏 iframe 渲染原始 HTML 响应体
4. **左侧维度异步加载**：`field_statistics` 序列化为 JSON 嵌入页面；JS 仅初始渲染 protocol+port 两个维度组；其余维度折叠为"点击加载"按钮，按需渲染，每组 max-height:200px 滚定

### 改动文件
- `auto_scan_result.py`：新增 `field_statistics_json` / `total_counts_json` 上下文（JSON 序列化）
- `auto_scan_identify_result_standalone.html`：~520 行重写
