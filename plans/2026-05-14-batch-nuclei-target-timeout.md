# 2026-05-14 批量 Nuclei YAML 协程耗时排查

## 问题

批量任务在协程模式运行 Nuclei YAML 时，5000 个目标、1000 协程、单请求默认超时 10s、sleep=0 的整体运行时间超过 5 分钟，不符合预期。

## D-lite 例外说明

本次是通过 `/project-control-plane` 进入的小范围行为排查/修复：预计只调整批量任务执行器或 Nuclei YAML runtime 的局部逻辑和测试，不变更数据库 schema、公开 API、认证安全策略或跨模块契约；按 Mode D-lite 执行。

## 目标

- 保持默认 10s 为单个请求超时，不改为整个 YAML 总超时。
- 确认多请求 YAML 模板中，某个请求超时/异常后是否仍继续执行后续请求；如会继续，改为该目标链路失败后停止后续请求。
- 排查 gevent SSL patch：既规避 `ssl.SSLContext.minimum_version` 递归，又不让 HTTPS 请求在协程模式退化为阻塞式并发。

## 影响面

- GitNexus `Task_handler` upstream：LOW，直接调用者 `batch_exp_task.startTask` 和遗留副本。
- GitNexus `_execute_http_request` upstream：LOW，直接调用者 `run_nuclei_template`。
- GitNexus `run_nuclei_template` upstream：MEDIUM，影响 YAML runtime 生成的 `_verify`。

## 当前假设

- Nuclei 模板的多个 path/raw 请求本身是串行链路；如果前一个请求连接/读取超时，继续执行后续请求会把单请求超时叠加成多倍耗时。
- `gevent.monkey.patch_all(ssl=False)` 避免了 SSL 递归，但也可能让 HTTPS socket/SSL 握手不再通过 gevent 协作式调度。

## 最小方案

1. 保持默认 `timeout=10` 为单个 HTTP 请求超时，不引入目标级/YAML 级总超时。
2. `_execute_http_request()` 中 `session.request()` 发生 `requests.exceptions.RequestException` 后立即返回当前目标失败，不再执行同一目标后续 path/raw。
3. 普通 HTTP 响应未命中 matcher 时保持原有语义，仍可继续后续 path/raw。
4. 新增 `gevent_batch_runner.py` 作为协程子进程轻量入口：先 `monkey.patch_all(thread=False, subprocess=False)`，再导入 Django/requests/执行器。
5. `batch_exp_task.startTask()` 的 spawn target 指向轻量 runner，避免子进程反序列化 target 时先导入 `batch_task_executor.py` 导致 SSL patch 过晚。

## 风险

- SSL patch 修复依赖协程子进程入口保持轻量，后续不要在 `gevent_batch_runner.py` 顶层导入 Django、requests、执行器或其他会导入 `ssl` 的模块。
- 多请求异常短路只针对请求异常；HTTP 404/500 这类普通响应仍按 matcher 语义继续后续请求。

## 验证记录

- `python manage.py test app_cybersparker.tests.RequestRuntimePatchTests app_cybersparker.tests.NucleiRuntimeRequestChainTests app_cybersparker.tests.BatchTaskGeventRunnerTests`：通过，12 tests OK。
- `python manage.py test app_cybersparker`：通过，13 tests OK。
- `python manage.py check`：通过，System check identified no issues。

## 结果

- 复现并修复：第一个 path 超时后仍继续第二个 path 的问题。
- 修复 gevent SSL patch 顺序：协程子进程先完成 gevent socket/SSL patch，再导入 requests/urllib3/执行器。
- 保留项目请求运行时的禁用证书校验配置；gevent SSL patch 只负责协作式 SSL socket/wrap 行为。
- simplify 审查反馈已处理：补充普通非匹配响应继续后续 path 的测试；进度节流增加 `last_progress_process`，避免相同进度文本按时间窗口重复写库。
