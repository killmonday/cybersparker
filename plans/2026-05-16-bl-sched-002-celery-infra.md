# BL-SCHED-002 Redis + Celery 基础设施

## 做什么
- 引入 Celery app、Redis broker 配置和四个标准队列：`auto_scan`、`batch_scan`、`result_writer`、`maintenance`。
- 增加本地开发/启动入口和 eager 模式基础测试。
- 增加 DB 连接预算硬闸门与 Celery dispatch 可用性判断。
- 增加统一终态 CAS helper，为后续 auto/batch 投递迁移提供稳定边界。

## 为什么
- `BL-SCHED-001` 已给出线程、连接池和状态模型基线；下一步必须把 Web 请求线程和长任务执行基础设施解耦。
- Celery/Redis 是后续 stop bridge、全局资源令牌、结果缓冲与 DB writer 的共同底座。
- 若不先建立连接预算硬闸门，后续 worker 引入会再次放大 PostgreSQL 连接超卖风险。

## 怎么做
1. 先补 Celery/Redis 官方配置与项目内最小集成：`cybersparker/celery.py`、settings、队列定义、worker 启动命令。
2. 实现连接预算计算与 dispatch 可用性检查，确保预算超限时 worker 启动失败、dispatch 被拒。
3. 为 `auto_scan_tasks` / `batch_EXPTask` 增补阶段二运行态字段和统一 CAS helper，但暂不切换业务执行链路。
4. 增加 eager / fake broker 测试，验证 Celery app、四个队列、预算闸门和 CAS helper。
5. 完成后同步 backlog、控制台、模块文档、CHANGELOG，并直接进入 `BL-AUTO-002` / `BL-BATCH-007`。

## 风险
- 需要新增迁移；必须保证现有页面与 Django 启动在未启 worker 时保持兼容。
- 预算硬闸门必须只在 Celery 路径启用，不能误伤当前 Web 进程启动。
- CAS helper 设计必须允许后续 stop bridge / result writer 直接复用，避免再拆第二套终态保护逻辑。

## 当前状态
- [已完成] 同步 BL-SCHED-001 文档并切换到 BL-SCHED-002。
- [已完成] 读取 Celery/Redis 现状、依赖和 Docker 配置。
- [已完成] 实现 Celery 基础设施、预算闸门、终态 CAS helper 与本地开发配置。
- [已完成] 增加测试并完成运行验证。

## 验证
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.CeleryRuntimeInfrastructureTests`：通过。
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.SchedulerRuntimeDiagnosticsTests app_cybersparker.tests.CeleryRuntimeInfrastructureTests`：通过。
- `DB_HOST=192.168.1.11 python manage.py check`：通过，0 issues。
- `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`：通过，无迁移漂移。
- memory broker embedded worker + `inspect(destination=[worker.hostname]).active_queues()`：确认 4 个队列全部可见。
- `POSTGRES_MAX_CONNECTIONS_TARGET=15 celery -A cybersparker worker ...`：验证为 CLI 级硬失败，直接抛 `RuntimeError: Celery worker startup rejected ...` 并退出。

## 结果
- 新增 Celery app、四标准队列、dispatch 硬闸门、worker 启动预算闸门、统一 CAS helper。
- 新增 `docker-compose.yml` 的 `redis` 与 `worker` 本地开发服务。
- 为 `BL-AUTO-002` / `BL-BATCH-007` 提供可复用的 worker 入口、dispatch 规则和终态保护边界。

## 下一步
- 已链式进入 `BL-AUTO-002`，下一项继续 `BL-BATCH-007`。
