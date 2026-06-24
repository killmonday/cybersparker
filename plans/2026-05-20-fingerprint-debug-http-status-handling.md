# 2026-05-20 指纹调试页 HTTP 状态处理修复

## 做什么
- 修复指纹调试页对目标 URL 的请求头选择，避免旧随机 UA 把部分站点打成 404。
- 修复指纹调试页把非 2xx 响应直接当成请求失败的问题，改为继续展示响应头和响应正文，方便排查规则。
- 补充后端测试，覆盖这两类行为。

## 为什么
- 用户反馈同一 URL 直接访问是 200，但页面里显示请求错误 404。
- 现场复现后确认：页面旧请求头会把该目标打成 404；同时后端对 4xx/5xx 调用了 `raise_for_status()`，导致明明拿到了响应，也被页面当成“请求失败”，无法看到正文。

## 怎么做
1. 只修改 `app_cybersparker/views/expload/fingerPrint_debug.py` 的请求头与 `mate` 响应处理。
2. 在 `app_cybersparker/tests.py` 为指纹调试页补充两条测试：
   - 非 2xx 响应仍返回响应头/响应体。
   - 默认请求头改为固定现代浏览器 UA，且不再附带会触发目标侧差异响应的旧头。
3. 同步 `CHANGELOG.md`、相关 backlog 状态记录；模块文档不改，因为这次只是页面本地 bug 修复，没有改模块范围和接口。
4. 本次按 Mode D-lite 处理：复用现有 `docs/backlog/03-指纹与自动识别.md`，补一个已完成的小 backlog 条目记录这次修复。

## 风险
- 仅影响 `POST /fingerPrint_debug/mate` 这条调试链路，风险低。
- 若前端依赖“4xx 一定走请求失败分支”，页面文案会变化，但这是本次修复目标。

## 验证
- 运行 `python manage.py test app_cybersparker.tests.FingerprintDebugPageTests --keepdb --noinput -v 2`
- 运行 `python manage.py check`

## 当前状态
- 已完成：代码、测试、变更记录已同步。

## 结果
- 已去掉旧请求头中的 `Referer` 与过时 `Accept-Encoding`，改为更干净的现代浏览器请求头。
- `mate()` 不再对非 2xx 响应调用 `raise_for_status()`，页面现在能看到真实响应头和响应正文。
- 定向测试 `python manage.py test app_cybersparker.tests.FingerprintDebugPageTests --keepdb --noinput -v 2` 通过。
- `python manage.py check` 通过。

## 后续
- 若仍有个别站点因目标侧反爬导致返回异常，再按真实返回内容继续排查，不再把所有非 2xx 一刀切成“请求错误”。
