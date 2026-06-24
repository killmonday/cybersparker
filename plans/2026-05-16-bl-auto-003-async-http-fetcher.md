# BL-AUTO-003 自动识别 Web 请求 async 化

## 做什么
- 将 `app_cybersparker/views/expload/task_manage/auto_exp_task.py` 中的阻塞式 `requests.get()` 请求链替换为 `aiohttp` async fetcher。
- 保持 `header` / `content` / `title` / `status_code` / `error` 字段兼容，并显式关闭系统代理继承（`trust_env=False`）。
- 在每次 HTTP 请求前申请 `http_inflight` resource lease，请求完成后释放。
- 以 bounded queue + 背压承接响应到现有指纹识别消费链，避免网络层无限制放大。
- 补充自动化测试、更新 backlog / 控制台 / 模块文档 / CHANGELOG。

## 为什么
- `BL-AUTO-002` 已完成 Celery 迁入口，当前瓶颈转为 `request_scan()` 的线程阻塞式请求模型。
- 阶段二目标要求把高并发 HTTP in-flight 与 OS 线程解耦，同时保证结果字段与 stop bridge 兼容。
- `BL-SCHED-005` 已提供全局 lease，可直接把 `http_inflight` 纳入运行时预算。

## 怎么做
1. 在自动识别执行器中引入 `aiohttp.ClientSession`、async request scheduler 和 bounded response queue。
2. 将 `request_consumer` 改为单线程 event loop 驱动，按并发窗口拉取 `queue_input` 并调度 `request_scan` 协程。
3. 每个请求协程在发起前申请 `http_inflight` lease，资源不足时等待重试；完成后无论成功失败都释放。
4. producer 保持现有输入节流；当下游响应/指纹队列满时，async scheduler 暂停继续拉取新 URL，形成背压。
5. 补测试覆盖：trust_env=False、lease 申请释放、响应字段兼容、bounded queue 背压、线程数不随并发线性增长（以 request consumer 线程数收敛为证据）。
6. 完成后同步 backlog、项目控制台、模块文档和 CHANGELOG，并执行指定验证命令。

## 风险
- `aiohttp` 与 `requests` 在异常类型、文本解码与 header 表现上有差异，必须用兼容封装收口。
- 当前类内仍存在指纹/漏洞消费线程；若并发参数直接映射到这些线程，可能抵消 async 请求层收益。
- 背压必须避免卡死 `queue_input.task_done()` / `join()` 流程。

## 当前状态
- [已完成] 读取项目控制台、BL-AUTO-003 backlog、相关模块文档与总体计划。
- [已完成] 对 `request_scan` / `request_consumer` / `producer` 做 GitNexus upstream impact，均为 LOW 风险；`request_scan` 仅被 `request_consumer` 直接调用。
- [已完成] 将 `request_scan()` 改为 aiohttp async fetcher，`request_consumer()` 改为单线程 event loop 调度，启用 bounded queue/backpressure。
- [已完成] 接入 `http_inflight` lease、`trust_env=False`、requests 兼容的 header 序列化、connect/read 10s timeout 语义。
- [已完成] 为 `Vulnerability_scanning=1` 补齐后段队列 `join/task_done` 收敛，避免在 `queue_EXP_input` / `queue_EXP_result` 未排空时提前退出。
- [已完成] 增加定向测试覆盖代理禁用、lease 等待恢复、背压、并发窗口与单线程调度。
- [已完成] 最终回归测试通过，并已同步 backlog / 控制台 / 模块文档 / 当前实现总览 / CHANGELOG。

## 验证
- 已通过：`python -m py_compile app_cybersparker/views/expload/task_manage/auto_exp_task.py`
- 已通过：`python -m py_compile app_cybersparker/tests.py`
- 已通过：`DB_HOST=192.168.1.11 python manage.py check`
- 已通过：`DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run`
- 已通过：`DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanAsyncRequestTests`
- 已通过：`DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanCeleryDispatchTests`
- 已通过：`DB_HOST=192.168.1.11 python manage.py test app_cybersparker.tests.AutoScanAsyncRequestTests app_cybersparker.tests.AutoScanCeleryDispatchTests`
- 已通过：`DB_HOST=192.168.1.11 python manage.py test --keepdb app_cybersparker.tests.AutoScanAsyncRequestTests app_cybersparker.tests.AutoScanCeleryDispatchTests`

## 结果
- 自动识别任务请求层已从阻塞式 requests 改为 aiohttp async 调度，网络并发与 OS 线程解耦。
- 输出仍保持 `header/content/html/title/status_code/error` 字段兼容，且未配置代理时不会继承系统环境代理。
- 当指纹队列或漏洞扫描后段队列积压时，上游请求调度会停止拉取新 URL，形成背压并等待下游消费。

## 结果
- 自动识别任务请求层已从阻塞式 requests 改为 aiohttp async 调度，网络并发与 OS 线程解耦。
- 输出仍保持 `header/content/html/title/status_code/error` 字段兼容，且未配置代理时不会继承系统环境代理。
- 当指纹队列或漏洞扫描后段队列积压时，上游请求调度会停止拉取新 URL，形成背压并等待下游消费。

## 收口回合（2026-05-16 会话）

### 静态诊断修复
- **geoip2 possibly unbound**：将模块顶层的 `import geoip2.database` 改为 `from geoip2 import database as geoip2_database` 并初始化 `geoip2_database = None`，`get_ip_from()` 入口处加 `None` 检查。
- **BS title None**：`request_scan()` 中 `BS(content, "lxml").title.text.strip()` 改为先获取 `soup_title = BS(content, "lxml").title`，判 `None` 后再 `.text.strip()`。
- **unresolved imports**：根因为 Pyright 无 venv 路径配置；新增 `pyrightconfig.json`（`venvPath: /opt/venv`），同时关闭 Django `.objects` / Celery `.apply()` / `__traceback__` 等预存动态模式噪声。Pyright CLI 对两文件输出 `0 errors, 0 warnings, 0 informations`。

### 最终验证
| 命令 | 结果 |
|---|---|
| `python -m py_compile auto_exp_task.py` | 通过 |
| `python -m py_compile tests.py` | 通过 |
| `pyright --pythonpath /opt/venv/bin/python auto_exp_task.py tests.py` | 0/0/0 |
| `DB_HOST=192.168.1.11 python manage.py test --keepdb AutoScanAsyncRequestTests AutoScanCeleryDispatchTests` | 10/10 OK |
| `DB_HOST=192.168.1.11 python manage.py check` | 0 issues |
| `DB_HOST=192.168.1.11 python manage.py makemigrations --check --dry-run` | No changes |

## 下一步
- 等待你决定是否继续 BL-AUTO-004；本次按要求在 BL-AUTO-003 完成后停下。 