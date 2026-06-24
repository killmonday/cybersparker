# 批量任务列表页删除确认状态收口

- 状态：已完成
- 模式：Mode D-lite

## 问题
批量任务列表页的“提交”按钮会直接触发批量删除，看起来像是少了确认步骤；同时关闭弹窗后，`pendingBatchDeleteIds` 需要清空，避免状态残留。

## 方案
1. 把批量任务列表页的“提交”按钮改成显式 `type="button"`。
2. 在 `bath_Expload_Task.js` 的点击处理中显式 `preventDefault()` / `stopPropagation()`，先弹 `deleteModal` 再执行批删。
3. `deleteModal` 关闭后清空 `pendingBatchDeleteIds`。
4. 补静态回归测试，覆盖按钮类型、点击拦截和隐藏事件清理状态。
5. 只改批量任务列表页，不碰结果页。

## 修改文件
- `app_cybersparker/templates/project/expload/task_manage/bath_exp_task_list.html`
- `app_cybersparker/static/project2/expload/js/batch_Expload_Task.js`
- `app_cybersparker/tests.py`
- `CHANGELOG.md`

## 验证
- `python manage.py check`
- `python manage.py test app_cybersparker.tests.BatchTaskDeleteModalStateTests`

## 结果
- 批量任务列表页的批量删除现在会先弹确认框，不会直接执行。
- 关闭确认框后，会清空 `pendingBatchDeleteIds`，避免残留状态。

## 风险
- 低：只改前端交互，不改后端删除语义。
