# 数据库连接池修复

## 做什么
修复线程化任务执行代码中 Django ORM 连接被后台线程长期持有的问题：线程入口先调用 `close_old_connections()` 清理继承/陈旧连接，每次 ORM 操作后用 `connection.close()` 在 `finally` 中把连接归还给 `dj_db_conn_pool` 的 SQLAlchemy 连接池。

## 为什么
- `dj_db_conn_pool` 配置为 `POOL_SIZE=20`、`MAX_OVERFLOW=10`，同一进程最多约 30 个池连接。
- 这些任务不是 Django 请求生命周期内执行，而是自建 `threading.Thread` / gevent 子进程；Django 不会自动在请求结束时清理线程连接。
- 已验证当前后端 `dj_db_conn_pool.core.mixins.core.DatabasePoolWrapperMixin.close()` 会 release connection to pool，因此后台线程写库后需要确定性调用 `connection.close()`。
- 前任修复把 `connection.close()` 替换成 `close_old_connections()` 是错误方向：Django 原生 `close_old_connections()` 只关闭过期/不可用连接，不保证释放健康连接，导致用户复测时触发 `QueuePool limit of size 20 overflow 10 reached`。

## 怎么做
1. 保留线程入口 `close_old_connections()`：用于清理请求外线程启动时可能继承的陈旧/坏连接。
2. 对后台线程内每次 ORM 查询/写入使用 `try...finally: connection.close()`：确保成功、异常、early return 路径都归还连接池。
3. 表单和执行器双层限制 `thread_num`：新增 `MAX_EXPLOIT_THREAD_NUM`，并在单任务、批量任务、自动扫描三个入口校验；执行器构造函数再次裁剪，防止旧数据或非表单入口绕过。
4. 保持原有业务逻辑、异常语义和进度节流策略，不做额外重构。

## 已完成
- `auto_exp_task.py`
  - 自动扫描执行器线程入口清理陈旧连接。
  - 指纹 EXP 映射预加载、任务完成/停止状态更新、producer 进度更新、识别结果写入、EXP 结果写入恢复 `finally: connection.close()`。
  - `thread_num` 在执行器层按 `MAX_EXPLOIT_THREAD_NUM` 裁剪。
- `single_task_executor.py`
  - 单任务执行器线程入口清理陈旧连接。
  - 完成状态更新、结果写入、停止状态、producer 进度更新恢复 `finally: connection.close()`。
  - `thread_num` 在执行器层按 `MAX_EXPLOIT_THREAD_NUM` 裁剪。
- `batch_task_executor.py`
  - 批量执行器线程入口清理陈旧连接。
  - EXP 缓存构建、最终状态更新、批量结果 `bulk_create`、进度落库恢复 `finally: connection.close()`。
  - `thread_num` 执行层从旧的 `6000` 裁剪改为复用 `MAX_EXPLOIT_THREAD_NUM`。
- `auto_scan_task.py` / `exp_task.py` / `batch_exp_task.py`
  - 新增 `clean_thread_num` 表单验证。
  - 启动后台线程前的 ORM 查询/更新恢复 `finally: connection.close()`，避免启动线程带着连接进入长时间 `join()` 或任务执行。
- `settings.py`
  - 新增 `MAX_EXPLOIT_THREAD_NUM = 50`。

## 验证
- `python -m py_compile` 覆盖 7 个变更 Python 文件：通过。
- `python manage.py check`：通过，0 issues。
- `gitnexus_detect_changes(scope=all)`：风险 `medium`，影响流程集中在任务启动/执行链路，符合本次修复范围。
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- .`：通过。
- `python -m ruff check --select F` 覆盖 7 个变更 Python 文件：通过。

## 风险
- `thread_num=50` 仍可能高于单进程池连接数上限 30；因为只有 ORM 段短暂占用连接，当前先以执行层归还连接为主。若压力测试仍出现排队，可继续把上限按任务类型收紧到 20~25。
- `batch_exp_task copy.py` 是遗留副本，仍可能保留旧模式；不属于运行入口，本次不改，记录为后续清理项。
- gevent 模式依赖子进程隔离；每个子进程有独立连接池，仍需通过实际压力测试确认数据库总连接数是否符合部署容量。
