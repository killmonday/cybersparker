# 批量任务线程/协程分流

- 状态：已完成
- 创建时间：2026-05-20

## 做什么

把批量任务的线程模式和协程模式分流到不同 Celery 队列和不同 worker，避免两种运行时互相污染。

## 为什么

当前问题已经证明：
1. `run_mode=2` 在 prefork worker 里直接跑会遇到 daemon 不能再起子进程的问题。
2. 为了绕开这个问题，如果在同一个 worker 进程里直接打 gevent patch，又会污染后续自动扫描任务的线程池。
3. 线程模式和协程模式如果继续共用一个 worker，后面还会不断互相影响。

所以要同时满足“线程模式正常、协程模式也正常”，最稳的做法就是分流。

## 怎么做

1. 新增独立队列 `batch_scan_gevent`，只接收批量任务 `run_mode=2`。
2. 普通线程模式继续投递到原 `batch_scan` 队列。
3. `start_celery.sh` 改成同时启动两个 worker：
   - `worker_main`：处理 `auto_scan,batch_scan,result_writer,maintenance`
   - `worker_gevent`：处理 `batch_scan_gevent`
4. `worker_gevent` 使用 `-P solo -c 1`，避免 gevent patch 污染其它任务。
5. 保留 daemon worker 下的安全降级逻辑，作为兜底，而不是主执行路径。

## 风险

- 运维复杂度会上升：要同时维护两个 worker 和两份日志。
- 资源预算需要重新分配，不能再把线程/协程看成同一类资源。
- 当前只做了代码级和定向测试，还没有真实 worker 端到端复测。

## 验证

- [x] `batch_scan_gevent` 队列已加入 Celery 配置。
- [x] `run_mode=2` 启动时会投递到 `batch_scan_gevent`。
- [x] `/opt/venv/bin/python manage.py test app_cybersparker.tests.CeleryRuntimeInfrastructureTests.test_celery_app_declares_expected_queues app_cybersparker.tests.BatchQueueRoutingTests app_cybersparker.tests.BatchTaskDaemonGuardTests --keepdb --noinput -v 2` 5/5 通过。
- [x] `/opt/venv/bin/python manage.py check` 0 issues。
- [x] `sh -n start_celery.sh` 通过。

## 结果

- 线程模式和协程模式现在已经具备分流基础：不同队列、不同 worker、不同日志。
- 自动扫描仍留在主 worker，不再和 gevent 运行时共用同一执行进程。
- gevent worker 目前采用 `solo`，优先保证运行时隔离和稳定，再谈进一步并发优化。

## 推荐资源分配

- 主 worker（线程模式 + 自动扫描 + writer）：
  - `CELERY_WORKER_CONCURRENCY=4`
  - `GLOBAL_THREAD_LIMIT=1200`
- gevent worker（协程模式）：
  - `-P solo -c 1`
  - `GLOBAL_COROUTINE_LIMIT=12000`
- 批量任务运行数建议先保持：
  - `RUNNING_BATCH_SCAN_LIMIT=1`

## 下一步

- 在真实环境复测：
  1. 跑一个批量任务 `run_mode=2`
  2. 再跑一个线程模式批量任务
  3. 再跑一个自动扫描任务
- 重点确认三者不再互相影响。
