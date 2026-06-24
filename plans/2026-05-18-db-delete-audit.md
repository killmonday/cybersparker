# 核心业务表删除审计

- 日期：2026-05-18
- 状态：进行中

## 做什么

为 PostgreSQL 核心业务表加临时 DELETE / TRUNCATE 审计，定位重启 Django/Celery 后业务数据被清空的真实触发源。

## 为什么

- 当前现象是：重启后 `fingerPrint`、`EXP`、`auto_scan_tasks`、`auto_scan_indentify_result`、`auto_scan_exp_result` 都会变成 0。
- 数据库统计显示这些表发生过真实删除，不像是切到了新空库，也不像只是未提交事务。
- 需要先抓到“谁在删、什么时候删、删了哪些表”，再做根因修复。

## 审计范围

- `app_cybersparker_fingerprint`
- `app_cybersparker_exp`
- `app_cybersparker_auto_scan_tasks`
- `app_cybersparker_auto_scan_indentify_result`
- `app_cybersparker_auto_scan_exp_result`

## 审计内容

- 行级 DELETE：记录表名、删除时间、事务 ID、backend pid、db user、application_name、整行 JSON。
- 语句级 TRUNCATE：记录表名、删除时间、事务 ID、backend pid、db user、application_name、操作类型。

## 不做

- 不改业务删除逻辑。
- 不自动恢复数据。
- 不对所有表开启全量审计，只盯核心业务表。

## 验证计划

1. 安装审计表、函数、触发器。
2. 验证触发器已绑定到目标表。
3. 提供复现后的查询方式，让用户下次重启后立即定位删除来源。

## 结果

- 待补充。
