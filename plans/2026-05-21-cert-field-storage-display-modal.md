# 证书字段存储、截断与弹窗展示

## 做什么
- 将 `auto_scan_indentify_result.cert_common_name` 改成不限长度。
- 入库前截断 `cert_org` / `cert_org_unit`，避免超长导致写库失败。
- 两个结果页继续按“单位 / 部门 / 公用名”展示证书信息，但改为可点击，并在弹窗里展示完整证书字段。

## 为什么
- 公用名可能很长，不能继续用短字符串字段。
- 证书申请单位和部门字段要保持稳定入库，避免超长失败。
- 页面上的证书摘要需要更短，但完整信息又要能随时查看。

## 怎么做
1. 改模型字段类型并加迁移。
2. 在识别结果落库时继续截断 `cert_org` / `cert_org_unit`。
3. 给旧结果页和 standalone 页补证书摘要按钮、长度限制和证书详情弹窗。
4. 补回归测试：字段长度、页面展示、弹窗存在。
5. 同步 backlog、模块文档、现状说明和变更记录。

## 风险
- 模型字段变更需要迁移，别漏掉本地/测试库同步。
- 两套模板结构不一样，别只改一边。
- 弹窗内容需要避免把长字符串撑破布局。

## 结果
- 待完成。

## 验证
- `python manage.py test app_cybersparker.tests.AutoScanResultSearchTests --keepdb --noinput -v 2`
- `python manage.py test app_cybersparker.tests.ResultEventServiceTests --keepdb --noinput -v 2`
- `python manage.py check`
