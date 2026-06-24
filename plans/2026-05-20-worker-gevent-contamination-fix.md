# Celery worker gevent 污染修复

- 状态：已完成
- 创建时间：2026-05-20

## 做什么

修复批量任务 `run_mode=2` 在 daemon Celery worker 内执行后，污染同一 worker 进程运行时，导致后续自动扫描任务在线程池里报 `gevent.exceptions.LoopExit` 的问题。

## 为什么

上一轮为了规避 `daemonic processes are not allowed to have children`，把 daemon worker 下的 gevent 模式改成了在当前 worker 进程里直接执行。这样会在已加载 Django/requests/线程池的 Celery worker 进程里做 gevent monkey patch，影响同进程后续任务，自动扫描的 `ThreadPoolExecutor` 就被污染到了 gevent queue。

## 怎么做

1. 保留普通 Web 路径 `run_mode=2` 的 gevent 子进程模式。
2. daemon Celery worker 下不再尝试 gevent 执行，也不再在当前 worker 进程里打 gevent patch。
3. 对 `run_mode=2` 做最小安全降级：在 daemon worker 内改用线程模式执行。
4. 补定向回归，覆盖 daemon worker 下不再走 gevent 模式、不再起子进程。

## 风险

- 这是行为降级：daemon worker 下 `run_mode=2` 不再真正使用 gevent 并发模型。
- 但比继续污染 worker 进程安全得多，影响面更小。
- 当前没有真实 worker 端到端复测，只做了代码级和定向测试验证。

## 验证

- [x] daemon worker 下 `run_mode=2` 不再 `spawn` 子进程。
- [x] daemon worker 下 `Task_handler` 入参中的 `run_mode` 被降级到线程模式。
- [x] `/opt/venv/bin/python manage.py test app_cybersparker.tests.BatchTaskDaemonGuardTests --keepdb --noinput -v 2` 通过。
- [x] `/opt/venv/bin/python manage.py check` 0 issues。

## 结果

- 普通 Web 路径仍保留 gevent 子进程隔离。
- daemon Celery worker 下改为线程模式执行，避免 gevent monkey patch 污染同一 worker 进程。
- 这样可以同时避开：
  - daemon 进程二次起子进程断言
  - gevent SSL/TLS 递归
  - gevent 污染后续自动扫描线程池

## 风险复盘

- 当前最重要的是运行时安全收敛，不是维持 daemon worker 下的 gevent 并发模型原样不变。
- 如果后续确实需要在 Celery 下保留真正的 gevent 模式，应该拆独立执行通道，而不是在当前 prefork worker 里继续打 monkey patch。

## 下一步

- 建议你在真实 worker 环境里先重跑两类任务：
  1. 批量任务 `run_mode=2`
  2. 紧接着再跑自动扫描任务
- 重点确认自动扫描不再出现 `gevent.exceptions.LoopExit`。
