# 插件列表批量删除参数兼容修复

- 状态：已完成
- 模式：Mode D-lite

## 问题
`/expload/list` 页面批量删除按钮会把已选插件 id 以 `uids` 形式提交，但后端只读 `uids[]`，导致选中后仍报 `No items selected`。

## 方案
1. 后端批量删除接口同时兼容 `uids[]` 和 `uids`。
2. 增加回归测试，覆盖页面当前实际提交格式。

## 修改文件
- `app_cybersparker/views/expload/plugin_manage.py`
- `app_cybersparker/tests.py`
- `docs/backlog/01-插件管理.md`
- `CHANGELOG.md`

## 验证
- `python manage.py check`：通过。
- `python manage.py test app_cybersparker.tests.AutoScanStatusViewTests`：通过，新增的批量删除回归测试通过。
- 空选中时仍返回 `No items selected`。

## 结果
- 后端同时兼容 `uids[]` 和 `uids`，插件列表批量删除恢复可用。
- 验证范围保持最小，没有改删除语义。

## 风险
- 低：仅做参数兼容，不改删除语义。

## 下一步
- 如果前端后续统一改成 `uids[]`，这条兼容可以再收口，但现在不必动。
