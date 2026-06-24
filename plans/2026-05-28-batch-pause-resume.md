# 2026-05-28 批量任务暂停状态与续跑

## 做什么
- 给批量任务新增正式 pause 状态。
- 支持优雅暂停、暂停后续跑、列表页状态/按钮切换。
- 保留现有 stop 接口兜底，不删除既有能力。

## 为什么
- 现有批量任务只有 stop/续跑，用户在页面上很难区分“立刻停”和“处理完队列后再停”。
- 用户希望参考自动扫描页面，给批量任务补齐“暂停中/已暂停/续跑”的完整体验。

## 怎么做
1. 模型新增 `pause_requested` 和 `status=4(pause)`。
2. 批量任务入口支持 `status=pause`，写 DB/Redis pause signal。
3. 执行器增加 `check_pause_signal()`，producer 停止拉新目标，消费者继续排空队列。
4. worker 收尾时把 pause 终态写回 DB，resume 清理 pause signal 并沿用现有进度恢复逻辑。
5. 前端列表页和 JS 参考自动扫描页面重组按钮与文案。
6. 增加回归测试：pause signal、生效后的终态、resume 入口、stop 修复场景。

## 风险
- 影响批量任务主执行链路，需要同时覆盖线程模式和 Celery worker 收尾逻辑。
- 需要避免把 pause 和 stop 混成同一终态，否则续跑按钮和状态文案会错乱。

## 验证
- `python manage.py test --keepdb --noinput app_cybersparker.tests.BatchScanCeleryDispatchTests app_cybersparker.tests.BatchQueueRoutingTests`：通过（15 tests）
- `python manage.py check`：通过，0 issues
- `python manage.py makemigrations --check --dry-run`：通过，无迁移漂移

## 结果
- 已完成：批量任务新增 pause 状态、pause_requested 信号、pause→队列排空→已暂停 收尾，以及 pause/stop 后续跑入口。
- 已完成：前端列表页新增暂停按钮、暂停中/已暂停状态文案、暂停后的续跑入口。
- 已完成：补齐回归测试，覆盖 pause signal、pause 检测、paused 终态、stop 修复场景。

## 后续
- 完成后同步 backlog / 模块文档 / CHANGELOG。
