# Python PoC 插件 target 从字符串改为字典

- 状态：待审查（v3）
- 日期：2026-06-16

## 做什么

Python PoC 插件的 target 参数从字符串改为字典。所有 Python 插件方法（`_verify`、`_cmd_exc`、`_code_exc`、`_attact`）的 target 参数都从 `"http://example.com"` 字符串改为 `{"target": "http://example.com", ...}` 字典。`cmd` 参数保持不变。

## 为什么

1. **传参能力受限**：当前插件只能拿到 URL 字符串，无法获知代理设置、超时配置、任务上下文等信息。
2. **无法传递函数引用**：如果想让插件调用系统内置方法（如统一日志、统一发送请求），字符串接口做不到。
3. **Python 和 YAML 接口统一**：YAML 路径的 `_verify(target)` 已经接受 `{"target": url, ...}` 格式的 dict，改 Python 后两端统一。

## Dict key 选择

**用 `"target"` 而非 `"url"`**。理由：

- YAML wrapper（`_build_yaml_wrapper`）已经通过 `target.get("target", "")` 读取此 key
- `auto_exp_task.py`、`dirscan_worker.py`、`batch_task_executor.py` 的 consumer 同时处理 Python 和 YAML 插件，key 统一避免静默失败
- `exp_debug.py` 调试页 YAML 分支已构建 `{"target": target, "__debug_trace": True, ...}`

```python
# 传给插件的 target 字典（v1 最小字段）
target = {
    "target": "http://example.com:8080",   # 原 URL 字符串（必填）
}
# 后续扩展预留: "proxy", "timeout", "task_id", "log", "send_request"
```

## 改动范围

| 层 | 文件 | 说明 |
|----|------|------|
| 核心路由 | `poc_runtime_resolver.py` | `call_runtime_method` 加类型校验，拒绝字符串 |
| 调用点 | `batch_task_executor.py` | `consumer_exp()` 两处 `line` → `{"target": line}` |
| 调用点 | `auto_exp_task.py` | `consumer_EXP()` 一处 `url` → `{"target": url}` |
| 调用点 | `exp_debug.py` | `api_exp_execute()` + `debug_execute()`，Python 路构造 `{"target": target}`，YAML 路保持 `{"target": target, "__debug_trace": True, ...}` |
| 调用点 | `batch_exp_task.py` | `TaskResult_verify()` 一处 |
| 调用点 | `dirscan_worker.py` | consumer 漏洞验证阶段一处 |
| 调用点 | `expResult.py` | 结果页手动复验一处 |
| 插件 | `EXP_plugin/*.py`（16 个，排除零参数测试文件） | 所有入口方法签名不动，函数体内 `target` 取值改为 `target["target"]`，`cmd` 参数不动 |

## 怎么改

### 步骤 1 — 改核心路由 `poc_runtime_resolver.py`

`call_runtime_method` 加类型校验，`_invoke_runtime_method` 不变：

```python
def call_runtime_method(exp_module, model, target, cmd=""):
    # 类型校验
    if not isinstance(target, dict):
        raise TypeError(
            f"call_runtime_method: target must be dict, got {type(target).__name__}. "
            "Pass {'target': url} instead of a plain string."
        )
    if "target" not in target:
        raise ValueError("call_runtime_method: target dict missing 'target' key")

    # ... 后续逻辑不变 ...
```

### 步骤 2 — 改 7 个调用点（含遗漏的 2 个）

每个调用点把字符串包装为 `{"target": 字符串}`：

**`batch_task_executor.py` — `consumer_exp()`：**
```python
# 改前: call_runtime_method(exp_module, "verify", line)
# 改后: call_runtime_method(exp_module, "verify", {"target": line})

# 改前: call_runtime_method(exp_module, "attact", line, cmd=self.cmd_input)
# 改后: call_runtime_method(exp_module, "attact", {"target": line}, cmd=self.cmd_input)
```

**`auto_exp_task.py` — `consumer_EXP()`：**
```python
# 改前: call_runtime_method(exp, "verify", url)
# 改后: call_runtime_method(exp, "verify", {"target": url})
```

**`exp_debug.py` — `api_exp_execute()` 和 `debug_execute()`：**
```python
# 改前:
# runtime_target = target  # 字符串
# if yaml: runtime_target = {"target": target, "__debug_trace": True, ...}
#
# 改后 (此模式同时用于 api_exp_execute 和 debug_execute 两个函数):
if str(exp_dict.get("poc", "")).lower().endswith((".yaml", ".yml")):
    runtime_target = {"target": target, "__debug_trace": True, "__debug_plugin_id": exp_dict["id"]}
else:
    runtime_target = {"target": target}
```
注意：前端用户输入的 URL 字符串存为 `target` 变量，调用 `call_runtime_method` 时构造为 `{"target": target}` 传入。

**`batch_exp_task.py` — `TaskResult_verify()`：**
```python
# 改前: call_runtime_method(exp, model, target, cmd)
# 改后: call_runtime_method(exp, model, {"target": target}, cmd)
```

**`dirscan_worker.py` — consumer 漏洞验证阶段：**
```python
# 改前: call_runtime_method(exp_module, "verify", target)
# 改后: call_runtime_method(exp_module, "verify", {"target": target})
```
（注：此处 `target` 变量名和 dict key 同名，注意区分。改前变量叫 `target`，dict key 也是 `"target"`，写成 `{"target": target}`。后续可考虑改名避免混淆，但非必须。）

**`expResult.py` — 结果页手动复验：**
```python
# 改前: call_runtime_method(exp, model, target, cmd)
# 改后: call_runtime_method(exp, model, {"target": target}, cmd)
```

### 步骤 3 — 改 16 个老插件

**核心规则（三条）：**

**规则 1**：每个入口函数（`_verify`/`_cmd_exc`/`_code_exc`/`_attact`）第一行提取 URL：
```python
def _verify(target):
    url = target["target"]
    # 后续所有代码用 url 变量，不再直接操作 target 参数
```

**规则 2**：内部 helper 函数保持字符串参数，不传 dict：
```python
def _check_jolokia(url, username=None, password=None):  # ← 仍用字符串
    endpoint = f"{url.rstrip('/')}/api/jolokia/"
```

**规则 3**：return 语句 target 字段写回字符串（URL），不写回 dict：
```python
return {'target': url, 'result': evidence}   # url 是字符串
# 不是 {'target': target}                    # target 是 dict，会污染下游
```

**参数名变体（3 个插件）**

以下 3 个插件的入口函数参数名是 `url` 而非 `target`，改动方式不同：

```python
# 参数名是 url 的插件：提取到新变量 target_url
def _verify(url):
    target_url = url["target"]   # 注意：左边是 dict key，右边是参数名
    # 后续代码用 target_url 替代原来的 url
```

| 文件 | 签名 | 处理 |
|------|------|------|
| `XCVE-2016-54-Wordpress_Twentyfourteen_Theme.py` | `_verify(url)`, `_cmd_exc(url,cmd)`, `_attact(url,cmd)` | `url["target"]` |
| `[CVE-2025-022101]test_fx8s2d3p.py` | `_verify(url)` | `url["target"]` |
| `[QVE-2026-1111]test11_a21ff8e5.py` | `_verify(url)` | `url["target"]` |

**为什么必须用规则 1+2 而非每个 helper 都收 dict**：以 `24dbe39d...py` 为例，内部调用链 `_verify → _try_default_creds → _check_jolokia`，三个函数都直接对 target 做 `.rstrip('/')`。如果逐个改 helper 签名，改动量大且容易漏。统一在入口提取 `url = target["target"]`，内部函数保持字符串参数，改动最小、最安全。

**三个代码模式（含 cmd 参数处理）：**

```python
# 模式 A：_verify(target) — 单参数
# 改前:
def _verify(target):
    url = target.rstrip('/') + '/path'
    resp = requests.get(target, ...)
    return {'target': target, 'result': ...}
# 改后:
def _verify(target):
    url = target["target"]
    full_url = url.rstrip('/') + '/path'
    resp = requests.get(full_url, ...)
    return {'target': url, 'result': ...}

# 模式 B：_cmd_exc(target, cmd) — 双参数，cmd 不动
# 改前:
def _cmd_exc(target, cmd):
    resp = requests.post(target, data=cmd, ...)
    return {'target': target, 'result': ...}
# 改后:
def _cmd_exc(target, cmd):
    url = target["target"]
    resp = requests.post(url, data=cmd, ...)
    return {'target': url, 'result': ...}

# 模式 C：_attact(target, cmd) — 双参数，cmd 不动
# 同模式 B
```

**插件列表（16 个，全部改。`[QVE-2022-2022]test2222_m703tgu0.py` 因 `_verify()` 零参数且含反向 shell 代码，不做处理）：**

| 文件 | 入口方法 | db 在用 |
|------|---------|---------|
| `0f658a202a...d1d54.py` | `_verify` | — |
| `0f658a202a..._IH9rn1E.py` | `_verify` | 是(id=62920) |
| `24dbe39d...33006.py` | `_verify`, `_cmd_exc` | — |
| `24dbe39d..._BRIXnCh.py` | `_verify`, `_cmd_exc` | 是(id=62918) |
| `67076d3e...ab55.py` | `_code_exc` | — |
| `67076d3e..._l0wOj4g.py` | `_code_exc` | 是(id=62922) |
| `7f74a51a...509e.py` | `_verify` | — |
| `7f74a51a..._8RSKmeG.py` | `_verify` | 是(id=62921) |
| `ae90d6fb...4cf6.py` | `_cmd_exc` | — |
| `ae90d6fb..._DdSYeu5.py` | `_cmd_exc` | 是(id=62923) |
| `e0b6b68d...4ce9.py` | `_verify` | — |
| `e0b6b68d..._JY2qnh9.py` | `_verify` | — |
| 5 个带 `[CVE-*]` `[QVE-*]` 前缀文件 | `_verify` / `_cmd_exc` / `_attact` | 部分 |

### 步骤 4 — 下游消费者确认

以下位置从插件返回值中读取 `target` 字段，插件改完（返回 `'target': url` 字符串）后无需修改：

| 消费者 | 位置 | 读法 | 受影响？ |
|--------|------|------|----------|
| `batch_task_executor.py — save_TaskResult` | 451 | `result["target"]` 传事件 payload | 否（仍是字符串） |
| `batch_task_executor.py — consumer_exp` | 777 | `result.get("target")` | 否 |
| `auto_exp_task.py — _normalize_exp_result` | 1364 | `str(result_info["target"])` | 否（仍是字符串） |
| `dirscan_worker.py — consumer` | 578/583 | `"target": target`（用原始变量） / `dict(result or {})` | 否 |

### 步骤 5 — 验证

- [ ] `python manage.py check` 0 issues
- [ ] `python manage.py test app_cybersparker.tests --parallel` 全部通过
- [ ] 确认 tests.py 中 7 处 `patch("...call_runtime_method")` mock 返回值的 `"target"` 字段均为字符串（非 dict），与插件改动后的 return 格式一致
- [ ] 调试页选一个 Python 插件（如 id=62920 Drupal SQL注入），输入 `http://testphp.vulnweb.com`，执行 verify 确认结果正常
- [ ] 调试页选一个 YAML 插件，执行 verify 确认 target 解析不受影响（`__debug_trace` 仍生效）
- [ ] 批量任务用 1 个 Python 插件 + 1 个 YAML 插件 + 1 个 target，确认两者结果都正常落库

## 风险

| 风险 | 等级 | 处理 |
|------|------|------|
| key 不匹配导致 YAML 静默失败 | 高 | 统一用 `"target"` key |
| dirscan_worker.py / expResult.py 遗漏 | 高 | 已补全 |
| 插件内部 helper 链式崩溃 | 高 | 规则 1：入口提取 url，helper 保持字符串 |
| `result['target']` 返回 dict 污染下游 | 高 | 规则 3：return 写回字符串 url |
| 插件改动遗漏 | 中 | 17 个文件逐文件 diff 确认全部 `target` 引用已改 |
| 3 个插件参数名是 `url` 不是 `target` | 中 | 见步骤 3"参数名变体"，提取方式不同 |
| 测试 mock 返回值格式 | 低 | tests.py 中 7 处 mock 了 `call_runtime_method`（绕过真实调用），mock 的 `"target"` 字段值仍是字符串，不受影响 |
| `__main__` 块手动调用 | 低 | 10 个插件有 `if __name__ == "__main__": _verify('http://...')`，手动调试代码，本次不改，执行时报 TypeError 是预期行为 |
| dirscan_worker.py 变量名 `target` 与 key 同名 | 低 | 写成 `{"target": target}`，语义正确 |
| 测试覆盖不足 | 中 | 新增混合任务手动验证步骤 |

## 不做

- 不修改 YAML template 文件（YAML 插件）
- 不在本次增加 `proxy`/`timeout`/函数引用等扩展字段（接口就位，字段后续加）
- 不删除 `EXP_plugin/` 下的残留文件
- 不清理 `dirscan_worker.py` 和 `expResult.py` 中可能存在的死导入
- 不修改 `[QVE-2022-2022]test2222_m703tgu0.py`（`_verify()` 零参数，模块顶层含反向 shell 代码，功能不可用）

## 验证清单

- [ ] `python manage.py check` 0 issues
- [ ] `python manage.py test app_cybersparker.tests --parallel` 全部通过
- [ ] 确认 tests.py 中 7 处 `patch("...call_runtime_method")` mock 返回值的 `"target"` 字段均为字符串
- [ ] 调试页选 Python 插件，verify 执行，结果正常
- [ ] 调试页选 YAML 插件，verify 执行，`__debug_trace` 生效
- [ ] 调试页选 Python 插件，cmd_exc 执行，cmd 参数正常传递
- [ ] 批量任务 1 Python + 1 YAML + 1 target，结果落库正确
