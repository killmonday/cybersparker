# BL-AUTO-008 全局资产检索页面

- 状态：已完成

## 验证

- [x] Django check 0 issues
- [x] /asset/search 可访问
- [x] /asset/facet 可访问
- [x] 全局搜索不限定 task_id
- [x] 左侧导航"资产检索"已添加
- [ ] 运行时端到端测试
- 创建时间：2026-05-17

## 做什么

新增全局资产检索页面 `/asset/search`，展示 `auto_scan_indentify_result` 全表数据，不限任务。左侧导航新增"资产检索"。

## 怎么做

### 后端
- `auto_scan_result.py` 新增 `global_asset_search(request)` 和 `global_facet(request)` 两个视图
- 复用 standalone 页面逻辑，去掉 task_id 过滤

### URL
- `/asset/search` → global_asset_search
- `/asset/facet` → global_facet

### 模板
- 复制 `auto_scan_identify_result_standalone.html`，去掉 vuln_stats 区域、task_id 变量

### 导航
- `project/index.html` 新增"资产检索"一级菜单
