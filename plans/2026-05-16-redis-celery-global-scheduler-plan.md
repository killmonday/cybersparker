# Redis + Celery 全局任务调度与高并发扫描改造计划

## 做什么

把当前由 Django 请求线程直接创建后台线程/子进程的任务执行模式，改造成 Redis + Celery 驱动的全局任务调度架构，并围绕全局资源预算控制系统稳定性：

- 所有扫描任务共享全局网络并发预算，目标总 in-flight HTTP 请求上限为 2k。
- 全局线程数量必须小于 2k。
- 全局协程/greenlet 数量必须小于 8k。
- PostgreSQL 真实连接数量控制在 100 个以内。
- 数据库连接获取超时或写入失败时，结果数据不能丢失，应进入可重试的持久化缓冲。
- `identify_result` / 自动识别任务的 Web 请求环节替换当前阻塞式 `requests` 模式，改为 `asyncio/aiohttp` 或 gevent 高并发调度。
- `identify_result` / 自动识别任务的指纹识别环节保留受控线程池，后续可按压测结果评估是否改为进程池。
- `identify_result` / 自动识别任务的漏洞验证环节保持现有线程/gevent 兼容模式，不强制异步化插件脚本。
- `batch_expload_Task` 沿用现有线程/gevent 执行方式，但纳入 Celery 与全局资源预算管理。
- 评估 `exploadTask` 单任务模块是否可被 `batch_expload_Task` 替代，并给出迁移/删除前置条件。

## 为什么

当前架构的问题不是单点代码错误，而是任务执行模型缺少全局调度边界：

- Django Web 进程负责请求响应，同时直接启动长生命周期扫描线程，Web 稳定性容易被扫描任务拖累。
- `THREAD_DIC`、`BATH_TASK_DIC`、`KILL_AUTO_TASK_DIC` 是进程内存状态，服务重启、多 worker、多机器部署时都不可靠。
- 单个任务的 `thread_num` 只限制单任务参数，无法限制全局线程数、全局协程数、全局网络并发和数据库写入压力。
- 2k 总网络并发是 IO 密集型目标，不适合用 2k OS 线程承载，也不应把 PostgreSQL 连接数扩到 2k。
- 数据库连接池超时属于高压场景下的正常故障模式之一，必须保证结果先进入可重试缓冲，不能因为拿不到 DB 连接而丢数据。

## 当前模块判断

### `exploadTask` 单任务模块

当前单任务模型 `EXPTask` 具备：

- 单插件 FK：`EXPTask.EXP`。
- 执行模式：`taskType=Verify/Attact`。
- 攻击参数：`cmd_input`。
- 输入源：上传文件、历史结果。
- 执行器：`single_task_executor.Task_handler`，仅线程模式。

### `batch_expload_Task` 批量任务模块

当前批量任务模型 `batch_EXPTask` 具备：

- 多插件/全部插件：`EXP` 为逗号分隔字符串。
- 执行模式：线程 / gevent 协程子进程。
- 输入源更丰富：上传文件、历史漏洞资产、历史上传文件、空间测绘实时查询、历史空间测绘结果。
- 执行器：`batch_task_executor.Task_handler`。
- 当前漏洞执行逻辑主要调用插件 `verify`，未覆盖单任务的 `Attact + cmd_input` 语义。

### 是否可以删除 `exploadTask`

结论：**不能立即删除，但可以作为后续弃用候选。**

理由：

- 如果业务只使用 `Verify` 扫描，`batch_expload_Task` 基本可以覆盖单任务，并且能力更强。
- 如果仍有人使用 `Attact` / `cmd_input`，当前批量任务没有等价能力，直接删除会丢功能。
- 删除前应先做一次实际使用审计，并决定：
  - 要么在批量任务中补齐 `taskType=Attact` 和 `cmd_input`；
  - 要么将攻击类交互功能迁移到调试/手工执行入口；
  - 要么确认生产环境无人使用后正式下线。

建议：本次大改造阶段先**冻结单任务新增能力**，保留兼容；完成批量任务能力补齐和使用审计后，再做删除迁移。

## 总体架构

```text
Django Web
  - 创建/编辑/停止/查看任务
  - 不直接启动长生命周期扫描线程
  - 写任务记录，投递 Celery task
        ↓
Redis
  - Celery broker
  - 全局资源令牌：HTTP、线程、协程、DB writer
  - stop flag / pause flag / heartbeat
  - 结果持久化缓冲：Redis Streams 或可靠队列
        ↓
Celery Workers
  - auto_scan 队列
  - batch_scan 队列
  - maintenance / result_writer 队列
        ↓
扫描执行器
  - Web 请求层：asyncio/aiohttp 或 gevent
  - 指纹识别层：受控线程池，必要时评估进程池
  - 漏洞验证层：保留现有线程/gevent 兼容插件模式
  - DB writer：少量 worker，批量 upsert，失败可重试
        ↓
PostgreSQL
  - 真实连接总量控制在 100 内
```

## 核心设计

### 1. Redis + Celery 任务调度

新增 Celery 基础设施：

- Redis 作为 broker。
- 是否使用 Redis result backend 需谨慎；任务状态以数据库为准，Celery result 只作辅助。
- 至少拆分队列：
  - `auto_scan`：自动识别任务。
  - `batch_scan`：批量漏洞任务。
  - `result_writer`：结果落库或补偿写入。
  - `maintenance`：清理、恢复、超时巡检。

Celery 配置建议：

- `worker_prefetch_multiplier = 1`，避免 worker 预取过多长任务。
- `task_acks_late = True`，worker 崩溃时任务可重新投递。
- `task_reject_on_worker_lost = True`。
- 设置 `task_soft_time_limit` / `task_time_limit`，但长扫描任务应结合心跳和分片设计，不能只靠超时硬杀。
- 设置 `worker_max_tasks_per_child` 和 `worker_max_memory_per_child`，降低长任务内存泄漏风险。
- 不建议“一个 URL 一个 Celery task”；建议“一个扫描任务一个 Celery task”或“一个目标分片一个 Celery task”。

### 2. 全局资源预算

使用 Redis 实现带 TTL 的分布式资源令牌。

建议资源键：

```text
resource:http_inflight      上限 2000
resource:threads           上限 1800~1900，硬性小于 2000
resource:coroutines         上限 8000
resource:db_writers         上限 8~16
resource:running_auto_scan  按机器能力设置，例如 1~3
resource:running_batch_scan 按机器能力设置，例如 1~4
```

规则：

- 启动任务前先申请任务级资源预算，申请不到则排队或拒绝启动。
- 发起 HTTP 请求前申请 `http_inflight` token，请求完成后释放。
- 创建线程池前申请线程预算，线程池退出后释放。
- 创建 aiohttp task/gevent greenlet 前申请协程预算，完成后释放。
- 所有资源 token 必须带 TTL 和 owner heartbeat，worker 崩溃后可自动回收。
- 资源管理必须用 Redis Lua 脚本保证原子性，避免并发超卖。

### 3. 数据库连接预算

目标：PostgreSQL 真实连接数小于 100。

建议调整方向：

```text
PostgreSQL max_connections = 100
Django / Celery 每进程 DB pool 建议从 20+10 收紧到 5+2 或 8+2
DB writer worker 数量控制在 2~8
```

预算公式：

```text
总连接预算 = Web 进程数 × Web 每进程池上限
          + Celery worker 进程数 × Worker 每进程池上限
          + gevent/batch 子进程数 × 子进程池上限
          + 管理/迁移/监控预留
          <= 100
```

实施要求：

- 后台 worker 每次 ORM 后继续使用 `finally: connection.close()` 归还连接池连接。
- DB writer 是数据库写入主路径，其他扫描 worker 尽量不直接高频写库。
- 任务状态更新可节流，例如进度百分比变化、固定时间窗口或终态时写入。

### 4. 数据不丢失的 DB 写入策略

数据库连接获取超时或写入失败时，不能直接丢弃结果。

建议新增“结果事件”持久化缓冲：

- 首选 Redis Streams + consumer group。
- 每条扫描结果先写入 Redis Stream。
- DB writer 从 Stream 消费。
- 只有成功写入 PostgreSQL 后才 ACK。
- 如果 DB 连接超时、`OperationalError`、`TimeoutError`，不 ACK，延迟重试。
- 结果事件必须带幂等键，避免重试造成重复数据。

幂等键建议：

```text
identify_result: task_id + target + product
exp_result: task_id + target + exp_id + plugin_name
batch_result: task_id + target + plugin_name
```

Redis 可靠性要求：

- 开启 AOF 或合适的持久化策略。
- 不允许对未落库结果 Stream 使用会丢数据的近似 `MAXLEN` 裁剪。
- 对 pending 过久的消息做巡检和 reclaim。
- Redis 不可用时，应进入本地 append-only spool 文件作为最后兜底；恢复后再回放。

### 5. `identify_result` Web 扫描环节改造

当前 `auto_exp_task.request_scan()` 使用阻塞式 `requests.get()`。

建议改造为独立网络调度层：

```text
producer 读取目标
  -> async HTTP scheduler
  -> aiohttp ClientSession / TCPConnector
  -> 全局 http_inflight token
  -> bounded response queue
```

优先推荐 `asyncio/aiohttp`：

- 更适合大量 HTTP in-flight。
- 不影响现有漏洞插件的同步线程模式。
- 请求层与插件执行层天然隔离。

必须保持的行为：

- timeout 语义与当前任务兼容。
- 代理配置与当前 `ProxySetting` 兼容。
- 不配置代理时禁止自动读取系统环境代理，等价于 `requests` 当前修复后的行为。
- HTTPS 证书校验策略与当前项目保持一致。
- 返回字段兼容当前指纹识别输入：header、content/html、title、status_code、error。

队列必须有上限：

```text
raw_response_queue maxsize
fingerprint_queue maxsize
exp_queue maxsize
result_event_queue maxsize
```

下游队列满时，上游停止继续发起 HTTP 请求，形成背压。

### 6. 指纹识别环节

用户判断该环节偏 CPU 密集，当前阶段保留线程池，但必须受全局线程预算控制。

计划：

- 将 `fingerpoint_consumer` 改为受控 `ThreadPoolExecutor` 或固定线程池。
- 启动前申请线程预算。
- 指纹数据继续一次性加载到内存，避免 N+1 DB 查询。
- 如果压测证明 GIL 导致 CPU 饱和且线程扩展无效，再评估 `ProcessPoolExecutor`。
- 进程池评估时必须考虑指纹规则序列化成本、内存放大和 worker 初始化耗时。

建议默认：

```text
fingerprint_workers = min(CPU核数 × 2, 全局线程剩余额度, 100~200)
```

### 7. 漏洞验证环节

保持现有线程/gevent兼容模式，不强行异步化插件。

理由：

- 现有漏洞脚本通常按同步阻塞方式编写。
- 插件生态不具备统一异步接口。
- 人力不足以维护全部插件异步改造。

改造边界：

- 自动扫描任务中的漏洞验证 worker 仍可使用线程池。
- 批量任务继续保留线程/gevent run mode。
- 漏洞验证 worker 必须纳入全局线程/协程预算。
- 插件执行结果不直接高频写 DB，而是写入结果事件缓冲。

### 8. `batch_expload_Task` 任务

沿用当前线程/gevent执行方式，但纳入 Celery 与全局资源管理：

- Django 只投递 Celery task，不直接启动 `Thread` 或 `multiprocessing.Process`。
- Celery worker 内部根据 `run_mode` 选择线程或 gevent。
- gevent 模式继续保留子进程隔离策略，避免 monkey patch 影响 Web/Celery 主进程。
- 启动前申请线程/协程预算。
- 结果写入改为结果事件缓冲 + DB writer。
- 停止任务改为 Redis/DB stop flag，执行器循环主动检查。

## 分阶段实施计划

### 阶段 0：基线与保护

目标：不改变执行模型，先建立可观测基线。

- 记录当前任务线程数、连接数、队列长度、任务耗时。
- 增加统一资源配置项，但暂不强制启用。
- 梳理 `THREAD_DIC`、`BATH_TASK_DIC`、`KILL_AUTO_TASK_DIC` 的替代状态模型。
- 确认 `exploadTask` 的实际使用情况，尤其是 `Attact/cmd_input`。

验收：

- 可以在任务运行时看到线程数、DB 连接数、任务状态、队列长度。
- 不改变用户功能。

### 阶段 1：引入 Redis + Celery 基础设施

目标：Web 与任务执行解耦。

- 增加 Celery app 配置。
- 增加 Redis broker 配置。
- 新增队列：`auto_scan`、`batch_scan`、`result_writer`、`maintenance`。
- Django 启动任务改为投递 Celery task。
- Celery task 内部暂时调用现有执行器，降低第一阶段风险。
- 停止任务改为写 Redis/DB stop flag，旧内存字典只作为兼容过渡。

验收：

- Web 进程不再直接创建长生命周期扫描线程。
- Celery worker 可独立启动、停止、重启。
- worker 崩溃后任务状态可恢复为 stopped/failed/retry。

### 阶段 2：全局资源调度器

目标：限制全局线程、协程、HTTP、DB writer 预算。

- 实现 Redis 原子资源令牌。
- 实现资源 lease TTL + heartbeat + 自动回收。
- 任务启动前做预算申请。
- 执行器创建线程/协程前申请资源。
- 资源不足时任务进入 queued/waiting，不直接失败。

验收：

- 总线程数硬性小于 2k。
- 总协程/greenlet 数硬性小于 8k。
- 总 HTTP in-flight 小于 2k。
- worker 异常退出后资源 token 可回收。

### 阶段 3：结果事件缓冲与 DB writer

目标：DB 超时不丢数据。

- 新增结果事件结构。
- 新增 Redis Streams 结果缓冲。
- 新增 DB writer Celery task / worker。
- 所有结果先写 Stream，再由 DB writer 批量 upsert。
- DB 写成功后 ACK。
- DB 连接超时、连接池耗尽、数据库异常时不 ACK，延迟重试。
- 增加 pending 消息巡检和 reclaim。

验收：

- 人为降低 DB pool 或模拟连接超时，结果不丢失。
- 恢复 DB 后结果可补写。
- 重试不会产生重复结果。
- PostgreSQL 连接总数小于 100。

### 阶段 4：自动识别 Web 扫描 async 化

目标：用少量线程承载 2k 全局 HTTP in-flight。

- 抽离当前 `request_scan` 为统一 async HTTP fetcher。
- 使用 `aiohttp.ClientSession` + connector limit。
- 每次请求前申请全局 HTTP token，请求结束释放。
- 保持代理、TLS、timeout、title/header/content/status_code 兼容。
- 将响应写入 bounded queue，给指纹识别线程池消费。
- 下游积压时触发背压，暂停发新请求。

验收：

- 总 HTTP in-flight 可达到 2k。
- OS 线程数不随 HTTP 并发线性增长。
- 下游 DB 或指纹识别变慢时，网络层自动降速，不爆内存。

### 阶段 5：指纹识别与漏洞验证并发治理

目标：保留现有同步生态，同时纳入全局预算。

- 指纹识别使用固定线程池并申请线程预算。
- 漏洞验证保留线程/gevent模式。
- 自动扫描漏洞验证与批量任务共享全局线程/协程预算。
- 对 CPU 饱和场景补充可选进程池评估，不作为首批必做。

验收：

- 指纹识别高负载下不会无限增线程。
- 漏洞验证插件不需要异步改造即可继续运行。
- 线程/协程预算持续受控。

### 阶段 6：`exploadTask` 去留决策

目标：决定是否删除单任务模块。

- 统计线上/本地数据中 `EXPTask.taskType=Attact` 和 `cmd_input` 使用情况。
- 检查前端入口、API、结果页是否仍依赖单任务语义。
- 如果确认要删除：
  - 先在批量任务补齐单插件 verify 的体验。
  - 决定是否补齐 attack/cmd_input。
  - 做数据迁移或只读归档。
  - 前端隐藏入口，保留一版兼容只读结果页。
- 如果暂不删除：
  - 单任务也迁移到 Celery。
  - 但不再新增能力。

验收：

- 有明确删除/保留结论。
- 删除前没有功能缺口。

## 关键配置建议

```python
GLOBAL_HTTP_INFLIGHT_LIMIT = 2000
GLOBAL_THREAD_LIMIT = 1800
GLOBAL_COROUTINE_LIMIT = 8000
GLOBAL_DB_WRITER_LIMIT = 8
POSTGRES_MAX_CONNECTIONS_TARGET = 100
DJANGO_DB_POOL_SIZE = 5  # 或 8，需按 worker 数计算
DJANGO_DB_MAX_OVERFLOW = 2
AUTO_SCAN_DEFAULT_NETWORK_CONCURRENCY = 1000
AUTO_SCAN_MAX_NETWORK_CONCURRENCY = 2000
AUTO_SCAN_FINGERPRINT_WORKERS = 100
AUTO_SCAN_EXPLOIT_WORKERS = 50
BATCH_DEFAULT_WORKERS = 50
RESULT_DB_BATCH_SIZE = 200~1000
RESULT_DB_FLUSH_INTERVAL_SECONDS = 1
```

实际值必须按部署进程数修正，原则是：

```text
Web进程池连接 + Celery进程池连接 + 子进程池连接 + 预留 <= 100
```

## 验证计划

### 单元测试

- Redis 资源令牌原子申请/释放。
- token TTL 超时回收。
- stop flag 生效。
- DB writer 幂等 upsert。
- DB timeout 时消息不 ACK、不丢失。
- pending Redis Stream 消息 reclaim。
- 队列满时上游背压。

### 集成测试

- Celery eager/fake Redis 模式验证任务状态流转。
- 本地 Redis 集成验证资源预算。
- 模拟 PostgreSQL 连接池耗尽，验证结果补偿写入。
- 模拟 worker 崩溃，验证任务状态和资源 token 回收。

### 压测

- 使用本地 mock HTTP server 模拟 2k in-flight。
- 观察：
  - 总线程数 < 2k。
  - 总协程/greenlet < 8k。
  - PostgreSQL 连接数 < 100。
  - Redis pending 结果可最终清零。
  - 任务停止/重启后无资源泄漏。
  - 进程内存稳定，无无限队列堆积。

## 风险

- Celery + Redis 引入新的运维组件，必须配置 Redis 持久化、监控和容量告警。
- Redis 全局资源令牌如果实现不严谨，会出现 token 泄漏或超卖。
- aiohttp 与当前 requests 行为在代理、TLS、编码、异常类型上存在差异，需要兼容测试。
- 指纹识别若确实 CPU 密集，线程池可能受 GIL 限制；后续可能需要进程池，但进程池会带来内存放大。
- gevent monkey patch 仍需保持子进程隔离，避免污染 Celery/Web 主进程。
- Redis Streams 如果配置了错误的裁剪策略，可能导致未落库结果丢失。
- 长任务 Celery ACK/重试语义复杂，必须以业务任务状态表为真源，Celery 状态只做执行层辅助。
- `exploadTask` 删除前如果未补齐 `Attact/cmd_input`，会造成功能回退。

## Backlog 拆分结果（2026-05-16）

本计划已拆分为阶段二候选 backlog，当前状态均为 `未开始`、`未验收`，等待用户确认阶段二主线和优先级。

| Backlog ID | 模块 | 优先级 | 范围 |
|---|---|---|---|
| BL-SCHED-001 | 运行部署与可观测性 | P0 | 全局调度基线观测与状态模型 |
| BL-SCHED-002 | 运行部署与可观测性 | P0 | Redis + Celery 基础设施 |
| BL-AUTO-002 | 指纹与自动识别 | P0 | 自动识别任务投递迁移到 Celery |
| BL-BATCH-007 | 任务执行 | P0 | 批量任务投递迁移到 Celery |
| BL-SCHED-005 | 运行部署与可观测性 | P0 | Redis 全局资源预算令牌 |
| BL-SCHED-006 | 运行部署与可观测性 | P0 | 结果事件缓冲与 DB Writer |
| BL-AUTO-003 | 指纹与自动识别 | P1 | 自动识别 Web 请求 async 化 |
| BL-AUTO-004 | 指纹与自动识别 | P1 | 自动识别指纹与漏洞验证并发治理 |
| BL-BATCH-008 | 任务执行 | P1 | 批量任务全局预算与结果事件治理 |
| BL-SCHED-007 | 运行部署与可观测性 | P1 | 结果缓冲本地 Spool 治理增强 |
| BL-TASK-002 | 任务执行 | P1 | 单任务 exploadTask 去留审计与迁移决策 |

独立评审结论：原草案需修改后可用。已按评审意见补充依赖链、量化验收条件，拆分 auto/batch 投递迁移，去掉 `BL-SCHED-001` 与 `BL-TASK-002` 的范围重复，并将本地 spool 兜底拆为 P1 独立项。

Mode H 共识结论（2026-05-16）：`BL-SCHED-001`、`BL-SCHED-002`、`BL-AUTO-002`、`BL-BATCH-007`、`BL-SCHED-005`、`BL-SCHED-006` 已完成 Planner → Architect → Critic 共识循环，最终 verdict 为 APPROVE。

### Mode H 最终决策

- DB 是业务终态真源，Redis 是运行态/协调真源；`THREAD_DIC` / `BATH_TASK_DIC` / `KILL_AUTO_TASK_DIC` 仅作为本机执行器句柄缓存，不得反向覆盖 DB 终态。
- 执行顺序固定为：`BL-SCHED-001` 状态模型 → `BL-SCHED-002` Celery + DB 预算硬闸门 → `BL-AUTO-002` / `BL-BATCH-007` 迁入口 + stop bridge → `BL-SCHED-005` owner/resource lease 与 heartbeat → `BL-SCHED-006` Stream + 最小 spool。
- `auto_scan_tasks`、`batch_EXPTask` 需要迁移状态字段：`queued`、`failed`、`dispatch_token`、`owner`、`stop_requested`、`heartbeat_at`、`last_error`，并补 UI “等待/失败”映射。
- 所有终态写 DB 必须通过统一 CAS helper：仅当前 `dispatch_token/owner` 且 DB 仍非终态时可写 `success/stopped/failed`；旧 token、重复消息、迟到 stop 一律 no-op。
- `BL-SCHED-002` 必须前置 DB 连接预算硬闸门：`Web池 + Celery池 + gevent子进程池 + 预留 <= 100`；超限时 worker 启动失败且 Celery dispatch 被拒绝开启。
- `BL-AUTO-002` / `BL-BATCH-007` 自带最小 stop bridge：worker/执行器轮询 DB `stop_requested` 与 Redis stop flag，并映射到本地 `exit_flag`。
- batch gevent 模式本阶段保留 `terminate()` fallback，cooperative stop 留后续细化。
- `BL-SCHED-006` 必须包含最小 append-only spool；`BL-SCHED-007` 只做 spool 轮转、归档、巡检和回放治理增强。
- 结果“不丢不重”必须有唯一键/幂等列 + upsert 验收：识别结果 `task_id + target + product`；自动联动漏洞结果 `task_id + target + exp_id`（无 `exp_id` 时 `task_id + target + plugin_name`）；批量漏洞结果 `task_id + target + plugin_name`。

### ADR

- Decision：分阶段迁移，前置状态模型、终态 CAS、DB 预算硬闸门、auto/batch stop bridge、最小 spool。
- Drivers：Web 解耦、任务可停止、避免重复执行、结果可靠落库。
- Alternatives：一步到位大改；无 spool 仅依赖 Redis。
- Why chosen：故障面最小、回滚路径最短，每阶段都可独立验证。
- Consequences：过渡期状态协调更复杂；需要严格执行 dispatch token、owner 和 CAS 质量门。
- Follow-ups：`BL-SCHED-007` 增强 spool 治理；后续再评估 async HTTP、插件异步化和单任务去留。

### 后续执行质量门

- schema/UI 映射测试必须覆盖“等待/失败”。
- 旧 token、重复消息、迟到 stop 不得覆写终态。
- 预算超限时 worker 必须硬失败且 dispatch 被拒。
- auto/batch stop bridge 必须生效；gevent 至少通过 terminate fallback 收敛到 stopped。
- Redis down → spool → replay 后三类结果表必须“不丢不重”。

## 后续新会话执行建议

建议不要一次性全部改完，应按以下顺序开工：

1. 先实现 Celery 基础设施和任务投递，不改扫描核心。
2. 再实现 Redis 全局资源预算。
3. 再实现结果事件缓冲和 DB writer，先解决“不丢数据”。
4. 再改自动识别 Web 请求层为 aiohttp/gevent。
5. 最后评估 `exploadTask` 删除或迁移。

每阶段都必须能独立验证并可回滚。
