# task_manage 目录约束

- 任务执行器运行在 Django 请求生命周期之外；线程入口先调用 `close_old_connections()` 清理陈旧连接。
- 执行器内每次 ORM 查询/写入后必须用 `try...finally: connection.close()` 归还 `dj_db_conn_pool` 连接池连接。
- 表单层校验 `thread_num` 后，执行器构造函数仍需按 `settings.MAX_EXPLOIT_THREAD_NUM` 二次裁剪，防止旧数据或非表单入口绕过。
