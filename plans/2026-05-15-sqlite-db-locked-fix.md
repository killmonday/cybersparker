# fix: auto scan 任务 SQLite database is locked

## 问题
`Auto_exploit_Task_handler.run()` 启动 `thread_num × 2 + 1` 个写 DB 线程
（fingerpoint_consumer + exp_consumer + save_exp_result），所有线程同时写 SQLite。
SQLite 仅支持单个 writer，并发写入者在 busy_timeout(5s) 后抛 `OperationalError: database is locked`。

## 修复
双层：
1. **Django OPTIONS**: 设置 `timeout=30`，延长 SQLite 连接 busy wait 超时
2. **Handler 层**: 添加 `threading.Lock` 串行化同一 handler 实例内的 DB 写入，
   同时保护 filter→create 的 check-then-insert 竞态

## 结果
- `cybersparker/settings.py`: DATABASES 增加 `OPTIONS: {timeout: 30}`
- `auto_exp_task.py`: `__init__` 新增 `self._db_lock`；`save_indentify_to_db` 和
  `save_exp_result_to_db` 的 filter+create 用 `with self._db_lock` 包裹
- 编译通过，15/15 测试通过，影响分析 LOW

## 后续（2026-05-15）：PG 迁移后移除 SQLite workaround
项目已迁移至 PostgreSQL，不再需要线程锁和 SQLite 特定配置：
- `self._db_lock` 已移除
- `filter→exists→create` 替换为 `get_or_create()`（提供跨 handler 实例的重复插入防护）
- `settings.py` 中 SQLite timeout OPTIONS 已在 PG 迁移时移除
