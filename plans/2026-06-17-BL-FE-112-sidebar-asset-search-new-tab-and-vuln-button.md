# BL-FE-112 侧边栏资产检索新标签页 + 自动扫描任务漏洞按钮

- 日期：2026-06-17
- 范围：2 个前端文件

## 做什么

1. 后台左侧导航栏"资产检索"点击后在新标签页打开 `/react-shell/assets/search`
2. 自动扫描任务管理页"操作"列新增"漏洞"按钮，点击新标签页打开 `/react-shell/auto-exp-results?task_id=<id>`

## 怎么做

### 改动 1 — SidebarLayout.tsx
- "资产检索" `<a>` 标签添加 `target="_blank" rel="noopener noreferrer"`
- onClick handler 中对 `/assets/search` 键直接 return（不 preventDefault + navigate），让浏览器处理 `<a target="_blank">`

### 改动 2 — AutoScanTaskListPage.tsx
- "操作"列 btns 数组追加一个 `<a>` 标签，href 指向 `/react-shell/auto-exp-results?task_id=<id>`，target="_blank"

## 风险
- 无。纯前端链接行为变更，不涉及 API/数据/安全。

## 验证
- TypeScript 编译通过（`npx tsc --noEmit`）✓
- Vite 构建通过（`npm run build`）✓
- 测试豁免：纯前端链接属性变更，无可测试逻辑
- Django 检查通过 ✓

## 结果
- 已完成：6 个文件修改（含指纹调试页远程搜索 + 布局修复）
- 修改文件：`frontend/src/components/SidebarLayout.tsx`、`frontend/src/pages/AutoScanTaskListPage.tsx`、`frontend/src/pages/FingerprintDebugPage.tsx`、`frontend/src/styles.css`、`app_cybersparker/views/expload/fingerPrint_debug.py`
- 已提交：commit 084b714
- 状态：已完成
