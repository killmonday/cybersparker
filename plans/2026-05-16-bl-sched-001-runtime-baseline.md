# BL-SCHED-001 全局调度基线观测与状态模型

## 做什么
- 新增只读诊断入口，输出线程数、数据库连接池占用、运行时队列长度与任务耗时基线。
- 增加统一资源配置项，但保持 observe-only，不改变现有任务执行行为。
- 输出 `EXPTask.taskType` 分组数量与非空 `cmd_input` 数量，供 `BL-TASK-002` 复用。
- 在控制面文档中明确三类内存字典的替代状态模型、迁移边界与 UI 兼容映射。

## 为什么
- 阶段二需要先拿到线程、连接池与任务句柄的可观测基线，再继续引入 Celery/Redis。
- 当前 `THREAD_DIC`、`BATH_TASK_DIC`、`KILL_AUTO_TASK_DIC` 只代表本机执行句柄，不能继续承担业务终态真源。
- `BL-TASK-002` 是否保留单任务模块依赖实际使用量，不应凭感觉决策。

## 怎么做
1. 新增 `scheduler_runtime_service`，集中采集诊断数据、统一资源配置、状态模型规划与单任务使用统计。
2. 暴露 `/runtime/diagnostics` 只读接口，支持按 `task_type` / `task_id` 查看当前批量/自动/单任务诊断。
3. 在 `cybersparker/settings.py` 增加 observe-only 基线配置与阶段二状态模型字段规划常量。
4. 增加针对空闲态、运行态和单任务使用统计的测试，确保入口可测且不影响原有执行链路。
5. 同步 backlog、模块文档、项目控制台、当前实现总览与 CHANGELOG。

## 风险
- `db_pool_checked_out` 必须基于 `dj_db_conn_pool.core.pool_container` 读取，不能为了观测而额外创建数据库连接。
- 批量任务协程子进程无法直接暴露内部 queue，只能先提供进程句柄计数与线程模式下的内部队列长度。
- 本项只做基线观测与规划，不应顺手修改任务启动/停止/执行路径。

## 当前状态
- [已完成] 读取控制面、模块文档、任务入口、执行器与连接池实现。
- [已完成] 实现诊断服务、路由与配置项。
- [已完成] 增加针对空闲态、运行态与使用量统计的测试并完成验证。
- [已完成] 同步 backlog、项目控制台、模块文档、实现总览与 CHANGELOG。

## 验证
- `python manage.py test app_cybersparker.tests.SchedulerRuntimeDiagnosticsTests`：通过（3/3）。
- `python manage.py check`：通过，0 issues。
- `python manage.py test app_cybersparker.tests`：失败；失败项为既有 `BatchTaskGeventRunnerTests.test_coroutine_mode_uses_lightweight_gevent_runner_as_spawn_target` 与 `test_stopping_running_batch_task_sets_valid_stop_status`，报错为 SQLAlchemy `_ConnectionFairy.dbapi_connection is None`。当前证据指向既有批量任务/连接池测试环境问题，不是本次新增诊断入口逻辑回归。

## 结果
- 新增 `/runtime/diagnostics` 只读入口与 `app_cybersparker/services/scheduler_runtime_service.py`。
- 统一输出 observe-only 资源配置、连接池占用、句柄计数、队列长度、任务耗时、状态模型规划与 `EXPTask` 使用量统计。
- 记录当前基线：`EXPTask.taskType` 为 `Verify=6`、`Attact=0`，非空 `cmd_input=0`。

## 下一步
- 链式进入 `BL-SCHED-002 Redis + Celery 基础设施`。
