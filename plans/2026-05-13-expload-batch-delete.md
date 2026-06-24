# expload/list 批量删除

- 状态：已完成
- 模式：Mode D-lite

## 问题
`/expload/list` 页面已有行复选框和全选复选框，但缺少批量删除功能。

## 方案
1. 后端：新增 `expload_batch_delete` 视图，接收 `uids[]` 列表，逐个删除 DB 记录和关联文件
2. URL：添加 `expload/batch_delete` 路由
3. 前端：在按钮区加批量删除按钮 + JS（收集已选 ID → 确认 → AJAX → 刷新）

## 修改文件
- `app_cybersparker/views/expload/plugin_manage.py`
- `cybersparker/urls.py`
- `app_cybersparker/templates/project/expload/exp_list.html`

## 验证
- 勾选多项 → 点击批量删除 → 确认 → 页面刷新 → 选中项已删除
- 未勾选任何项时点击 → 提示无选中项

## 风险
- 低：仅复用已有删除逻辑，不改变数据模型
