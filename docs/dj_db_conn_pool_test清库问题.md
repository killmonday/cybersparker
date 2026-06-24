# dj_db_conn_pool 导致 manage.py test 清空主库

> 记录日期：2026-05-26

## 问题

运行 `python manage.py test` 后，主库 `cybersparker` 的所有业务表数据被清空，表被重建（OID 变化）。

## 根因

`dj_db_conn_pool.backends.postgresql` 的连接池以 `self.alias`（即 `"default"`）为 key 缓存 SQLAlchemy 连接池。Django test runner 在创建 test 数据库后只修改 `settings_dict['NAME']`，连接池里已缓存的连接仍然指向主库：

```
settings_dict['NAME'] = 'test_cybersparker'   ← 代码以为切了
pool.get('default').connect()           ← 实际还连着 cybersparker
```

导致 test runner 的所有 schema 操作（migrate, serialize, flush）全部跑在主库上，表被 DROP + CREATE。

### 对照组证据

| 后端 | swap 后 `current_database()` | 表 OID | 数据 |
|------|---------------------------|--------|------|
| `django.db.backends.postgresql` | `test_cybersparker` ✓ | 不变 | 保留 |
| `dj_db_conn_pool.backends.postgresql` | `cybersparker` ✗ | 改变 | 清空 |

### 为什么选 dj_db_conn_pool

SQLite → PostgreSQL 迁移时直接用了它。项目有大量后台线程直接操作 ORM（不在 Django 请求生命周期），需要后台线程使用 `try...finally: connection.close()` 归还连接，dj_db_conn_pool 的 SQLAlchemy QueuePool 刚好满足这个模式。

详见 `plans/2026-05-15-db-connection-pool-fix.md`。

## 修复：SafeTestRunner

测试期间临时切回 Django 原生 PostgreSQL 后端，避开连接池。

### 文件

- `app_cybersparker/test_runner.py` — SafeTestRunner 实现
- `cybersparker/settings.py` — `TEST_RUNNER = "app_cybersparker.test_runner.SafeTestRunner"`

### 原理

1. 测试前：`ENGINE` 换成 `django.db.backends.postgresql`，销毁连接池，关闭旧连接
2. Django test runner 用原生后端跑完整测试周期（create_test_db → migrate → test → destroy_test_db）
3. 测试后：`ENGINE` 恢复为 `dj_db_conn_pool.backends.postgresql`

对调用方完全透明，不需要额外参数或环境变量。

### 验证

- 插入 3 条 EXP + 3 条 Task 记录
- 跑 `python manage.py test app_cybersparker.tests --noinput`（132 tests）
- 数据保留，表 OID 不变 ✓

## 替代方案（未采用）

换回 Django 原生 `django.db.backends.postgresql` + `CONN_MAX_AGE`：
- 优点：彻底消除第三方依赖，test runner 100% 兼容
- 缺点：无连接数硬上限（需依赖 `MAX_EXPLOIT_THREAD_NUM` 间接控制），无 pre_ping
- 评估：长期来看更健康，但需要改 celery 连接预算计算等代码

## 相关漏洞

nuclei 运行时引擎 5 个修复（同日）：
- `_safe_eval_expression` AST 沙箱加固
- `_read_payload_file_lines` 路径遍历防护
- `_match_regex` 支持 `{{}}` 模板表达式
- `_match_binary` 无效 hex 日志告警
- `_extract_regex` group 索引可读性提升
