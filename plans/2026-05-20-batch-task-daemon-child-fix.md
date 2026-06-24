# 批量任务 Celery 子进程断言修复

- 状态：已完成
- 创建时间：2026-05-20

## 做什么

修复批量任务在 Celery worker 中运行 `run_mode=2` 时触发 `AssertionError: daemonic processes are not allowed to have children` 的问题。

## 为什么

当前批量任务已经迁移到 Celery worker 执行，但 `startTask()` 在协程模式下仍然会再 `spawn` 一个子进程。Celery 的 prefork worker 本身是 daemon 子进程，daemon 进程不能再创建子进程，所以任务一启动就直接崩。

## 怎么做

1. 保持 Web 请求线程路径不变：非 Celery 场景下，`run_mode=2` 仍走原有子进程模式。
2. 对 daemon worker 场景做最小分流：如果已经在 daemon 进程里，就不要再次 `spawn` 子进程，改为直接复用 `Task_handler` 线程启动 gevent 模式。
3. 保留现有 stop bridge、resource lease、CAS 终态收敛逻辑。
4. 增加守护回归测试，覆盖“普通父进程仍走 spawn”和“daemon worker 不再起子进程”两条路径。

## 风险

- 只应影响批量任务 `run_mode=2` + daemon worker 路径；线程模式和 Web 直起路径不能受影响。
- gevent 模式改为在 worker 内用线程启动后，外层仍要能继续通过 `is_alive/join/kill_task` 监控和停止。
- 当前定向测试避开了仓库里既有的 `TransactionTestCase + TRUNCATE 保护` 环境噪声，只验证这次修复分支。

## 验证

- [x] daemon/Celery 场景下 `startTask()` 不再调用 `process.start()`。
- [x] 非 daemon 场景下 `run_mode=2` 仍保留原有子进程启动逻辑。
- [x] `python manage.py test app_cybersparker.tests.BatchTaskDaemonGuardTests --keepdb --noinput -v 2` 通过。
- [x] `python manage.py check` 0 issues。

## 结果

- 根因已收敛：Celery prefork worker 是 daemon 子进程，旧代码在 `run_mode=2` 下再次 `spawn`，被 Python 直接拒绝。
- 修复后，普通 Web 路径仍保留 gevent 子进程隔离；daemon worker 路径改为直接复用 `Task_handler.start()` 执行 gevent 模式。
- 新增 `BatchTaskDaemonGuardTests`，覆盖 daemon worker 防护分支和 Celery 入口成功收敛分支。

## 风险复盘

- 当前没有做浏览器级或真实 Celery worker 端到端复测，证据以代码级和定向单测为主。
- 仓库现有部分 `TransactionTestCase` 会受 PostgreSQL TRUNCATE 保护影响，不能拿来作为这次修复的稳定验收基线。

## 下一步

- 建议你在实际 worker 环境里再跑一次同样的批量任务 `run_mode=2`，确认这条错误日志不再出现。
