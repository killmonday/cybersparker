# BL-FE-101 standalone 结果页 React 化（仅任务内结果主链路）

- 状态：已完成
- 关联 Backlog：`docs/backlog/08-前后端分离改造.md#bl-fe-101-standalone-结果页-react-化仅任务内结果主链路`
- 分支：`feat/react-frontend-separation`

## 做什么

将 `/Identify_task/<uid>/result/standalone` 的主内容区切到 React，直接消费阶段七已经固定好的 `/api/v1/identify-tasks/<uid>/results` 与 `/api/v1/identify-tasks/<uid>/facets` 契约，先覆盖任务内搜索、分页、facet、结果列表和详情展开主链路。

## 为什么

阶段七已经把结果页 JSON 契约固定好了，也确认了 standalone 结果页是下一期结果展示线的第一优先级。先把单任务结果页跑通，可以用最小范围验证 React 结果组件是否可靠，再把同一套组件扩到全局资产检索页。

## 怎么做

1. 盘点当前 standalone 结果页的 Django 视图、模板、JS 状态和 React 壳接入点。
2. 做影响分析，确认只改 standalone 结果页主内容区，不动旧 `/Identify_task/<uid>/result` 后台页。
3. 在 `frontend/` 中新增 standalone 结果页模式，接 `/api/v1/identify-tasks/<uid>/results` 与 `/api/v1/identify-tasks/<uid>/facets`。
4. 先只接主链路：搜索、分页、facet、结果列表、详情展开。
5. 保留旧模板回退路径，附属能力（HTML 原文查看、漏洞结果、端口概览）先继续走现有入口或留到 FE-103。
6. 通过新旧页同查询对照测试和阶段验证命令收口。

## 风险

- 最容易把 task scope 条件带丢，出现“任务 200 打开的 standalone 页查到了任务 100 的资产”。
- 共享结果组件时，facet、分页、展开状态容易丢失。
- 若 React 页面直接依赖旧模板隐式字段，会把 BL-FE-004 固定下来的契约层绕开。

## 验证

- `npm --prefix frontend run build`
- `python manage.py test ...`（补 standalone 结果页相关定向测试）
- `python manage.py check`
- 新旧 standalone 页同查询结果总数、首屏列表、facet 前几项对照

## 当前进度

- 2026-05-30：开始执行准备，已读取 BL-FE-101 backlog、阶段八规划和阶段七结果页契约文档。
- 2026-05-30：已确认 standalone 结果页当前后端主入口为 `Task_result()`，任务内结果 `/api/v1` 契约入口为 `task_result_api()` / `task_facet_api()`；当前 React 仍只有低风险列表页样板，尚未接结果页。
- 2026-05-30：已完成第一轮最小实现：新增 `react_task_result_list()` 与 `/react-shell/identify-tasks/<uid>/results` 壳页路由；`frontend/src/main.tsx` 已新增 `task-results` 页面模式和 `TaskResultsPage` 第一版，先覆盖任务内搜索、facet（可点击）、分页（上一页/下一页/每页条数）、结果列表与详情展开主链路；`frontend/src/styles.css` 已补最小结果页样式。
- 2026-05-30：已将自动扫描任务列表里的“结果（独立窗口）”入口切到新的 React 结果页壳路径，形成真实可见入口；旧 `/Identify_task/<uid>/result/standalone` 模板仍保留为回退路径。
- 2026-05-30：已按当前实现补齐第一轮验证：`npm --prefix frontend run build`、`npm --prefix frontend exec -- tsc --noEmit -p /workspaces/cybersparker/frontend/tsconfig.json`、`python manage.py test app_cybersparker.tests.ReactShellIntegrationTests app_cybersparker.tests.AutoScanResultSearchTests --keepdb`、`python manage.py check` 全部通过。

## 下一步

- 已补独立只读审查，确认当前版本仍在 BL-FE-101 范围内，但附属能力（HTML 原文查看、漏洞结果查看、端口概览懒加载）继续留在 FE-103。
- 已补 3 类更贴近验收的对照证据：task 结果 API 与旧 standalone JSON 对照、task facet API 与旧 facet 对照、`rows_per_page` 白名单参数生效。
- 本项进入待验收状态，下一步建议切到 `BL-FE-102`，复用当前结果组件做全局资产检索页 React 化。
