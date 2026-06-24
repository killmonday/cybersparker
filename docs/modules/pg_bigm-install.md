# pg_bigm 安装配置

## 概述

pg_bigm 是 PostgreSQL 扩展，提供 2-gram（bigram）全文搜索。用于加速中文/日文/韩文（CJK）文本的 `LIKE` 子串搜索。

项目当前使用三种 HTML 搜索索引：

| 索引 | 类型 | 用途 |
|------|------|------|
| `idx_html_upper_trgm` | GIN trigram | 英文 `ILIKE` 子串搜索 |
| `idx_html_upper_bigm` | GIN bigram | 中文 `ILIKE` 子串搜索 |
| `idx_html_tsvector` | GIN tsvector | ASCII 分词全文搜索 |

## 安装（Debian/Ubuntu）

### 1. 装编译依赖

```bash
apt-get install -y gcc make git postgresql-server-dev-17
```

### 2. 编译 pg_bigm

```bash
git clone https://github.com/pgbigm/pg_bigm.git
cd pg_bigm
USE_PGXS=1 make
USE_PGXS=1 make install
```

### 3. 创建扩展

```sql
CREATE EXTENSION IF NOT EXISTS pg_bigm;
```

### 4. 建索引

```sql
CREATE INDEX IF NOT EXISTS idx_html_upper_bigm
  ON app_cybersparker_auto_scan_indentify_result
  USING GIN (UPPER(html) gin_bigm_ops);
```

或者直接运行 Django 迁移：

```bash
python manage.py migrate app_cybersparker 0036_pg_bigm_tsvector_indexes
```

## 本地开发环境

本开发环境使用 Debian apt 安装的 PostgreSQL 17，端口 5433。pg_bigm 由 `deploy/setup-env.sh` 自动编译安装。

手动安装步骤见上面"安装（Debian/Ubuntu）"章节，按顺序执行即可。

启动本地 PG：

```bash
pg_ctlcluster 17 main start
```

连接本地库（settings.py 默认已指向 localhost:5433）：

```bash
python manage.py runserver
```

如使用非默认端口或远程 DB，通过环境变量覆盖：

```bash
DB_HOST=your-host DB_PORT=5433 DB_PASSWORD=<密码> python manage.py runserver
```

## 注意

- pg_bigm 必须在 PostgreSQL 服务器上编译安装，不是客户端
- `settings.py` 中 `DATABASES` 默认 `HOST=localhost, PORT=5433`，部署时通过 `DB_HOST`/`DB_PORT`/`DB_PASSWORD` 环境变量覆盖
