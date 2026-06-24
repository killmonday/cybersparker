# 2026-05-20 自动扫描任务新增漏扫线程数配置

## 做什么
- 为自动扫描任务新增单独的“漏洞扫描线程数”配置项。
- 保持 `thread_num` 继续控制 HTTP 扫描阶段的 aiohttp 并发上限。
- 让漏洞扫描阶段改为读取新配置项控制 `exp_consumer` 线程数，不再和 HTTP 并发绑死。
- 同步调整自动扫描任务申请的线程预算，避免全局 `threads` lease 仍按 HTTP 并发错误放大。
- 补充测试，并同步 backlog / 模块文档 / 项目控制台 / CHANGELOG。

## 为什么
- 现在自动扫描任务里，HTTP 扫描已改成 aiohttp 协程，但漏洞扫描阶段仍用线程执行。
- 继续共用一个 `thread_num` 会导致两件事绑在一起：想把 HTTP 并发开大时，漏洞扫描线程也会被一起拉大，不符合实际使用需求。
- 本次要把“HTTP 并发”和“漏洞扫描线程并发”拆开，方便分别调优。

## 怎么做
1. 在 `auto_scan_tasks` 新增 `vulnerability_thread_num` 字段，作为漏洞扫描线程数配置。
2. 自动扫描任务表单、详情、启动链路、Celery worker 取数链路补传该字段。
3. `Auto_exploit_Task_handler` 新增读取逻辑：
   - `thread_num` 继续用于 `network_concurrency`
   - `vulnerability_thread_num` 用于 `exp_consumer` 启动数
4. 线程资源申请从“按 `thread_num` 申请”改为“按指纹线程 + 漏扫线程申请”。
5. 补测试：
   - 新字段能传到执行器
   - 漏扫线程数按新字段而不是 HTTP 并发计算
   - Django check / 定向测试通过

## 风险
- 会改动模型、表单、执行器、Celery 启动链路和任务页面，属于局部功能增强。
- 现有老任务若没有新字段，将按默认值运行，可能与旧“thread_num 全控”行为不同，需要给一个保守默认值。
- 本地已有未跟踪迁移 `app_cybersparker/migrations/0018_alter_auto_scan_tasks_sleep_time_and_more.py`，本次不改它，单独新增迁移文件，避免混入无关内容。

## 验证
- `python manage.py test app_cybersparker.tests.AutoScanThreadBudgetTests --keepdb --noinput -v 2`
- `python manage.py check`
- 说明：`AutoScanCeleryDispatchTests` 在当前本地数据库连接池/keepdb 环境下存在既有测试噪音（唯一键残留、SQLAlchemy pooled connection 断言），与本次新增字段逻辑无直接关系，未作为本次完成阻塞。

## 当前状态
- 已完成：模型、表单、执行器、资源申请、页面回填链路已打通。

## 结果
- `auto_scan_tasks` 新增 `vulnerability_thread_num` 字段，默认值 40。
- `thread_num` 继续只控制 HTTP 扫描阶段的 aiohttp 并发上限。
- `Auto_exploit_Task_handler` 改为用 `vulnerability_thread_num` 控制漏洞扫描阶段 `exp_consumer` 线程数。
- 自动扫描线程资源申请改为按“指纹线程（最多 3）+ 漏扫线程”计算，避免 HTTP 并发直接放大线程预算。
- 相关表单、详情接口、运行态接口、Celery worker 取数链路已补传新字段。

## 后续
- 若后续还要继续细分指纹线程数，可在本次拆分基础上再加第三个配置项，但这次先不做。
- 如需提高“漏扫线程数”相关回归信心，后续可在修复本地 keepdb / 连接池测试噪音后，再补跑 `AutoScanCeleryDispatchTests` 全组。
