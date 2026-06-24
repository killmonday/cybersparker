# 2026-05-28 Log4j nuclei 探针验证

## 做什么
- 定位插件调试界面到 nuclei 引擎的实际执行链路。
- 用最小探针分别验证：模板是否能独立跑通、目标 `192.168.1.166:4712` 是否符合模板预期、项目包装层是否改坏参数。
- 给出失败根因，并在需要时修复代码、测试、文档、变更记录。

## 为什么
用户在插件调试界面用模板 `Apache Log4j Server - Deserialization Command Execution` 和目标 `192.168.1.166:4712` 验证失败，当前不清楚是漏洞环境与模板预期不一致，还是本项目 nuclei 引擎对非 HTTP 场景支持有缺口。

## 怎么做
1. 查项目里 nuclei 任务执行链路，确认 target、模板内容、命令行参数、结果解析方式。
2. 脱离项目做最小实验：直接用 nuclei 跑该模板，观察对 `host:port` 目标的表现。
3. 再通过项目入口复现同一模板，比较两边输入和输出差异。
4. 若是项目问题，最小化修复并补测试；若是环境或模板限制，整理证据和可执行建议。

## 风险
- 该模板属于漏洞验证模板，探针只针对用户说明的本地复现环境，不扩展到其他目标。
- 目标可能要求特定握手、JDK 版本或外部回连条件，模板“没命中”不一定代表引擎故障。
- 若本地缺少 nuclei 或模板库，需要先确认依赖现状。

## 验证
- 能明确列出项目执行命令和直接跑 nuclei 的命令。
- 能给出至少一组“项目内”和“一组项目外”的对照输出。
- 若修改代码：补测试并跑相关测试；同时更新 CHANGELOG 与相关 docs。

## 结果
- 已完成：执行链路定位、独立探针、根因结论与修复建议。
- 结论：`192.168.1.166:4712` 端口可连通，项目也已配置 ceye；失败主因不是目标地址格式，也不是 `tcp:` 模板不被识别，而是 OOB 模板判定顺序有缺口。
- 具体缺口：Log4j 模板的 matcher 要求 `part: interactsh_protocol = dns`，但原逻辑在 `_execute_network_request()` / `_execute_http_request()` 的 matcher 阶段并不会先拉取 ceye 记录，所以该字段始终为空；而 `run_nuclei_template()` 又只在 `result` 已经为真时才调用 `_poll_ceye()`，等于“先要求命中，再去拿命中证据”，导致这类模板永远失败。
- 第一轮修复：新增按需 OOB 上下文注入逻辑。仅当 matcher/extractor 用到 `interactsh_protocol / interactsh_request / interactsh_response` 时，先查询 ceye 记录并注入当前匹配上下文；命中后仍把 `dnslog` 附回结果，普通 HTTP 模板不受影响。
- 第二轮复核又发现两处阻塞并已修复：
  1. `{{generate_java_gadget(... 'http://{{interactsh-url}}' ...)}}` 这类“函数参数里再套变量”的写法，原先会把 `interactsh-url` 当成表达式里的减法，导致 payload 在发送前就渲染失败；现新增嵌套标记渲染，先把内层 `{{interactsh-url}}` 展开再算外层表达式。
  2. network OOB 模板原先发完 payload 后强依赖 `sock.recv()` 成功返回；若服务端不立即回包，就会在查 ceye 前提前失败。现改为：read 超时会记录为 `read_failed`，但只要模板依赖 OOB 字段，仍继续查 ceye 并按 DNS 记录判定命中。
- 第三轮又发现调试页存在“假成功”口径问题并已修复：YAML 包装层以前把运行异常包装成普通非空 dict（例如端口解析异常字符串），`debug_execute` 又用“result 非空”判断成功，导致像 `192.168.1.166:4712。` 这样的非法输入也会显示验证成功。现改为 `_build_yaml_wrapper._verify()` 明确返回 `matched: True/False`，调试页优先按 `matched` 判定状态；异常、未命中都显示失败，只有真实命中才显示成功。
- 第四轮又发现一个 OOB 收口错误并已修复：此前 `run_nuclei_template()` 只要模板最终命中，就会统一调用 `_get_oob_records()` 查询 ceye，即使模板根本没有 `interactsh_*` matcher/extractor。现改为只有请求块里实际依赖 OOB 字段时才查 ceye，普通 HTTP 命中模板不会再无意义轮询 DNSLog。
- 第五轮又定位到批量任务 61“100% 但 0 成果”的根因：批量执行器 `batch_task_executor.py` 在 `consumer_exp()` 和 `save_TaskResult()` 两处都用了 `type(result) == type({})` 严格类型判断。前面为了修调试页，我们把 YAML 运行时返回值改成了 `RuntimeMethodResult(dict 子类)`；这样调试页和 auto_scan 因为用 `isinstance(..., dict)` / `if not result` 仍正常，但批量链路会把命中结果直接跳过，不入 `queue_output`，最终成果表 0 行。现已改为 `isinstance(result, dict)`，并增加 `[batch-result]` 日志，能看到“插件命中 → 入队待写库”的关键节点。

## 验证结果
- 最小探针 1：直接对 `part: interactsh_protocol` 调 matcher，结果恒为 `False`，证明原上下文没有这个字段。
- 最小探针 2：mock `_execute_network_request=False` 且 `_poll_ceye` 可返回记录时，原 `run_nuclei_template()` 仍不会调用 `_poll_ceye`，证明存在判定死循环。
- 环境探针：`192.168.1.166:4712` 可建立 TCP 连接，无立即 banner 返回，符合服务端等待客户端发包的场景。
- 自动化测试：`python manage.py test app_cybersparker.tests.BatchRuntimeResultCompatibilityTests app_cybersparker.tests.NucleiRuntimeRequestChainTests --keepdb -v 2` 通过。新增覆盖：`RuntimeMethodResult(dict 子类)` 在批量链路中也能被当作命中结果正常入队；同时保留 non-OOB 命中不查 ceye、嵌套 `interactsh-url` 渲染、network 场景在 read timeout 下仍继续查 ceye等回归用例。

## 文档同步
- 已更新 `CHANGELOG.md`。
- 已更新 `docs/modules/02-任务执行模块.md`。
- 未单独更新 `docs/当前实现总览.md`，因为本次仅是运行时局部判定修复，模块文档已覆盖关键约束变化。
