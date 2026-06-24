# 从 exp.db 恢复指纹数据

- 日期：2026-05-17
- 状态：已完成

## 做什么

从旧 SQLite 库 `/workspaces/cybersparker/db/exp.db` 读取指纹表 `app_cybersparker_fingerprint`，只导入当前数据库的 `fingerPrint` 表；同时清理项目根目录下误存在的 0 字节假库文件 `db\exp.db`。

## 为什么

- 用户反馈数据库被清空，但只需要先恢复指纹规则。
- 旧库仍保留完整指纹表，可直接恢复，不必动其他业务表。
- `db\exp.db` 是 0 字节无效文件，容易误导后续排查。

## 不做

- 不导入任务、结果、插件、用户等其他表。
- 不修改指纹模型结构。
- 不补迁移，不改业务代码。

## 结果

- 旧库文件：`/workspaces/cybersparker/db/exp.db`
- 源表：`app_cybersparker_fingerprint`
- 源数据量：5897
- 当前库导入后 `fingerPrint` 数量：5897
- 抽样校验通过：`qnap`、`MiniCMS`、`骑士人才系统(74cms)` 等记录已恢复
- 0 字节假库文件 `db\exp.db` 已删除

## 验证

- 读取 SQLite 表结构与行数：确认旧库指纹表存在且为 5897 条
- Django ORM 计数：`fingerPrint.objects.count()` = 5897
- 抽样读取前 5 条数据：内容与旧库一致

## 说明

- 导入过程中出现 `create_time` naive datetime warning，仅影响时区提示，不影响指纹规则内容导入。
- 本次是数据恢复，不是代码/功能变更，因此未更新 `CHANGELOG.md`。
