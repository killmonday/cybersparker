# exp_debug CodeMirror Tab→4空格

- 状态：已完成
- 模式：Mode D-lite

## 问题
POC 代码编辑器中按 Tab 时未强制使用 4 空格缩进，可能导致 tab/space 混用引起 Python TabError。

## 根因
1. tips 编辑器（`editor_tips`）缺少 `indentUnit/tabSize/indentWithTabs` 配置
2. 主编辑器虽有配置但无显式 Tab 键处理，依赖 CodeMirror 默认行为不够可靠

## 方案
1. tips 编辑器：补全 `indentUnit: 4, tabSize: 4, indentWithTabs: false`
2. 主编辑器：在 `extraKeys` 中添加显式 Tab 处理，直接插入 4 空格

## 修改文件
- `app_cybersparker/templates/project/expload/exp_debug.html`

## 验证
- Django 系统检查 0 issues
- 模板能正常渲染（无语法错误）
