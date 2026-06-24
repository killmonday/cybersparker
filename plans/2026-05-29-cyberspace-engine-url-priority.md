# 2026-05-29 空间测绘引擎目标提取 URL 优先

## 做什么
- 统一 fofa / zoomeye / quake / hunter / shodan 的目标提取顺序。
- 规则改为：URL > 域名/主机名+端口 > IP+端口。
- 保留任务 61 的拉取调试日志，方便确认 Quake 返回与本地去重差异。
- 补回归测试，覆盖各引擎的优先级行为。

## 为什么
任务 61 的 Quake 查询在官网可见 70 多条站点结果，但本地只落成 21 条。排查发现不是 Quake 少返回，而是适配器只保留 `ip:port`，把多个不同域名站点错误合并成同一目标。

## 怎么做
1. 在 `cyberspace_engine_adapters.py` 新增通用目标选择辅助函数。
2. 让各引擎优先使用原始 URL 字段；没有 URL 时优先域名/主机名；最后才退回 IP。
3. 保留 Quake 的分页、原始数量、去重数量日志。
4. 在 `tests.py` 增加各引擎 URL/域名优先回归测试。

## 风险
- 不同引擎返回字段名不统一，必须容忍字段缺失。
- URL 带路径时会直接进入目标文件，后续执行器要按现有逻辑兼容。
- 目标数量可能明显上升，这是预期变化，不应被误判为重复拉取。

## 验证
- `python manage.py test app_cybersparker.tests.CyberspaceEngineAdapterTargetPriorityTests --keepdb -v 2`
- 重新跑 input_type=4 的 Quake 任务，对比日志中的 `raw_count / added / duplicates / total`。

## 结果
- 已完成：各引擎目标提取统一改为 URL > 域名/主机名+端口 > IP+端口。
- 已完成：保留 Quake 拉取链路详细日志，能直接看出 Quake 返回条数与本地去重后的差异。
- 已完成：补测试覆盖 Fofa / ZoomEye / Quake / Hunter / Shodan 的优先级行为。
- 预期效果：像任务 61 这种同 IP/端口下挂多个域名站点的查询，不会再被粗暴压成 21 条 `ip:port` 目标。
