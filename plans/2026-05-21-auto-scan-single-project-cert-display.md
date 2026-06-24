# 单项目资产检索页证书展示补齐

## 做什么
- 给单项目资产检索页（`/Identify_task/<uid>/result`）补上证书序列号和证书申请信息展示。
- 同步更新相关模块文档、变更记录和回归测试。

## 为什么
- 全局资产检索页和 standalone 页已经能看到证书信息，但单项目旧页还缺这一块，导致同一类结果在不同入口展示不一致。

## 怎么做
1. 在 `auto_scan_identify_result.html` 里补充证书展示区。
2. 补一条定向测试，覆盖旧单项目页的证书渲染。
3. 更新 `docs/modules/03-指纹与自动识别模块.md`、`docs/backlog/03-指纹与自动识别.md`、`docs/当前实现总览.md` 和 `CHANGELOG.md`。

## 风险
- 只改模板展示，不改检索语义，风险很低。
- 需要确认旧页渲染路径没有遗漏其他字段依赖。

## 结果
- 已补齐单项目旧结果页的证书展示，旧页现在与 standalone / 全局页保持一致。

## 验证
- `python manage.py test app_cybersparker.tests.AutoScanResultSearchTests --keepdb --noinput -v 2`
- `python manage.py check`
