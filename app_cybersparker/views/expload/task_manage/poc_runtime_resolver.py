import hashlib
import importlib
import importlib.util
import inspect
import os
import sys
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))


def _normalize_poc_path(poc_path):
    raw_path = str(poc_path or "").strip()
    if not raw_path:
        raise ValueError("poc path is empty")

    candidates = [
        raw_path,
        os.path.join(PROJECT_ROOT, raw_path),
        os.path.join(os.getcwd(), raw_path),
    ]
    for candidate in candidates:
        abs_path = os.path.abspath(candidate)
        if os.path.isfile(abs_path):
            return abs_path

    raise FileNotFoundError(f"poc file not found: {raw_path}")


def _load_python_module_from_path(py_abs_path):
    module_key = hashlib.sha256(py_abs_path.encode("utf-8")).hexdigest()[:24]
    module_name = f"exp_runtime_{module_key}"

    if module_name in sys.modules:
        try:
            return importlib.reload(sys.modules[module_name])
        except Exception:
            sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, py_abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from path: {py_abs_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeMethodResult(dict):
    def __bool__(self):
        return bool(self.get("matched"))

def _build_yaml_wrapper(yaml_abs_path):
    """读 YAML 文件，返回带标准方法的 SimpleNamespace，直接调 run_nuclei_template"""

    with open(yaml_abs_path, "rb") as f:
        yaml_bytes = f.read()

    from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

    def _verify(target):
        trace_enabled = isinstance(target, dict) and bool(target.get("__debug_trace"))
        trace_lines = []

        def trace_fn(message):
            if not trace_enabled:
                return
            line = f"[nuclei-debug-trace] {message}"
            trace_lines.append(line)
            print(line)

        target_url = str(target.get("target", "") if isinstance(target, dict) else target or "").strip()
        trace_fn(f"进入 YAML _verify, target={target_url!r}")
        if not target_url:
            return RuntimeMethodResult({"target": target_url, "matched": False, "result": "", "trace": trace_lines})
        try:
            result = run_nuclei_template(yaml_bytes, target_url, trace_fn=trace_fn if trace_enabled else None)
        except Exception as exc:
            trace_fn(f"模板执行抛出异常: {exc}")
            return RuntimeMethodResult({"target": target_url, "matched": False, "result": str(exc), "trace": trace_lines})
        if not result:
            trace_fn("模板执行完成，但未命中")
            return RuntimeMethodResult({"target": target_url, "matched": False, "result": "", "trace": trace_lines})
        if isinstance(result, bool):
            trace_fn(f"模板执行完成，布尔结果={bool(result)}")
            return RuntimeMethodResult({"target": target_url, "matched": bool(result), "result": "matched" if result else "", "trace": trace_lines})
        trace_fn("模板执行完成，已命中并返回结构化结果")
        return RuntimeMethodResult({"target": target_url, "matched": True, "result": str(result), "trace": trace_lines})

    def _unsupported(target, cmd=""):
        _ = cmd  # 保持签名兼容，yaml 插件不支持非 verify 模式
        t = str(target.get("target", "") if isinstance(target, dict) else target or "").strip()
        return RuntimeMethodResult({"target": t, "matched": False, "result": "yaml plugin only supports verify mode"})

    return SimpleNamespace(
        _verify=_verify,
        _cmd_exc=_unsupported,
        _code_exc=_unsupported,
        _file_read=_unsupported,
        _attack=_unsupported,
        _attact=_unsupported,
        _attract=_unsupported,
    )


def load_runtime_module_from_poc(poc_path, exp_id=None):
    _ = exp_id  # 保留签名兼容，yaml 路径不再需要编译缓存
    poc_abs_path = _normalize_poc_path(poc_path)
    suffix = os.path.splitext(poc_abs_path)[1].lower()

    if suffix == ".py":
        return _load_python_module_from_path(poc_abs_path)
    elif suffix in (".yaml", ".yml"):
        return _build_yaml_wrapper(poc_abs_path)
    else:
        raise ValueError(f"unsupported poc type: {suffix}")


def _invoke_runtime_method(method, target, cmd=""):
    try:
        param_len = len(inspect.signature(method).parameters)
    except Exception:
        param_len = None

    if param_len is not None and param_len <= 1:
        return method(target)

    try:
        return method(target, cmd)
    except TypeError:
        return method(target)


def call_runtime_method(exp_module, model, target, cmd=""):
    if not isinstance(target, dict):
        raise TypeError(
            f"call_runtime_method: target must be dict, got {type(target).__name__}. "
            "Pass {'target': url} instead of a plain string."
        )
    if "target" not in target:
        raise ValueError("call_runtime_method: target dict missing 'target' key")

    model_key = str(model or "").strip().lower()
    method_map = {
        "1": ["_verify"],
        "verify": ["_verify"],
        "2": ["_cmd_exc"],
        "command": ["_cmd_exc"],
        "3": ["_code_exc"],
        "code_execute": ["_code_exc"],
        "code": ["_code_exc"],
        "4": ["_file_read"],
        "file_reading": ["_file_read"],
        "file": ["_file_read"],
        "5": ["_attact", "_attack", "_attract"],
        "attact": ["_attact", "_attack", "_attract"],
        "attack": ["_attact", "_attack", "_attract"],
    }

    candidate_methods = method_map.get(model_key)
    if not candidate_methods:
        raise ValueError(f"unsupported model: {model}")

    for method_name in candidate_methods:
        method = getattr(exp_module, method_name, None)
        if callable(method):
            return _invoke_runtime_method(method, target, cmd)

    raise AttributeError(f"method not found for model {model}: {candidate_methods}")


def resolve_exp_by_name(plugin_name):
    """以插件名字符串查找 EXP 记录。返回 EXP 对象或 None。

    若调用方有插件 ID，优先用 ID 直接查，不要经过此函数。
    此函数仅用于只有名字字符串的历史数据桥接场景。
    """
    from app_cybersparker import models as _models

    name = plugin_name.strip()
    if not name:
        return None

    obj = _models.EXP.objects.filter(title=name).first()
    if obj:
        return obj

    if name.startswith("[") and "]" in name:
        name = name.split("]", 1)[1].strip()
        return _models.EXP.objects.filter(title=name).first()

    return None
