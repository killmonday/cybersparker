# 2026-05-30 官方 Nuclei OOB 模板兼容修复

## 做什么
- 修复 `nuclei_runtime_engine.py` 对官方 Nuclei OOB/network 模板的兼容问题，不修改官方模板内容。
- 兼容官方模板里的 `interactsh-url` / DNSLog 变量写法，统一映射到现有 ceye 链路。
- 修复 network payload 在官方 `generate_java_gadget(..., 'hex') + concat(end)` 场景下未按二进制发送的问题。
- 补充回归测试，覆盖官方模板风格 OOB/network 执行链路。

## 为什么
- 当前官方模板 `EXP_plugin/CVE-2017-5645_2a704bc9.yaml` 在专用 docker 靶场上 TCP 可连通，但最终未命中。
- 根因不在模板或靶场，而在本项目运行时兼容层：
  1. 只注入了 `interactsh_url`，未兼容官方常见的 `interactsh-url`。
  2. 官方模板生成的是 hex 主体再拼 `\r\n`，当前 network 发送逻辑未做保守的自动字节化。
  3. 我们原先手写的 `_build_urldns()` 造出的 Java 序列化对象结构与实际可打通靶场的 `ysoserial URLDNS` 样本不一致，导致 payload 虽然发送成功，但目标不会发出 DNS 请求。

## 怎么做
1. 在 `_build_dynamic_values()` 中补充 OOB 专用别名：`interactsh-url`、`ceye-url`。
2. 在 network 发送前增加一个小的 payload bytes helper：
   - 显式 `type: hex` 时继续按 hex 发送。
   - 未声明 `type: hex` 但原始表达式明确包含 `generate_java_gadget(..., 'hex')` 这类 binary helper 时，自动把 hex 主体解成 bytes，并保留尾随 `\r\n` 等文本后缀。
3. 发送方式改为 `sendall`，并在自动解码失败时补 trace，避免静默吞错。
4. 把 `generate_java_gadget('dns', ...)` 内部的 URLDNS 构造改为“复用脚本内置的匿名成功样本字节 + 定点替换 host/full URL/长度字段”，不再继续使用手写的 URLDNS 序列化结构，也不再依赖本地外部文件。
5. 在 `app_cybersparker/tests.py` 的 `NucleiRuntimeRequestChainTests` 中补 5 条回归：
   - `_build_dynamic_values()` 真实别名测试
   - 官方模板风格 payload 字节化测试
   - 真实官方模板 OOB 命中测试
   - 普通 hex-like 文本不误判保护测试
   - `_build_urldns()` 对成功样本 URL 生成完全一致字节的测试
6. 更新 `CHANGELOG.md`，如有必要补一句模块文档说明“官方 interactsh/DNSLog 变量统一走 ceye，URLDNS 复用成功样本 patch”。

## 风险
- 自动字节化若过宽，可能把普通文本误判成二进制；因此必须限制在显式 `type: hex` 或明确 binary helper 场景。
- 变量别名不能全量扩散，只补 OOB 相关 key。

## 验证
- 跑现有 OOB 回归测试。
- 跑新增的 4 条兼容测试。
- 用官方模板 `EXP_plugin/CVE-2017-5645_2a704bc9.yaml` 对 `192.168.1.166:4712` 做手工调试，确认出现 payload 发送、ceye 查询、OOB 注入并最终命中。

## 结果
- 已完成：运行时已兼容官方 OOB 变量别名 `interactsh-url` / `ceye-url`，统一映射到现有 ceye 链路。
- 已完成：network payload 新增保守字节化逻辑，官方 `generate_java_gadget(..., 'hex') + \r\n` 场景会按二进制发送并保留尾随换行。
- 已完成：`_build_urldns()` 改为复用脚本内置的匿名成功样本字节，对 host/full URL 及其长度字段做定点 patch；同 URL 时生成字节与内置样本完全一致，换短域名时也能正确生成新 payload，同时不会泄漏真实 ceye 域名。
- 已补 5 条回归测试，覆盖变量别名、官方 payload 二进制发送、真实官方模板经 ceye 命中、普通 hex-like 文本不误判、URLDNS 成功样本复用。
- 已验证通过：`NucleiRuntimeRequestChainTests` 13 条测试 + `python manage.py check` + `python -m py_compile app_cybersparker/views/expload/task_manage/nuclei_runtime_engine.py`。

## 文档
- 若最终只是运行时内部兼容增强，可最小更新模块文档一句行为口径；无需新增独立设计文档。
