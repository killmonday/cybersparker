# YAML 运行时去中间文件重构（2026-05-25）

## 做什么

去掉 nuclei YAML 模板的执行中间层（`__yaml_runtime__/*.py` 编译缓存），改为直接从 YAML 文件调用 `run_nuclei_template()`。

## 为什么

当前链路：`YAML 文件` → `compile_yaml_to_project_poc()` 生成 `.py` → `_load_python_module_from_path()` 加载 `.py` → `call_runtime_method()` 调 `_verify()`

生成的 `.py` 是纯机械代码——把 YAML 内容 hex 编码后硬编码，包一层 `_verify()` 转发到 `run_nuclei_template()`。用户不会编辑它，改 YAML 才是改逻辑。

多余的开销：
- 每个 YAML 模板多一个 `.py` 缓存文件
- YAML 更新后缓存失效问题
- 批量导入 1.3 万模板时多写 1.3 万个 `.py`

## 怎么做

### 核心改动：`poc_runtime_resolver.py`

**删掉：** `compile_yaml_to_project_poc()`、`_build_yaml_runtime_source()`、`CONVERTER_VERSION`、`YAML_RUNTIME_ROOT`

**新增：** `_build_yaml_wrapper(yaml_abs_path)` — 读 YAML 内容，返回一个带标准方法的简单对象：

```python
from types import SimpleNamespace

def _build_yaml_wrapper(yaml_abs_path):
    with open(yaml_abs_path, "rb") as f:
        yaml_bytes = f.read()

    def _verify(target):
        target_url = str(target.get("target", "") if isinstance(target, dict) else target or "").strip()
        if not target_url:
            return {}
        try:
            result = run_nuclei_template(yaml_bytes, target_url)
        except Exception as exc:
            return {"target": target_url, "result": str(exc)}
        if not result:
            return {}
        if isinstance(result, bool):
            return {"target": target_url, "result": "matched"}
        return {"target": target_url, "result": str(result)}

    def _unsupported(target, cmd=""):
        t = str(target.get("target", "") if isinstance(target, dict) else target or "").strip()
        return {"target": t, "result": "yaml plugin only supports verify mode"}

    return SimpleNamespace(
        _verify=_verify,
        _cmd_exc=_unsupported,
        _code_exc=_unsupported,
        _file_read=_unsupported,
        _attack=_unsupported,
        _attact=_unsupported,
        _attract=_unsupported,
    )
```

**修改：** `load_runtime_module_from_poc()` — YAML 分支直接调 `_build_yaml_wrapper()` 而非 `compile_yaml_to_project_poc() + _load_python_module_from_path()`：

```python
def load_runtime_module_from_poc(poc_path, exp_id=None):
    poc_abs_path = _normalize_poc_path(poc_path)
    suffix = os.path.splitext(poc_abs_path)[1].lower()
    if suffix == ".py":
        return _load_python_module_from_path(poc_abs_path)
    elif suffix in (".yaml", ".yml"):
        return _build_yaml_wrapper(poc_abs_path)
    else:
        raise ValueError(f"unsupported poc type: {suffix}")
```

注意：函数签名保留 `exp_id` 参数（兼容现有调用方），但不使用。

### 清理

- 删除 `EXP_plugin/__yaml_runtime__/` 整个目录（14 个 `.py` + 1 个 lock 文件）
- 清理 `poc_runtime_resolver.py` 中不再使用的 import：`binascii`（hex 编解码）、`tempfile`、`fcntl`（文件锁）
- `hashlib` 保留（`_load_python_module_from_path` 仍用）

### 调用方：零改动

8 个调用点全部保持不变：

| 调用方 | 文件 |
|--------|------|
| 调试页 | `exp_debug.py:157-158` |
| 结果复验 | `result__manage/expResult.py:160-161` |
| 自动扫描 | `auto_exp_task.py:1114-1115` |
| 批量任务 | `batch_exp_task.py:968-969` |
| 单任务 | `exp_task.py:223-224` |
| 跨平台批量 | `batch_task_executor.py:140,156,509,511` |
| 跨平台 Web | `single_task_executor.py:194-198` |
| 测试 | `tests.py:1608-1609` |

都只是 `load_runtime_module_from_poc(...)` + `call_runtime_method(...)` 两个调用，内部实现变了但返回对象的鸭子类型兼容。

### `call_runtime_method()`：不动

`call_runtime_method(exp_module, model, target, cmd)` 通过 `getattr(exp_module, method_name, None)` 查找方法，对 Python 模块和 SimpleNamespace 都适用。

## 验证方式

1. Django 系统检查：`python manage.py check` 0 issues
2. 调试页手动跑一个 YAML 模板（`exp_debug.py` 路径），确认返回结果
3. 跑 `app_cybersparker/tests.py` 中跟 YAML/auto_exp 相关的测试
4. Pyright：`poc_runtime_resolver.py` 无新增类型错误
5. 全局检索确认没有残留的 `compile_yaml_to_project_poc` 或 `__yaml_runtime__` 引用

## 风险

| 风险 | 等级 | 说明 |
|------|------|------|
| 调用方隐式依赖 `.py` 模块属性 | 低 | 调用方只用 `call_runtime_method()` 返回的 dict，不访问模块内部变量 |
| 现有 `__yaml_runtime__/*.py` 被其他工具引用 | 极低 | `rg` 全局检索确认无外部引用 |
| 性能回退 | 无 | 原来是读 `.py` → importlib 加载 → hex 解码 → 执行；现在是读 YAML → 执行，更少步骤 |

## 不做

- 不修改 `.py` 插件的执行路径
- 不改 `call_runtime_method()` 的接口
- 不删 `_load_python_module_from_path()`（`.py` 插件仍需要）
- 不在此重构中处理批量导入逻辑

## 结果

- 已完成：
  - `poc_runtime_resolver.py` 重构：删除 `compile_yaml_to_project_poc()`、`_build_yaml_runtime_source()`、`YAML_RUNTIME_ROOT`、`CONVERTER_VERSION`、`binascii`/`tempfile`/`fcntl` 导入（净减 ~50 行）。
  - 新增 `_build_yaml_wrapper(yaml_abs_path)`：直接读 YAML 文件，返回 `SimpleNamespace` 包装对象（含 `_verify`/`_cmd_exc`/`_code_exc`/`_file_read`/`_attack`/`_attact`/`_attract`）。
  - `load_runtime_module_from_poc()` YAML 分支改为调 `_build_yaml_wrapper()`，`.py` 分支不变。
  - 8 个调用方零改动（SimpleNamespace 鸭子类型兼容）。
  - 删除 `EXP_plugin/__yaml_runtime__/` 目录（14 个缓存 `.py` + lock 文件）。
  - Django 系统检查通过（0 issues）。
  - Smoke 验证：加载现有 YAML → 所有方法可调用 → `call_runtime_method` verify 正常执行 HTTP 请求 → 非 verify 模式返回 unsupported。
  - CHANGELOG 已同步。批量导入方案已同步。
