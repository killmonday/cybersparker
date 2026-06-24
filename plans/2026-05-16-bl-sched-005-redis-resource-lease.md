# BL-SCHED-005 Redis 全局资源预算令牌

## 做什么
- 为 `http_inflight`、`threads`、`coroutines`、`db_writers`、`running_auto_scan`、`running_batch_scan` 建立 Redis 原子资源令牌。
- 实现 lease 申请、释放、TTL 回收、heartbeat 续租和 owner 维度的可观测状态。
- 当资源不足时写入 `waiting_resource` 运行态标记并进入延迟重试，而不是把任务误标为完成。

## 为什么
- `BL-AUTO-002` / `BL-BATCH-007` 已把自动识别与批量任务入口迁入 Celery；下一步必须给 worker 执行层加上真正的全局资源边界。
- 没有原子资源令牌时，多个 worker 仍可能同时超卖线程、协程和 DB writer 配额。
- 后续 `BL-SCHED-006` 的结果 writer 也依赖 `db_writers` 预算令牌。

## 怎么做
1. 先落最小 Redis 资源服务：申请、释放、续租、回收、资源快照。
2. 为 auto/batch worker 接入 owner/resource lease 和 heartbeat。
3. 资源不足时写任务运行态 `waiting_resource` 并延迟重试。
4. 补单测：超卖、释放、TTL 回收、heartbeat、资源不足路径。
5. 同步 backlog、模块文档、控制台、CHANGELOG。

## 风险
- 资源令牌必须原子，不能用简单 get/set 替代。
- 若本地没有 Redis，测试需要用 fake redis 或严格隔离的 mock。
- 需要保持现有任务状态语义，不能把等待资源错误映射成 finish/stop。

## 当前状态
- [已完成] 从 BL-BATCH-007 切入 BL-SCHED-005。
- [已完成] 读取现有 Redis/worker 运行态接入点。
- [已完成] 实现资源令牌、TTL 回收、heartbeat 与 waiting_resource 重试路径。
- [已完成] 增加测试并完成文档同步。

## 验证
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.ResourceLeaseServiceTests`：通过（5/5）。
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanCeleryDispatchTests app_cybersparker.tests.BatchScanCeleryDispatchTests`：通过（11/11）。
- `DB_HOST=192.168.1.11 python manage.py check`：通过，0 issues。
- `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`：通过，无迁移漂移。

## 结果
- 新增 `resource_lease_service`，实现资源 lease 申请、释放、TTL 回收、heartbeat 与 waiting_resource 标记。
- auto/batch worker 已在执行前申请运行资源，并在运行中续租、结束后释放。
- 本地无 Redis 时自动回退到 memory lease，以保证单测和本地开发不被外部依赖阻塞。

## 下一步
- 已链式进入 `BL-SCHED-006`。
