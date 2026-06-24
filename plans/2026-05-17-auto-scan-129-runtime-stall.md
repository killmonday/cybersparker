# 自动扫描任务 129 自停/进度卡住排查

- 日期：2026-05-17
- 状态：进行中

## 做什么

复现并定位自动扫描任务 `id=129` 在启动后自动停止、进度不满 100%、卡住不继续的问题。

## 为什么

- 用户现场反馈该任务会自己停掉。
- 当前数据库里该任务已停在 `status=3`、`process=39.01%`、`phase=1`、`current_line=1170`，符合“未完成但已停止”的异常表现。
- 该问题影响自动扫描主链路，需要先拿到运行时证据，再决定最小修复点。

## 范围

- 启动 Redis、Django 后端、Celery worker。
- 重新启动 `id=129` 的自动扫描任务并观察日志、状态变化。
- 排查 `auto_scan_task.py`、`auto_exp_task.py`、`tasks.py`、相关运行时信号链路。
- 若确认根因，执行最小修复并补齐必要验证。

## 不做

- 不顺手改无关的自动扫描功能。
- 不扩大为整套调度系统重构。
- 不修改与本问题无关的 backlog 项。

## 当前已知事实

- `auto_scan_tasks(id=129)` 当前值：`status=3`、`process=39.01%`、`phase=1`、`current_line=1170`、`failed=False`、`stop_requested=False`、`pause_requested=False`。
- 目标文件为 `EXP_input/engine_assets/fofa_97fab16b66a54c2babd5b3bddb45494c.txt`。
- 项目文档显示自动扫描已在阶段二切到 Celery 投递，stop/pause 信号为 Redis 优先、DB 兜底。

## 风险

- 当前工作树已有大量未提交改动，结论必须区分“本次复现现象”和“仓库既有变更”。
- 运行时问题可能同时涉及 Redis 信号、Celery worker、结果事件缓冲、HTTP 请求并发治理，多点联动。
- 任务目标文件较大时，复现耗时可能偏长，需要结合日志和数据库状态同步判断。

## 验证计划

1. 启动 Redis、后端、Celery worker。
2. 用真实运行路径重启 `id=129`，持续观察 worker 日志与任务状态。
3. 确认停止时是：主动 stop、pause 误命中、异常退出、CAS 终态覆盖，还是执行器自然提前收敛。
4. 锁定根因后做最小修复。
5. 重新启动 `id=129` 或补最小回归验证，确认任务不会再次异常自停。

## 结果

- 待补充。
