# PG 迁移：SQLite → PostgreSQL

## 问题
SQLite 单 writer 限制导致 `auto_exp_task` 多线程并发写时频繁 `database is locked`，
`threading.Lock` + `timeout=30` 仅是排队等待，未解决吞吐瓶颈。

## 方案
迁移到 PostgreSQL 192.168.1.11:5432，利用行级锁 + MVCC 实现真正并发写。

## 变更范围

| 文件 | 操作 |
|------|------|
| `requirements.txt` | 新增 `psycopg2-binary` |
| `cybersparker/settings.py` | DATABASES 改为 PostgreSQL 引擎，密码硬编码 + 环境变量覆盖 |
| `app_cybersparker/apps.py` | 移除 `_configure_sqlite_connection`（PG 不需要 WAL/同步 PRAGMA） |
| `app_cybersparker/views/expload/task_manage/auto_exp_task.py` | 删除无效 `import sqlite3` 检查 |
| `app_cybersparker/views/expload/task_manage/batch_task_executor.py` | 同上 |
| `app_cybersparker/views/expload/task_manage/single_task_executor.py` | 同上 |
| `app_cybersparker/views/expload/fingerprint.py` | 删除未使用的 `import sqlite3` 和注释掉的连接代码 |
| `docker-compose.yml` | 移除 SQLite 文件挂载 `db/db_cybersparker.db` |

## 不做
- 不迁移现有 SQLite 数据（新建空白 PostgreSQL 库）

## 数据迁移（2026-05-15 补充）

用户反馈历史数据不可见。使用 Python 脚本直接从 SQLite 读取并写入 PostgreSQL：

| 表 | 迁移行数 |
|---|---|
| app_cybersparker_fingerprint | 5897 |
| app_cybersparker_exp | 78 |
| app_cybersparker_cyberspaceenginesetting | 2 |
| app_cybersparker_auto_scan_tasks | 5 |
| app_cybersparker_exptask | 6 |
| app_cybersparker_batch_exptask | 16 |
| app_cybersparker_cveextensions | 116 |
| app_cybersparker_exp_relate_fingerprint | 31 |
| app_cybersparker_exptask_result | 25580 |
| app_cybersparker_auto_scan_exp_result | 5 |
| app_cybersparker_auto_scan_indentify_result | 817 |
| **合计** | **32553** |

遇到的问题及处理：
- SQLite VARCHAR 长度不强制 → `EXPTask_result.result` 和 `auto_scan_exp_result.result` 改为 `TextField`
- SQLite boolean 存为 0/1 → 脚本中自动转换为 Python bool
- FK 依赖 → 按 parent-first 顺序迁移，保留原始 ID 值
- 不添加数据库连接池（Django 默认连接池已够用）

## 风险
- 中：PostgreSQL 服务器 `192.168.1.11` 是外部依赖，不可用时服务无法启动
- 低：requirements.txt 新增依赖

## 验证
- [x] `python manage.py check` — 0 issues
- [x] `python manage.py migrate` — 22/22 migrations OK
- [x] `python manage.py check --deploy` — 6 pre-existing warnings (DEBUG=True etc.)
- [x] `python manage.py test` — 15/15 tests passed
- [x] PostgreSQL 21 张表全部创建成功

## 结果
迁移成功。数据库从 SQLite (`db/exp.db`) 切换至 PostgreSQL (`192.168.1.11:5432/cybersparker`)。
