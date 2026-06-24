import ast
import base64
import binascii
import gzip as gzip_module
import hashlib
import json
import logging
import os
import random
import re
import socket
import ssl
import string
import struct
import time
from collections import OrderedDict
from datetime import datetime as datetime_class
from django.utils import timezone
from itertools import product
import traceback
from typing import Any
from urllib.parse import urlparse, quote, unquote

import requests
import yaml
from django.db import connection as dj_db_connection

logger = logging.getLogger(__name__)


def _emit_trace(trace_fn, message, **payload):
    if not trace_fn:
        return
    if payload:
        details = ", ".join(f"{key}={payload[key]!r}" for key in sorted(payload))
        text = f"{message} | {details}"
    else:
        text = message
    try:
        trace_fn(text)
    except Exception:
        pass


class UnresolvedVariableError(Exception):
    pass


def _to_text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("latin-1", errors="ignore")
    return str(value)


def _contains(inp, substring):
    return _to_text(substring) in _to_text(inp)


def _contains_all(inp, *substrings):
    text = _to_text(inp)
    return all(_to_text(s) in text for s in substrings)


def _contains_any(inp, *substrings):
    text = _to_text(inp)
    return any(_to_text(s) in text for s in substrings)


def _starts_with(inp, prefix):
    return _to_text(inp).startswith(_to_text(prefix))


def _ends_with(inp, suffix):
    return _to_text(inp).endswith(_to_text(suffix))


def _line_starts_with(inp, prefix):
    p = _to_text(prefix)
    return any(line.startswith(p) for line in _to_text(inp).splitlines())


def _line_ends_with(inp, suffix):
    s = _to_text(suffix)
    return any(line.endswith(s) for line in _to_text(inp).splitlines())


def _safe_re_search(pattern, text):
    """Python 3.11 不允许 (?i)/(?m)/(?s) 在表达式中间（Go 的 regexp 允许）。
    遇到时用 (?flags:...) 局部组包裹受影响部分，保留原始语义。"""
    try:
        return re.search(pattern, text)
    except re.error as e:
        if "global flags not at the start" not in str(e):
            raise
        # 从后往前替换，每次用 (?flags:...) 包裹标志之后的部分
        clean = pattern
        for flag_char in ["i", "m", "s"]:
            flag_tag = f"(?{flag_char})"
            idx = clean.find(flag_tag)
            if idx == -1:
                continue
            after = clean[idx + len(flag_tag):]
            if not after:
                # 标志在末尾，直接去掉即可
                clean = clean[:idx]
            else:
                clean = clean[:idx] + f"(?{flag_char}:{after})"
        return re.search(clean, text)


def _regex(pattern, inp):
    return re.search(pattern, _to_text(inp)) is not None


def _md5(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8")
    return hashlib.md5(data).hexdigest()


def _hex_encode(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8")
    return binascii.hexlify(data).decode("utf-8")


def _hex_decode(inp):
    return binascii.unhexlify(_to_text(inp))


def _base64(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8")
    return base64.b64encode(data).decode("utf-8")


def _base64_decode(inp):
    return base64.b64decode(_to_text(inp))


def _to_lower(inp):
    return _to_text(inp).lower()


def _to_upper(inp):
    return _to_text(inp).upper()


def _concat(*args):
    return "".join(_to_text(a) for a in args)


def _rand_base(length, optional_charset=string.ascii_letters + string.digits):
    try:
        n = int(length)
    except Exception:
        n = 8
    chars = optional_charset or (string.ascii_letters + string.digits)
    return "".join(random.choice(chars) for _ in range(max(0, n)))


def _url_encode(inp):
    return quote(_to_text(inp))


def _url_decode(inp):
    return unquote(_to_text(inp))


def _sha256(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _rand_int(optional_min=0, optional_max=2147483647):
    try:
        lo = int(optional_min)
    except Exception:
        lo = 0
    try:
        hi = int(optional_max)
    except Exception:
        hi = 2147483647
    return random.randint(lo, hi)


def _rand_text_alpha(length, optional_bad_chars=""):
    try:
        n = max(0, int(length))
    except Exception:
        n = 8
    chars = string.ascii_letters
    if optional_bad_chars:
        chars = "".join(c for c in chars if c not in _to_text(optional_bad_chars))
    return "".join(random.choices(chars, k=n)) if chars else ""


def _rand_text_alphanumeric(length, optional_bad_chars=""):
    try:
        n = max(0, int(length))
    except Exception:
        n = 8
    chars = string.ascii_letters + string.digits
    if optional_bad_chars:
        chars = "".join(c for c in chars if c not in _to_text(optional_bad_chars))
    return "".join(random.choices(chars, k=n)) if chars else ""


def _rand_text_numeric(length, optional_bad_numbers=""):
    try:
        n = max(0, int(length))
    except Exception:
        n = 8
    chars = string.digits
    if optional_bad_numbers:
        chars = "".join(c for c in chars if c not in _to_text(optional_bad_numbers))
    return "".join(random.choices(chars, k=n)) if chars else ""


def _replace(inp, old, new):
    return _to_text(inp).replace(_to_text(old), _to_text(new))


def _replace_regex(inp, pattern, replacement):
    return re.sub(_to_text(pattern), _to_text(replacement), _to_text(inp))


def _gzip(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8")
    return gzip_module.compress(data)


def _gzip_decode(inp):
    data = inp if isinstance(inp, bytes) else _to_text(inp).encode("utf-8", errors="ignore")
    return gzip_module.decompress(data)


def _date_time(inp):
    fmt = _to_text(inp) if inp else "%Y-%m-%d"
    return timezone.now().strftime(fmt)


def _unix_time(optional_seconds=0):
    try:
        offset = int(optional_seconds)
    except Exception:
        offset = 0
    return int(time.time()) + offset


def _join(separator, *elements):
    return _to_text(separator).join(_to_text(e) for e in elements)


def _trim(inp, cutset=""):
    if cutset:
        return _to_text(inp).strip(_to_text(cutset))
    return _to_text(inp).strip()


def _generate_java_gadget(gadget, cmd, encoding):
    """
    Generate a Java deserialization gadget payload.
    Currently supports only the 'dns' gadget type (URLDNS).

    The URLDNS gadget uses HashMap + java.net.URL serialized in a way that
    triggers DNS resolution on deserialization, without requiring Java runtime.
    """
    gadget = _to_text(gadget)
    cmd = _to_text(cmd)
    encoding = _to_text(encoding)

    if gadget != "dns":
        raise NotImplementedError(
            f"Java gadget type '{gadget}' is not yet supported. "
            f"Currently only 'dns' is supported."
        )

    payload = _build_urldns(cmd)
    return _encode_java_payload(payload, encoding)


_URLDNS_SAMPLE_HOST = b"flag.example.ceye.io"
_URLDNS_SAMPLE_URL = b"http://flag.example.ceye.io"
_URLDNS_SAMPLE_BYTES = binascii.unhexlify(
    "aced0005737200116a6176612e7574696c2e486173684d61700507dac1c31660d103000246000a6c6f6164466163746f724900097468726573686f6c6478703f4000000000000c770800000010000000017372000c6a6176612e6e65742e55524c962537361afce47203000749000868617368436f6465490004706f72744c0009617574686f726974797400124c6a6176612f6c616e672f537472696e673b4c000466696c6571007e00034c0004686f737471007e00034c000870726f746f636f6c71007e00034c000372656671007e00037870ffffffffffffffff740014666c61672e6578616d706c652e636579652e696f74000071007e000574000468747470707874001b687474703a2f2f666c61672e6578616d706c652e636579652e696f78"
)


def _build_urldns(url):
    """Patch an embedded known-good URLDNS serialized sample with a new DNSLog URL."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"Cannot extract hostname from URL: {url}")
    if (parsed.scheme or "http") != "http":
        raise ValueError(f"URLDNS sample patcher currently only supports http URLs: {url}")
    if parsed.port:
        raise ValueError(f"URLDNS sample patcher currently does not support explicit ports: {url}")
    if parsed.path not in ("", "/"):
        raise ValueError(f"URLDNS sample patcher currently only supports empty path URLs: {url}")

    sample = _URLDNS_SAMPLE_BYTES
    new_host = host.encode("utf-8")
    new_url = url.encode("utf-8")

    host_marker = b"\x74" + struct.pack('>H', len(_URLDNS_SAMPLE_HOST)) + _URLDNS_SAMPLE_HOST
    url_marker = b"\x74" + struct.pack('>H', len(_URLDNS_SAMPLE_URL)) + _URLDNS_SAMPLE_URL
    host_entry = b"\x74" + struct.pack('>H', len(new_host)) + new_host
    url_entry = b"\x74" + struct.pack('>H', len(new_url)) + new_url

    host_marker_pos = sample.find(host_marker)
    if host_marker_pos == -1:
        raise ValueError("Unexpected URLDNS sample: authority host string not found")
    url_marker_pos = sample.find(url_marker, host_marker_pos + len(host_marker))
    if url_marker_pos == -1:
        raise ValueError("Unexpected URLDNS sample: full URL string not found")

    host_value_start = host_marker_pos + 3
    host_value_end = host_value_start + len(_URLDNS_SAMPLE_HOST)
    url_value_start = url_marker_pos + 3
    url_value_end = url_value_start + len(_URLDNS_SAMPLE_URL)

    return b"".join([
        sample[:host_marker_pos],
        host_entry,
        sample[host_value_end:url_marker_pos],
        url_entry,
        sample[url_value_end:],
    ])


def _wr_field(buf, tc, name, classname=None):
    """Write a Java serialization field descriptor."""
    buf.append(ord(tc))
    _wr_utf(buf, name)
    if tc in ('L', '['):
        _wr_string(buf, classname)


def _wr_utf(buf, s):
    """Write modified UTF-8: 2-byte length + UTF-8 data."""
    b = s.encode('utf-8')
    buf.extend(struct.pack('>H', len(b)))
    buf.extend(b)


def _wr_string(buf, s):
    """Write TC_STRING (0x74) + 2-byte length + UTF-8 data."""
    b = s.encode('utf-8')
    buf.append(0x74)
    buf.extend(struct.pack('>H', len(b)))
    buf.extend(b)


def _encode_java_payload(payload, encoding):
    """Encode binary Java serialized payload into the requested format."""
    if encoding == "base64":
        return base64.b64encode(payload).decode('utf-8')
    elif encoding == "hex":
        return binascii.hexlify(payload).decode('utf-8')
    elif encoding in ("raw", "base64-raw"):
        return base64.b64encode(payload).decode('utf-8').rstrip('=')
    else:
        raise ValueError(f"Unsupported encoding for java_gadget: {encoding}")


SAFE_FUNCTIONS = {
    "contains": _contains,
    "contains_all": _contains_all,
    "contains_any": _contains_any,
    "starts_with": _starts_with,
    "ends_with": _ends_with,
    "line_starts_with": _line_starts_with,
    "line_ends_with": _line_ends_with,
    "regex": _regex,
    "md5": _md5,
    "hex_encode": _hex_encode,
    "hex_decode": _hex_decode,
    "base64": _base64,
    "base64_decode": _base64_decode,
    "to_lower": _to_lower,
    "to_upper": _to_upper,
    "concat": _concat,
    "rand_base": _rand_base,
    "url_encode": _url_encode,
    "url_decode": _url_decode,
    "sha256": _sha256,
    "rand_int": _rand_int,
    "rand_text_alpha": _rand_text_alpha,
    "rand_text_alphanumeric": _rand_text_alphanumeric,
    "rand_text_numeric": _rand_text_numeric,
    "replace": _replace,
    "replace_regex": _replace_regex,
    "gzip": _gzip,
    "gzip_decode": _gzip_decode,
    "date_time": _date_time,
    "unix_time": _unix_time,
    "join": _join,
    "trim": _trim,
    "generate_java_gadget": _generate_java_gadget,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "bool": bool,
}


def _validate_ast_safety(tree):
    """拒绝含 dunder 属性访问或 dunder 变量名的表达式，阻断沙箱逃逸。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise ValueError(f"forbidden dunder attribute: {node.attr}")
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise ValueError(f"forbidden dunder name: {node.id}")


def _safe_eval_expression(expression, context):
    expr = str(expression or "").strip()
    if not expr:
        return ""
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!\s*(?=[A-Za-z_\(])", "not ", expr)
    try:
        tree = ast.parse(expr, mode="eval")
        _validate_ast_safety(tree)
    except SyntaxError:
        raise
    except ValueError:
        raise
    safe_globals = {"__builtins__": {}}
    safe_locals = {}
    safe_locals.update(SAFE_FUNCTIONS)
    safe_locals.update(context)
    return eval(expr, safe_globals, safe_locals)


def _is_hex_string(value):
    if not isinstance(value, str):
        return False
    data = value.strip()
    return bool(data) and len(data) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", data) is not None


def _expand_preprocessors(data):
    rand_tokens = set(m[0] for m in re.findall(r"(\{\{randstr(_\w+)?\}\})", data))
    for token in rand_tokens:
        data = data.replace(token, _rand_base(27))
    return data


def _hyphen_to_underscore(value):
    if isinstance(value, list):
        return [_hyphen_to_underscore(item) for item in value]
    if isinstance(value, dict):
        return {str(k).replace("-", "_"): _hyphen_to_underscore(v) for k, v in value.items()}
    return value


def _build_dynamic_values(target):
    url = str(target or "").strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "http://" + url
        parsed = urlparse(url)

    path_parts = parsed.path.split("/") if parsed.path else [""]
    path_parent = "/".join(path_parts[:-1]) if len(path_parts) > 1 else ""
    file_name = path_parts[-1] if path_parts else ""

    host_ip = ""
    try:
        if parsed.hostname:
            host_ip = socket.gethostbyname(parsed.hostname)
    except Exception:
        host_ip = ""

    values = OrderedDict()
    values["BaseURL"] = url
    values["RootURL"] = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url
    values["Hostname"] = parsed.netloc
    values["Scheme"] = parsed.scheme
    values["Host"] = parsed.hostname or ""
    values["Port"] = parsed.port or (443 if parsed.scheme == "https" else 80)
    values["Path"] = path_parent
    values["File"] = file_name
    values["IP"] = host_ip
    for k, v in list(values.items()):
        values[k.lower()] = v

    ceye_url = _get_ceye_url()
    if ceye_url:
        values["ceye_url"] = ceye_url
        values["ceye-url"] = ceye_url
        values["interactsh_url"] = ceye_url
        values["interactsh-url"] = ceye_url

    return values


def _coerce_network_payload_bytes(raw_data, data_value, data_type):
    if isinstance(data_value, bytes):
        return data_value

    text_value = _to_text(data_value)
    normalized_type = str(data_type or "text").lower()
    if normalized_type == "hex":
        return _hex_decode(text_value.strip())

    raw_text = _to_text(raw_data)
    should_auto_decode_hex = (
        normalized_type == "text"
        and "generate_java_gadget" in raw_text
        and ("'hex'" in raw_text or '"hex"' in raw_text)
    )
    if not should_auto_decode_hex:
        return text_value.encode("utf-8")

    hex_end = 0
    for idx, char in enumerate(text_value):
        if char.lower() not in "0123456789abcdef":
            break
        hex_end = idx + 1
    if hex_end and hex_end % 2 == 0:
        hex_part = text_value[:hex_end]
        suffix = text_value[hex_end:]
        if _is_hex_string(hex_part) and not suffix.strip("\r\n\t "):
            return _hex_decode(hex_part) + suffix.encode("utf-8")

    raise ValueError("network payload looked like auto-hex gadget output but could not be decoded")


def _get_ceye_config():
    try:
        from app_cybersparker.models import CeyeConfig
        return CeyeConfig.objects.first()
    except Exception:
        return None
    finally:
        try:
            dj_db_connection.close()
        except Exception:
            pass


def _get_ceye_url():
    config = _get_ceye_config()
    if not config or not config.api_token or not config.identifier:
        return ""
    flag = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"{flag}.{config.identifier}"


def _poll_ceye(ceye_url):
    """ceye_url 格式: {flag}.{identifier}"""
    if not ceye_url or "." not in ceye_url:
        return []
    config = _get_ceye_config()
    if not config or not config.api_token:
        return []
    flag = ceye_url.split(".")[0]
    # 首次查询前等 5 秒，给 DNS 传播留时间
    time.sleep(5)
    records = []
    for _ in range(5):
        try:
            resp = requests.get(
                "http://api.ceye.io/v1/records",
                params={"token": config.api_token, "type": "dns", "filter": flag},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("data", [])
                if records:
                    break
        except Exception:
            pass
        time.sleep(3)
    return records


def _oob_part_names():
    return {"interactsh_protocol", "interactsh_request", "interactsh_response"}


def _needs_oob_context(matchers=None, extractors=None):
    for item in _normalize_to_list(matchers) + _normalize_to_list(extractors):
        part = str((item or {}).get("part") or "").strip().lower()
        if part in _oob_part_names():
            return True
        # 检查 DSL 表达式是否引用了 OOB 变量
        for dsl_expr in _normalize_to_list((item or {}).get("dsl", [])):
            expr_text = str(dsl_expr or "")
            for oob_name in _oob_part_names():
                if oob_name in expr_text:
                    return True
    return False


def _get_oob_records(dynamic_values, trace_fn=None):
    if dynamic_values.get("__oob_checked"):
        records = dynamic_values.get("__oob_records") or []
        _emit_trace(trace_fn, "复用已缓存的 ceye 查询结果", record_count=len(records))
        return records

    dynamic_values["__oob_checked"] = True
    oob_url = dynamic_values.get("ceye_url") or dynamic_values.get("interactsh_url") or ""
    if not oob_url:
        dynamic_values["__oob_records"] = []
        _emit_trace(trace_fn, "当前模板未生成 ceye / interactsh 地址")
        return []

    _emit_trace(trace_fn, "开始查询 ceye DNS 记录", oob_url=oob_url)
    records = _poll_ceye(oob_url) or []
    dynamic_values["__oob_records"] = records
    _emit_trace(trace_fn, "ceye 查询完成", record_count=len(records))
    return records


def _attach_oob_context(data, dynamic_values, matchers=None, extractors=None, trace_fn=None):
    if not _needs_oob_context(matchers, extractors):
        return data

    records = _get_oob_records(dynamic_values, trace_fn=trace_fn)
    if not records:
        _emit_trace(trace_fn, "模板依赖 OOB 字段，但 ceye 暂无记录")
        return data

    enriched = dict(data)
    rendered = "\n".join(str(item) for item in records)
    enriched["interactsh_protocol"] = "dns"
    enriched["interactsh_request"] = rendered
    enriched["interactsh_response"] = rendered
    enriched["dnslog"] = records
    _emit_trace(trace_fn, "已把 ceye 结果注入 matcher 上下文", record_count=len(records))
    return enriched


def _render_text(text, dynamic_values):
    pattern = re.compile(r"\{\{([^{}]+)\}\}|§([^§]+)§")

    def repl(match):
        expr = (match.group(1) or match.group(2) or "").strip()
        if not expr:
            return ""
        if expr in dynamic_values:
            return _to_text(dynamic_values[expr])
        if expr.lower() in dynamic_values:
            return _to_text(dynamic_values[expr.lower()])
        try:
            return _to_text(_safe_eval_expression(expr, dynamic_values))
        except Exception as exc:
            raise UnresolvedVariableError(str(exc))

    return pattern.sub(repl, _to_text(text))


def _render_nested_markers(value, dynamic_values, max_depth=5):
    rendered = _to_text(value)
    for _ in range(max_depth):
        if "{{" not in rendered and "§" not in rendered:
            break
        updated = _render_text(rendered, dynamic_values)
        if updated == rendered:
            break
        rendered = updated
    return rendered


def _marker_replace(value, dynamic_values):
    if isinstance(value, str):
        return _render_text(value, dynamic_values)
    if isinstance(value, list):
        return [_marker_replace(v, dynamic_values) for v in value]
    if isinstance(value, dict):
        return {k: _marker_replace(v, dynamic_values) for k, v in value.items()}
    return value


def _load_template_dict(template):
    raw = template
    if isinstance(template, bytes):
        raw = template.decode("utf-8", errors="ignore")
    if _is_hex_string(str(raw).strip()):
        try:
            raw = binascii.unhexlify(str(raw).strip()).decode("utf-8", errors="ignore")
        except Exception:
            pass
    raw = _expand_preprocessors(_to_text(raw))
    loaded = yaml.safe_load(raw) or {}
    normalized = _hyphen_to_underscore(loaded)
    if not isinstance(normalized, dict):
        return {}
    doc: dict[str, Any] = dict(normalized)
    if "http" in doc and "requests" not in doc:
        doc["requests"] = doc["http"]
    if "tcp" in doc and "network" not in doc:
        doc["network"] = doc["tcp"]
    if isinstance(doc.get("requests"), dict):
        doc["requests"] = [doc["requests"]]
    if isinstance(doc.get("network"), dict):
        doc["network"] = [doc["network"]]
    return doc


def _normalize_to_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


PAYLOAD_SAFE_DIRS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../EXP_plugin")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../EXP_input")),
]


def _is_safe_payload_path(path):
    """只允许读取项目内 EXP_plugin / EXP_input 目录下的 payload 文件。"""
    abs_path = os.path.abspath(path)
    return any(abs_path.startswith(safe_dir + os.sep) for safe_dir in PAYLOAD_SAFE_DIRS)


def _read_payload_file_lines(path):
    if not _is_safe_payload_path(path):
        logger.warning("_read_payload_file_lines: blocked path %r", path)
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fp:
            return [line.strip() for line in fp if line.strip()]
    except Exception:
        return []


def _payload_generator(payloads, attack):
    payloads = payloads or {}
    if not payloads:
        yield {}
        return

    payload_keys = list(payloads.keys())
    payload_values = []
    for key in payload_keys:
        val = payloads.get(key)
        vals = val if isinstance(val, list) else [val]
        expanded = []
        for item in vals:
            if isinstance(item, str) and os.path.isfile(item):
                file_vals = _read_payload_file_lines(item)
                if file_vals:
                    expanded.extend(file_vals)
                else:
                    expanded.append(item)
            else:
                expanded.append(item)
        payload_values.append(expanded)

    attack_type = str(attack or "batteringram").lower()
    if attack_type == "pitchfork":
        for combo in zip(*payload_values):
            yield dict(zip(payload_keys, combo))
        return

    for combo in product(*payload_values):
        yield dict(zip(payload_keys, combo))


def _response_headers_text(headers):
    return "\n".join(f"{k}: {v}" for k, v in (headers or {}).items())


def _http_response_to_map(resp, request_dump=b""):
    if resp is None:
        return {
            "status_code": 0,
            "body": b"",
            "header": "",
            "all_headers": "",
            "request": request_dump,
            "response": b"",
            "kval_extractor_dict": {},
        }

    body = resp.content or b""
    headers_text = _response_headers_text(resp.headers)
    response_blob = headers_text.encode("utf-8", errors="ignore") + b"\n\n" + body

    data = {
        "status_code": resp.status_code,
        "body": body,
        "header": headers_text,
        "all_headers": headers_text,
        "request": request_dump,
        "response": response_blob,
        "kval_extractor_dict": {**dict(resp.cookies), **dict(resp.headers)},
    }

    for k, v in dict(resp.headers).items():
        data[k.lower().replace("-", "_")] = v
    return data


def _get_part_value(part, data, want_bytes=False):
    name = str(part or "").strip() or "body"
    if name == "all":
        name = "body"
    value = data.get(name, b"" if want_bytes else "")
    if want_bytes and not isinstance(value, bytes):
        value = _to_text(value).encode("utf-8", errors="ignore")
    if not want_bytes and isinstance(value, bytes):
        value = _to_text(value)
    return value


def _match_words(matcher, corpus, context):
    words = _normalize_to_list(matcher.get("words"))
    condition = str(matcher.get("condition") or "or").lower()
    case_insensitive = bool(matcher.get("case_insensitive"))
    match_all = bool(matcher.get("match_all"))

    text = _to_text(corpus)
    if case_insensitive:
        text = text.lower()

    hits = []
    for word in words:
        text_word = _to_text(word)
        if "{{" in text_word:
            try:
                candidate = _to_text(_render_text(text_word, context))
            except UnresolvedVariableError:
                candidate = text_word
        else:
            candidate = text_word
        if case_insensitive:
            candidate = candidate.lower()
        ok = candidate in text
        if ok:
            hits.append(candidate)
            if condition == "or" and not match_all:
                return True
        else:
            if condition == "and":
                return False

    return len(hits) > 0 if match_all else (condition == "and" and len(hits) == len(words))


def _match_regex(matcher, corpus, context=None):
    regexes = _normalize_to_list(matcher.get("regex"))
    condition = str(matcher.get("condition") or "or").lower()
    text = _to_text(corpus)

    matched = 0
    for pattern in regexes:
        pattern_str = _to_text(pattern)
        if "{{" in pattern_str:
            try:
                pattern_str = _to_text(_render_text(pattern_str, context or {}))
            except UnresolvedVariableError:
                pass
        ok = _safe_re_search(pattern_str, text) is not None
        if ok:
            matched += 1
            if condition == "or":
                return True
        elif condition == "and":
            return False

    return condition == "and" and matched == len(regexes) and matched > 0


def _match_binary(matcher, corpus):
    binary_patterns = _normalize_to_list(matcher.get("binary"))
    condition = str(matcher.get("condition") or "or").lower()
    data = corpus if isinstance(corpus, bytes) else _to_text(corpus).encode("utf-8", errors="ignore")

    matched = 0
    for pattern in binary_patterns:
        try:
            raw = binascii.unhexlify(_to_text(pattern))
        except Exception:
            logger.warning("_match_binary: invalid hex pattern %r", _to_text(pattern)[:120])
            continue
        ok = raw in data
        if ok:
            matched += 1
            if condition == "or":
                return True
        elif condition == "and":
            return False

    return condition == "and" and matched == len(binary_patterns) and matched > 0


def _match_size(matcher, corpus):
    sizes = [int(x) for x in _normalize_to_list(matcher.get("size")) if str(x).strip()]
    length = len(corpus if isinstance(corpus, (bytes, str)) else _to_text(corpus))
    return length in sizes


def _match_status(matcher, status_code):
    statuses = [int(x) for x in _normalize_to_list(matcher.get("status")) if str(x).strip()]
    return int(status_code or 0) in statuses


def _match_dsl(matcher, context):
    expressions = _normalize_to_list(matcher.get("dsl"))
    condition = str(matcher.get("condition") or "and").lower()

    for expression in expressions:
        try:
            result = bool(_safe_eval_expression(expression, context))
        except Exception:
            result = False

        if not result and condition == "and":
            return False
        if result and condition == "or":
            return True

    return condition == "and"


def _apply_matchers(matchers, condition, data):
    matchers = _normalize_to_list(matchers)
    if not matchers:
        return False

    logical = str(condition or "or").lower()
    matched_any = False

    for matcher in matchers:
        mtype = str(matcher.get("type") or "word").lower()
        part = matcher.get("part", "body")

        if mtype == "status":
            res = _match_status(matcher, data.get("status_code", 0))
        elif mtype == "size":
            res = _match_size(matcher, _get_part_value(part, data))
        elif mtype == "word":
            res = _match_words(matcher, _get_part_value(part, data), data)
        elif mtype == "regex":
            res = _match_regex(matcher, _get_part_value(part, data), data)
        elif mtype == "binary":
            res = _match_binary(matcher, _get_part_value(part, data, want_bytes=True))
        elif mtype == "dsl":
            res = _match_dsl(matcher, data)
        elif mtype == "xpath":
            res = _match_xpath(matcher, _get_part_value(part, data))
        else:
            res = False

        if matcher.get("negative"):
            res = not res

        if res:
            matched_any = True
            if logical == "or":
                return True
        else:
            if logical == "and":
                return False

    return matched_any if logical == "or" else True


def _extract_regex(extractor, corpus):
    results = {"internal": {}, "external": {}, "extra_info": []}
    regexes = _normalize_to_list(extractor.get("regex"))
    name = extractor.get("name")
    group = int(extractor.get("group") or 0)
    internal = bool(extractor.get("internal"))

    for pattern in regexes:
        # print(f'[debug] _extract_regex, pattern: {pattern}, corpus: {corpus}, group: {group}')
        match = _safe_re_search(_to_text(pattern), _to_text(corpus))
        if not match:
            continue
        has_capture_group = match.lastindex is not None and match.lastindex >= group
        value = match.group(group) if has_capture_group else match.group(0)
        # print(f'\n[debug] _extract_regex, name: {name}, value: {value}\n')
        if name:
            if internal:
                results["internal"][name] = value
            else:
                results["external"][name] = value
            return results
        results["extra_info"].append(value)

    return results


def _extract_kval(extractor, kval_dict):
    results = {"internal": {}, "external": {}, "extra_info": []}
    keys = _normalize_to_list(extractor.get("kval"))
    name = extractor.get("name")
    internal = bool(extractor.get("internal"))

    for key in keys:
        k = _to_text(key)
        value = kval_dict.get(k)
        if value is None:
            value = kval_dict.get(k.replace("_", "-"))
        if value is None:
            continue
        if name:
            if internal:
                results["internal"][name] = value
            else:
                results["external"][name] = value
            return results
        results["extra_info"].append(value)

    return results


def _extract_dsl(extractor, context):
    results = {"internal": {}, "external": {}, "extra_info": []}
    expressions = _normalize_to_list(extractor.get("dsl"))
    name = extractor.get("name")
    internal = bool(extractor.get("internal"))

    for expression in expressions:
        try:
            value = _safe_eval_expression(expression, context)
        except Exception:
            continue

        if name:
            if internal:
                results["internal"][name] = value
            else:
                results["external"][name] = value
            return results
        results["extra_info"].append(value)

    return results


def _has_ssl_extractor(extractors):
    for ext in _normalize_to_list(extractors):
        if str(ext.get("type") or "").lower() in ("ssl-cert", "ssl"):
            return True
    return False


def _parse_host_port(url):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _fetch_ssl_cert_data(host, port=443, timeout=3):
    """Fetch TLS certificate fields from a server using stdlib ssl."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        # Must be CERT_REQUIRED or getpeercert() returns empty dict.
        # load_default_certs() loads system trust store; check_hostname=False
        # prevents hostname verification while still populating cert fields.
        ctx.load_default_certs()
        ctx.verify_mode = ssl.CERT_REQUIRED
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                cert_der = ssock.getpeercert(binary_form=True)
                _tls_version = ssock.version() if hasattr(ssock, "version") else ""
                _cipher = ssock.cipher() if hasattr(ssock, "cipher") else None
    except Exception:
        return None

    if not cert:
        return None

    _OID_TO_DN = {
        "countryName": "C",
        "stateOrProvinceName": "ST",
        "localityName": "L",
        "organizationName": "O",
        "organizationalUnitName": "OU",
        "commonName": "CN",
        "emailAddress": "EMAILADDRESS",
    }

    def _to_dn(rdn_list):
        parts = []
        for item in rdn_list or []:
            for key, val in item:
                short = _OID_TO_DN.get(key, key)
                parts.append(f"{short}={val}")
        return ", ".join(parts)

    def _subject_field(field_name):
        for item in cert.get("subject") or []:
            for key, val in item:
                if key.lower().replace(" ", "") == field_name.lower().replace(" ", ""):
                    return val
        return ""

    def _issuer_field(field_name):
        for item in cert.get("issuer") or []:
            for key, val in item:
                if key.lower().replace(" ", "") == field_name.lower().replace(" ", ""):
                    return val
        return ""

    san = []
    for entry in cert.get("subjectAltName") or []:
        if entry[0] == "DNS":
            san.append(entry[1])

    fingerprint_md5 = hashlib.md5(cert_der).hexdigest() if cert_der else ""
    fingerprint_sha1 = hashlib.sha1(cert_der).hexdigest() if cert_der else ""
    fingerprint_sha256 = hashlib.sha256(cert_der).hexdigest() if cert_der else ""
    tls_version = _tls_version
    cipher_name = _cipher[0] if _cipher else ""

    return {
        "tls_version": tls_version,
        "subject_cn": _subject_field("commonName"),
        "subject_dn": _to_dn(cert.get("subject")),
        "subject_org": _subject_field("organizationName"),
        "subject_an": san,
        "issuer_cn": _issuer_field("commonName"),
        "issuer_dn": _to_dn(cert.get("issuer")),
        "issuer_org": _issuer_field("organizationName"),
        "not_before": cert.get("notBefore", ""),
        "not_after": cert.get("notAfter", ""),
        "serial": cert.get("serialNumber", ""),
        "fingerprint_hash": {
            "md5": fingerprint_md5,
            "sha1": fingerprint_sha1,
            "sha256": fingerprint_sha256,
        },
        "cipher": cipher_name,
    }


def _extract_ssl_cert(extractor, ssl_data):
    if not ssl_data:
        return {"internal": {}, "external": {}, "extra_info": []}

    name = extractor.get("name")
    internal = bool(extractor.get("internal"))

    result = {}
    for key, value in ssl_data.items():
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            result[key] = value
        elif isinstance(value, list):
            result[key] = value
        else:
            result[key] = str(value)

    if name:
        if internal:
            return {"internal": {name: result}, "external": {}, "extra_info": []}
        return {"internal": {}, "external": {name: result}, "extra_info": []}
    return {"internal": result, "external": {}, "extra_info": []}


def _apply_extractors(extractors, data):
    merged = {"internal": {}, "external": {}, "extra_info": []}
    for extractor in _normalize_to_list(extractors):
        etype = str(extractor.get("type") or "regex").lower()
        part = extractor.get("part", "body")
        if etype == "regex":
            res = _extract_regex(extractor, _get_part_value(part, data))
        elif etype == "kval":
            res = _extract_kval(extractor, data.get("kval_extractor_dict", {}))
        elif etype == "dsl":
            res = _extract_dsl(extractor, data)
        elif etype == "json":
            res = _extract_json(extractor, _get_part_value(part, data))
        elif etype == "xpath":
            res = _extract_xpath(extractor, _get_part_value(part, data))
        elif etype in ("ssl-cert", "ssl"):
            res = _extract_ssl_cert(extractor, data.get("ssl_data"))
        else:
            res = {"internal": {}, "external": {}, "extra_info": []}

        merged["internal"].update(res["internal"])
        merged["external"].update(res["external"])
        merged["extra_info"] += res["extra_info"]

    return merged


def _json_path_get(data, path):
    """Simplified jq-style path: .key, .key.subkey, [0], .key[0].sub"""
    if not path:
        raise ValueError("empty json path")
    current = data
    tokens = path.lstrip(".").split(".")
    for token in tokens:
        token = token.strip()
        if not token:
            raise ValueError(f"empty token in path: {path!r}")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$", token)
        if match:
            key, idx = match.group(1), int(match.group(2))
            if not isinstance(current, dict) or key not in current:
                raise ValueError(f"key {key!r} not found in json")
            current = current[key]
            if not isinstance(current, list):
                raise ValueError(f"{key!r} is not a list")
            if idx >= len(current):
                raise ValueError(f"index {idx} out of range for {key!r}")
            current = current[idx]
            continue
        match2 = re.match(r"^\[(\d+)\]$", token)
        if match2:
            idx = int(match2.group(1))
            if not isinstance(current, list):
                raise ValueError(f"not a list for index {idx}")
            if idx >= len(current):
                raise ValueError(f"index {idx} out of range")
            current = current[idx]
            continue
        if not isinstance(current, dict):
            raise ValueError(f"not a dict for key {token!r}")
        if token not in current:
            raise ValueError(f"key {token!r} not found in json")
        current = current[token]
    return current


def _extract_json(extractor, corpus):
    results = {"internal": {}, "external": {}, "extra_info": []}
    try:
        parsed = json.loads(corpus)
    except (json.JSONDecodeError, TypeError, ValueError):
        return results
    paths = _normalize_to_list(extractor.get("json") or [])
    name = extractor.get("name")
    internal = bool(extractor.get("internal"))
    for path in paths:
        path_str = _to_text(path)
        try:
            full_path = "." + path_str if not str(path_str).startswith(".") else path_str
            value = _json_path_get(parsed, full_path)
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        text_value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if name:
            if internal:
                results["internal"][name] = text_value
            else:
                results["external"][name] = text_value
            return results
        results["extra_info"].append(str(text_value))
    return results


def _match_xpath(matcher, corpus):
    try:
        from lxml import etree
    except ImportError:
        return False
    xpath_exprs = _normalize_to_list(matcher.get("xpath"))
    if not xpath_exprs:
        return False
    text = _to_text(corpus)
    try:
        if text.strip().startswith("<?xml"):
            doc = etree.XML(text.encode("utf-8", errors="ignore"))
        else:
            doc = etree.HTML(text)
    except Exception:
        return False
    if doc is None:
        return False
    for xpath_expr in xpath_exprs:
        try:
            nodes = doc.xpath(_to_text(xpath_expr))
        except Exception:
            continue
        if nodes:
            return True
    return False


def _extract_xpath(extractor, corpus):
    results = {"internal": {}, "external": {}, "extra_info": []}
    try:
        from lxml import etree
    except ImportError:
        return results
    xpath_exprs = _normalize_to_list(extractor.get("xpath"))
    if not xpath_exprs:
        return results
    name = extractor.get("name")
    internal = bool(extractor.get("internal"))
    attribute = extractor.get("attribute")
    text = _to_text(corpus)
    try:
        if text.strip().startswith("<?xml"):
            doc = etree.XML(text.encode("utf-8", errors="ignore"))
        else:
            doc = etree.HTML(text)
    except Exception:
        return results
    if doc is None:
        return results
    for xpath_expr in xpath_exprs:
        try:
            nodes = doc.xpath(_to_text(xpath_expr))
        except Exception:
            continue
        for node in nodes:
            if attribute:
                val = node.attrib.get(_to_text(attribute), "") if hasattr(node, "attrib") else str(node)
            elif hasattr(node, "text"):
                val = node.text or ""
            else:
                val = str(node)
            if not val:
                continue
            if name:
                if internal:
                    results["internal"][name] = val
                else:
                    results["external"][name] = val
                return results
            results["extra_info"].append(val)
    return results


def _build_http_call_from_path(request_obj, path_item, dynamic_values):
    method = str(request_obj.get("method") or "GET").upper()
    headers = request_obj.get("headers") or {}
    body = request_obj.get("body") or ""
    url = _to_text(path_item)
    if url.startswith("{{") or url.startswith("§"):
        url = _marker_replace(url, dynamic_values)
    elif url.startswith("/"):
        url = _marker_replace("{{BaseURL}}" + url, dynamic_values)
    else:
        url = _marker_replace(url, dynamic_values)

    kwargs = {
        "headers": _marker_replace(headers, dynamic_values),
        "data": _marker_replace(body, dynamic_values),
        "allow_redirects": bool(request_obj.get("redirects")),
        "timeout": 10,
        "verify": False,
    }
    return method, url, kwargs


def _build_http_call_from_raw(request_obj, raw_item, dynamic_values):
    raw_text = _to_text(raw_item).strip("\n")
    lines = raw_text.splitlines()
    timeout = 10

    # 跳过所有 @ 开头的 Nuclei 指令行（@timeout / @Host / @tls-sni / @once / @note 等）
    # 策略：每行按空格分词，跳过所有非 HTTP method 的前缀 token（包括 @ 指令及参数值），
    # 找到第一个合法 HTTP method 即为请求行起始。整行找不到 method → 跳过整行。
    _VALID_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH", "CONNECT", "TRACE"})
    while lines:
        line = lines[0].strip()
        if not line.startswith("@"):
            break
        # 提取 @timeout（如果此行含）
        if line.lower().startswith("@timeout"):
            match = re.search(r"@timeout:?\s*(\d+)s", line, re.IGNORECASE)
            if match:
                timeout = int(match.group(1))
        # 找第一个合法 HTTP method 的位置
        tokens = line.split()
        method_idx = None
        for i, tok in enumerate(tokens):
            if tok.upper() in _VALID_HTTP_METHODS:
                method_idx = i
                break
        if method_idx is not None:
            lines[0] = " ".join(tokens[method_idx:])  # 原地修改，后续正常解析
            break
        lines = lines[1:]                              # 纯指令行，跳过

    if not lines:
        raise ValueError("empty raw request")

    first = lines[0].strip()
    parts = first.split()
    if len(parts) < 2:
        raise ValueError("invalid raw request line")
    method = parts[0].upper()
    path = parts[1]

    split_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "":
            split_index = idx
            break

    header_lines = lines[1:split_index] if split_index is not None else lines[1:]
    body_lines = lines[split_index + 1:] if split_index is not None else []

    headers = {}
    for line in header_lines:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip()] = v.strip()

    body = "\n".join(body_lines)
    url = _marker_replace("{{BaseURL}}" + path, dynamic_values)

    kwargs = {
        "headers": _marker_replace(headers, dynamic_values),
        "data": _marker_replace(body, dynamic_values),
        "allow_redirects": bool(request_obj.get("redirects")),
        "timeout": timeout,
        "verify": False,
    }
    return method, url, kwargs


def _execute_http_request(request_obj, dynamic_values, session=None, trace_fn=None):
    # print('[debug] request_obj:', request_obj)
    results = []
    paths = _normalize_to_list(request_obj.get("path"))
    raws = _normalize_to_list(request_obj.get("raw"))
    request_items = [("path", item) for item in paths] + [("raw", item) for item in raws]
    if not request_items:
        return False

    payloads = request_obj.get("payloads") or {}
    attack = request_obj.get("attack") or "batteringram"
    matchers = request_obj.get("matchers") or []
    extractors = request_obj.get("extractors") or []
    matchers_condition = request_obj.get("matchers_condition") or "or"
    stop_at_first_match = request_obj.get("stop_at_first_match", True)
    req_condition = bool(request_obj.get("req_condition")) or len(request_items) > 1

    own_session = session is None
    if own_session:
        session = requests.Session()
    try:
        for payload in _payload_generator(payloads, attack):
            dynamic_values.update(payload)
            aggregated = {}
            accumulated_extra_info = []
            accumulated_external = {}
            print('[debug] ready to send http request')
            for idx, (kind, item) in enumerate(request_items, start=1):
                try:
                    if kind == "path":
                        method, url, kwargs = _build_http_call_from_path(request_obj, item, dynamic_values)
                    else:
                        method, url, kwargs = _build_http_call_from_raw(request_obj, item, dynamic_values)
                except UnresolvedVariableError:
                    continue

                req_dump = f"{method} {url}".encode("utf-8", errors="ignore")
                start = time.time()
                try:
                    print('[debug] send http request '+ method + ' ' + url)
                    _emit_trace(trace_fn, '即将发送 HTTP 请求', method=method, url=url, timeout=kwargs.get('timeout'), headers=kwargs.get('headers'))
                    resp = session.request(method=method, url=url, **kwargs)
                    duration = time.time() - start
                    body_preview = _to_text(resp.content)[:1024]
                    _emit_trace(trace_fn, '收到 HTTP 响应', status_code=resp.status_code, final_url=resp.url, duration=round(duration, 3), body_preview=body_preview)
                except requests.exceptions.RequestException as exc:
                    _emit_trace(trace_fn, 'HTTP 请求异常', error=str(exc), method=method, url=url)
                    return results if results else False
                except Exception:
                    traceback.print_exc()
                    return results if results else False

                resp_data = _http_response_to_map(resp, req_dump)
                resp_data["duration"] = duration

                extractor_data = {**resp_data, **dynamic_values}
                if _has_ssl_extractor(extractors) and url.lower().startswith("https"):
                    host, port = _parse_host_port(url)
                    if host and port:
                        ssl_data = _fetch_ssl_cert_data(host, port)
                        if ssl_data:
                            extractor_data["ssl_data"] = ssl_data

                extracted = _apply_extractors(extractors, extractor_data)
                dynamic_values.update(extracted["internal"])
                accumulated_external.update(extracted["external"])
                accumulated_extra_info.extend(extracted["extra_info"])

                current_data = {**resp_data, **dynamic_values}
                current_data = _attach_oob_context(current_data, dynamic_values, matchers, extractors, trace_fn=trace_fn)
                if req_condition:
                    aggregated.update(current_data)
                    for k, v in current_data.items():
                        aggregated[f"{k}_{idx}"] = v
                else:
                    if _apply_matchers(matchers, matchers_condition, current_data):
                        output = {}
                        output.update(accumulated_external)
                        output.update(payload)
                        output["extra_info"] = accumulated_extra_info
                        results.append(output)
                        if stop_at_first_match:
                            return results

            if req_condition and aggregated:
                if _apply_matchers(matchers, matchers_condition, aggregated):
                    output = {}
                    output.update(accumulated_external)
                    output.update(payload)
                    output["extra_info"] = accumulated_extra_info
                    results.append(output)
                    if stop_at_first_match:
                        return results
    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                pass

    return results if results else False


def _execute_network_request(request_obj, dynamic_values, trace_fn=None):
    hosts = _normalize_to_list(request_obj.get("host"))
    inputs = _normalize_to_list(request_obj.get("inputs"))
    if not hosts or not inputs:
        return False

    payloads = request_obj.get("payloads") or {}
    attack = request_obj.get("attack") or "batteringram"
    matchers = request_obj.get("matchers") or []
    extractors = request_obj.get("extractors") or []
    matchers_condition = request_obj.get("matchers_condition") or "or"
    read_size = int(request_obj.get("read_size") or 1024)
    read_all = bool(request_obj.get("read_all"))

    for payload in _payload_generator(payloads, attack):
        dynamic_values.update(payload)
        for host_expr in hosts:
            try:
                host_value = _marker_replace(host_expr, dynamic_values)
            except UnresolvedVariableError:
                continue

            use_tls = str(host_value).startswith("tls://")
            target = str(host_value).replace("tls://", "", 1) if use_tls else str(host_value)
            parsed = urlparse(f"//{target}")
            host = parsed.hostname
            port = parsed.port
            if not host or not port:
                continue

            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(8)
                _emit_trace(trace_fn, '即将建立 TCP 连接', host=host, port=int(port), use_tls=use_tls)
                sock.connect((host, int(port)))
                _emit_trace(trace_fn, 'TCP 连接建立成功', host=host, port=int(port))
                if use_tls:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    sock = context.wrap_socket(sock, server_hostname=host)

                req_chunks = []
                resp_chunks = []
                resp_data = {"host": target}

                for inp in inputs:
                    name = inp.get("name")
                    read_before = int(inp.get("read") or 0)
                    if read_before > 0:
                        chunk = sock.recv(read_before)
                        resp_chunks.append(chunk)
                        if name:
                            resp_data[name] = chunk

                    raw_data = inp.get("data", "")
                    if isinstance(raw_data, str):
                        data_value = _render_nested_markers(raw_data, dynamic_values)
                    else:
                        data_value = _marker_replace(raw_data, dynamic_values)
                    data_type = str(inp.get("type") or "text").lower()
                    try:
                        payload_bytes = _coerce_network_payload_bytes(raw_data, data_value, data_type)
                    except Exception as exc:
                        _emit_trace(trace_fn, 'TCP payload 编码失败', error=str(exc), data_type=data_type, preview=_to_text(data_value)[:120])
                        raise

                    sock.sendall(payload_bytes)
                    _emit_trace(trace_fn, '已发送 TCP payload', byte_length=len(payload_bytes), preview=_to_text(payload_bytes[:80]))
                    req_chunks.append(payload_bytes)
                    time.sleep(0.05)

                last_bytes = []
                read_failed = False
                if read_all:
                    while True:
                        try:
                            chunk = sock.recv(1024)
                        except Exception:
                            read_failed = True
                            break
                        if not chunk:
                            break
                        last_bytes.append(chunk)
                else:
                    try:
                        last_bytes.append(sock.recv(read_size))
                    except Exception:
                        read_failed = True

                resp_chunks.extend(last_bytes)
                resp_data["request"] = b"".join(req_chunks)
                resp_data["data"] = b"".join(last_bytes)
                resp_data["raw"] = b"".join(resp_chunks)
                resp_data["kval_extractor_dict"] = {}
                resp_data["read_failed"] = read_failed

                extracted = _apply_extractors(extractors, {**resp_data, **dynamic_values})
                dynamic_values.update(extracted["internal"])

                current_data = {**resp_data, **dynamic_values}
                current_data = _attach_oob_context(current_data, dynamic_values, matchers, extractors, trace_fn=trace_fn)
                if read_failed and not current_data.get("dnslog") and _needs_oob_context(matchers, extractors):
                    _emit_trace(trace_fn, 'HTTP 响应未返回且 OOB 也未命中，本次请求判失败')
                    continue
                matched = _apply_matchers(matchers, matchers_condition, current_data)
                _emit_trace(trace_fn, 'HTTP matcher 判定完成', matched=matched, matchers_condition=matchers_condition)
                if matched:
                    output = {}
                    output.update(extracted["external"])
                    output.update(payload)
                    output["extra_info"] = extracted["extra_info"]
                    return [output]
            except Exception:
                continue
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass

    return False


UNSUPPORTED_NUCLEI_PROTOCOLS = (
    "code",
    "javascript",
    "headless",
    "file",
    "dns",
    "ssl",
    "websocket",
    "whois",
)


def find_unsupported_nuclei_protocols(doc):
    unsupported = []
    for key in UNSUPPORTED_NUCLEI_PROTOCOLS:
        if doc.get(key):
            unsupported.append(key)
    return unsupported

def run_nuclei_template(template, target, trace_fn=None):
    doc = _load_template_dict(template)
    _emit_trace(trace_fn, '已加载 nuclei 模板', template_id=doc.get('id'), top_level_keys=sorted(doc.keys()))
    if not doc.get("requests") and not doc.get("network"):
        unsupported = find_unsupported_nuclei_protocols(doc)
        if unsupported:
            _emit_trace(trace_fn, '模板协议当前不受支持', unsupported=unsupported)
            raise NotImplementedError(f"unsupported nuclei protocol: {', '.join(unsupported)}")
    dynamic_values = _build_dynamic_values(target)
    _emit_trace(trace_fn, '目标已标准化', BaseURL=dynamic_values.get('BaseURL'), Host=dynamic_values.get('Host'), Port=dynamic_values.get('Port'))

    variables = doc.get("variables") or {}
    for key, value in variables.items():
        if isinstance(value, str):
            try:
                dynamic_values[key] = _marker_replace(value, dynamic_values)
            except Exception:
                dynamic_values[key] = value
        else:
            dynamic_values[key] = value

    result = False
    session = requests.Session()
    try:
        flow_str = str(doc.get("flow") or "").strip().lower()
        request_objects = _normalize_to_list(doc.get("requests"))

        if "&&" in flow_str and len(request_objects) > 1:
            # AND 模式 (flow: http(1) && http(2))：执行所有请求，含 matchers 的必须全部通过
            collected = []
            overall = True
            for request_obj in request_objects:
                req_result = _execute_http_request(request_obj or {}, dynamic_values, session=session, trace_fn=trace_fn)
                has_matchers = bool(request_obj.get("matchers"))
                if has_matchers and not req_result:
                    overall = False
                if req_result:
                    collected.extend(req_result if isinstance(req_result, list) else [req_result])
            result = collected if overall else False
        else:
            for request_obj in request_objects:
                result = _execute_http_request(request_obj or {}, dynamic_values, session=session, trace_fn=trace_fn)
                if result:
                    break

        if not result:
            for request_obj in _normalize_to_list(doc.get("network")):
                result = _execute_network_request(request_obj or {}, dynamic_values, trace_fn=trace_fn)
                if result:
                    break
    finally:
        try:
            session.close()
        except Exception:
            pass

    if any(
        _needs_oob_context(request_obj.get("matchers"), request_obj.get("extractors"))
        for request_obj in _normalize_to_list(doc.get("requests")) + _normalize_to_list(doc.get("network"))
    ):
        try:
            # HTTP 请求刚发出时查不到 DNS 结果，需清除缓存强制重新查询
            # network 请求在 _execute_network_request 结束时已查过一次，不清缓存
            if any(
                _needs_oob_context(r.get("matchers"), r.get("extractors"))
                for r in _normalize_to_list(doc.get("requests"))
            ):
                dynamic_values.pop("__oob_checked", None)
                dynamic_values.pop("__oob_records", None)
            dns_records = _get_oob_records(dynamic_values, trace_fn=trace_fn)
            if dns_records:
                if isinstance(result, list):
                    for r in result:
                        if isinstance(r, dict):
                            r["dnslog"] = dns_records
                elif isinstance(result, dict):
                    result["dnslog"] = dns_records
                elif not result:
                    result = {"dnslog": dns_records}
            # 有 OOB 记录但 result 为空时，用 OOB 记录构造结果
            if dns_records and not result:
                result = {"dnslog": dns_records, "matched": True}
        except Exception:
            pass

    _emit_trace(trace_fn, '模板执行结束', matched=bool(result), result_preview=_to_text(result)[:300] if result else '')
    return result
