# 数据库全表禁止 TRUNCATE 保护

- 日期：2026-05-18
- 状态：已完成

## 做什么

在当前 PostgreSQL 业务库的所有 `public` 表上安装 `BEFORE TRUNCATE` 触发器，统一禁止 TRUNCATE，保留 DELETE 可用。

## 为什么

- 已确认业务库多次被外部连接从宿主机发起整库级别 `TRUNCATE`，导致指纹、插件、自动扫描任务和结果表被清空。
- 现阶段首要目标是阻止再次大面积误清库，先保住数据。

## 已执行修复

- PostgreSQL `public` schema 下现有 23 张表全部安装 `block_truncate_<table>` 触发器。
- 新增函数 `public.block_all_truncate()`：任何表收到 TRUNCATE 请求时直接抛错 `TRUNCATE is forbidden on <schema>.<table>`。
- DELETE 不受影响，仍可按业务需要正常使用。

## 验证

- 安装结果：`protected_count = 23 / table_count = 23`。
- `TRUNCATE TABLE public.row_delete_audit_log`：被自定义触发器成功拦截。
- `fingerPrint.objects.filter(id=...).delete()`：DELETE 正常可用。
