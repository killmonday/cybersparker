# BL-SCHED-006 结果事件缓冲与 DB Writer

## 做什么
- 为识别结果、自动联动漏洞结果、批量漏洞结果定义事件结构与幂等键。
- 建立 Redis Streams / memory stream / 最小 append-only spool 三层事件缓冲。
- 新增 `run_result_writer_task`，由 `result_writer` 队列消费事件并批量/幂等写入 PostgreSQL。
- 在 DB writer 上接入 `db_writers` 资源预算约束、pending reclaim 与 spool 回放。

## 为什么
- `BL-AUTO-002` / `BL-BATCH-007` 已迁入 Celery；没有事件缓冲时，结果仍然直接高频写库，DB 高压时仍会丢失或阻塞结果。
- 需要为后续 `BL-SCHED-007` 的 spool 治理提供最小可工作的 append-only 落点。
- 统一 writer 之后，auto/batch 结果都能通过同一幂等规则保证“不丢不重”。

## 怎么做
1. 新增 `result_event_service.py`，负责 publish / consume / reclaim / ack / spool replay。
2. 将 `save_indentify_to_db`、`save_exp_result_to_db`、`Task_handler.save_TaskResult` 改为写事件并投递 `run_result_writer_task`。
3. 在 writer 侧按三类流分别执行 upsert / merge，确保幂等。
4. DB 异常时不 ACK，保留 pending；Redis 不可用时落本地 spool；恢复后可 replay。
5. 增加测试覆盖 identify/auto_exp/batch 幂等、pending 保留、spool fallback/replay、writer task 处理。

## 风险
- 结果页当前仍使用旧结果表；writer 改造必须保持这些查询完全兼容。
- auto 识别结果当前表唯一键是 `(task_id, target)`，因此对产品维度需要做 merge 而不是新增重复行。
- 本项只做最小 spool，不实现轮转/归档/巡检增强；这些留给 `BL-SCHED-007`。

## 当前状态
- [已完成] 读取 backlog、计划和现有三条结果写入链路。
- [已完成] 实现事件缓冲、writer task、spool fallback 与 pending reclaim。
- [已完成] 将 auto/batch 结果写入改为 publish event + dispatch writer。
- [已完成] 增加测试并完成文档同步。

## 验证
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.ResultEventServiceTests app_cybersparker.tests.ResultWriterTaskTests`：通过（7/7）。
- `DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.ResourceLeaseServiceTests app_cybersparker.tests.AutoScanCeleryDispatchTests app_cybersparker.tests.BatchScanCeleryDispatchTests app_cybersparker.tests.ResultEventServiceTests app_cybersparker.tests.ResultWriterTaskTests`：通过（24/24）。
- `DB_HOST=192.168.1.11 python manage.py check`：通过，0 issues。
- `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`：通过，无迁移漂移。
- 当前库数据检查：三张结果表当前行数均为 0，且未发现重复幂等键样本，迁移无需先做历史去重。

## 结果
- 新增 `app_cybersparker/services/result_event_service.py` 与 `run_result_writer_task`。
- auto 识别结果、自动漏洞结果、批量漏洞结果均改为先写事件再由 writer 入库。
- 支持 Redis Stream、memory stream、spool fallback、pending reclaim 与 writer 资源预算约束。

## 下一步
- 已链式进入 `BL-SCHED-007`。
