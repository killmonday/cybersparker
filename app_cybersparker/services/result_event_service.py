import json
import os
import re
import threading
import time
from collections import defaultdict
from urllib.parse import urlparse

from django.conf import settings
from django.db import DatabaseError, OperationalError, transaction

from app_cybersparker import models

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


STREAM_IDENTIFY = "identify_result"
STREAM_AUTO_EXP = "auto_exp_result"
STREAM_BATCH_EXP = "batch_result"
STREAM_NAMES = (STREAM_IDENTIFY, STREAM_AUTO_EXP, STREAM_BATCH_EXP)
STREAM_KEY_PREFIX = "result-event-stream"
DEFAULT_STREAM_GROUP = "db_writer"
DEFAULT_STREAM_BATCH_SIZE = 100
DEFAULT_PENDING_IDLE_SECONDS = 5
DEFAULT_SPOOL_MAX_BYTES = 1024 * 1024
DEFAULT_SPOOL_ARCHIVE_LIMIT = 20
SPOOL_ACTIVE_FILE = "active.jsonl"
SPOOL_PENDING_PREFIX = "pending-"
SPOOL_ARCHIVE_DIR = "archive"
SPOOL_STATE_FILE = "state.json"

_memory_lock = threading.Lock()
_memory_streams = defaultdict(list)
_memory_pending = defaultdict(dict)
_memory_id = 0

_relation_buffer = []


def _flush_relations():
    if _relation_buffer:
        models.AssetTaskRelation.objects.bulk_create(
            _relation_buffer,
            ignore_conflicts=True,
            batch_size=100,
        )
        _relation_buffer.clear()


def _stream_key(stream_name):
    return f"{STREAM_KEY_PREFIX}:{stream_name}"


def _spool_dir():
    return str(getattr(settings, "RESULT_EVENT_SPOOL_DIR", os.path.join(settings.BASE_DIR, "result_spool")))


def _spool_archive_dir():
    return os.path.join(_spool_dir(), SPOOL_ARCHIVE_DIR)


def _spool_active_path():
    return os.path.join(_spool_dir(), SPOOL_ACTIVE_FILE)


def _spool_state_path():
    return os.path.join(_spool_dir(), SPOOL_STATE_FILE)


def _spool_max_bytes():
    return int(getattr(settings, "RESULT_EVENT_SPOOL_MAX_BYTES", DEFAULT_SPOOL_MAX_BYTES))


def _spool_archive_limit():
    return int(getattr(settings, "RESULT_EVENT_SPOOL_ARCHIVE_LIMIT", DEFAULT_SPOOL_ARCHIVE_LIMIT))


def _ensure_spool_dir():
    os.makedirs(_spool_dir(), exist_ok=True)
    os.makedirs(_spool_archive_dir(), exist_ok=True)


def _get_stream_client():
    if bool(getattr(settings, "RESULT_EVENT_FORCE_SPOOL", False)):
        return None
    if redis is None:
        return None
    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    if not broker_url.startswith("redis://"):
        return None
    try:
        return redis.Redis.from_url(broker_url)
    except Exception:
        return None


def _next_memory_id():
    global _memory_id
    with _memory_lock:
        _memory_id += 1
        return str(_memory_id)


def reset_memory_event_store():
    global _memory_id
    with _memory_lock:
        _memory_streams.clear()
        _memory_pending.clear()
        _memory_id = 0

    spool_dir = _spool_dir()
    if not os.path.isdir(spool_dir):
        return

    for name in os.listdir(spool_dir):
        path = os.path.join(spool_dir, name)
        if os.path.isdir(path):
            for child in os.listdir(path):
                os.remove(os.path.join(path, child))
            os.rmdir(path)
        else:
            os.remove(path)


def _read_spool_state():
    path = _spool_state_path()
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_spool_state(state):
    _ensure_spool_dir()
    with open(_spool_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _list_pending_spool_files():
    _ensure_spool_dir()
    files = []
    for name in sorted(os.listdir(_spool_dir())):
        if name.startswith(SPOOL_PENDING_PREFIX) and name.endswith('.jsonl'):
            files.append(os.path.join(_spool_dir(), name))
    return files


def _rotate_active_spool_if_needed():
    path = _spool_active_path()
    if not os.path.isfile(path):
        return None
    if os.path.getsize(path) < _spool_max_bytes():
        return None
    rotated_name = f"{SPOOL_PENDING_PREFIX}{int(time.time())}.jsonl"
    rotated_path = os.path.join(_spool_dir(), rotated_name)
    os.replace(path, rotated_path)
    return rotated_path


def _archive_spool_file(file_path):
    _ensure_spool_dir()
    archive_path = os.path.join(_spool_archive_dir(), os.path.basename(file_path))
    if os.path.isfile(file_path):
        os.replace(file_path, archive_path)
    archived = sorted(os.listdir(_spool_archive_dir()))
    while len(archived) > _spool_archive_limit():
        oldest = archived.pop(0)
        os.remove(os.path.join(_spool_archive_dir(), oldest))
    return archive_path


def count_spool_lines():
    total = 0
    for path in [_spool_active_path(), *_list_pending_spool_files()]:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            total += sum(1 for _ in f)
    return total


def get_spool_stats():
    _ensure_spool_dir()
    pending_files = _list_pending_spool_files()
    active_path = _spool_active_path()
    max_file_size = 0
    pending_lines = 0
    for path in pending_files + ([active_path] if os.path.isfile(active_path) else []):
        if not os.path.isfile(path):
            continue
        max_file_size = max(max_file_size, os.path.getsize(path))
        with open(path, "r", encoding="utf-8") as f:
            pending_lines += sum(1 for _ in f)
    state = _read_spool_state()
    return {
        "active_file": active_path if os.path.isfile(active_path) else None,
        "pending_file_count": len(pending_files),
        "pending_line_count": pending_lines,
        "max_file_size": max_file_size,
        "replay_failures": state.get("replay_failures", 0),
    }


def append_spool_event(stream_name, payload):
    _ensure_spool_dir()
    _rotate_active_spool_if_needed()
    with open(_spool_active_path(), "a", encoding="utf-8", errors="ignore") as f:
        f.write(json.dumps({"stream": stream_name, "payload": payload}, ensure_ascii=False) + "\n")
    return {"backend": "spool", "stream": stream_name, "path": _spool_active_path()}


def replay_spool_to_stream(limit=None):
    _ensure_spool_dir()
    state = _read_spool_state()
    replayed = 0
    pending_files = _list_pending_spool_files()
    active_path = _spool_active_path()
    if os.path.isfile(active_path) and os.path.getsize(active_path) > 0:
        rotated_path = _rotate_active_spool_if_needed() or active_path
        if rotated_path == active_path:
            temp_name = f"{SPOOL_PENDING_PREFIX}{int(time.time())}.jsonl"
            temp_path = os.path.join(_spool_dir(), temp_name)
            os.replace(active_path, temp_path)
            pending_files.append(temp_path)
    pending_files = _list_pending_spool_files()

    for file_path in pending_files:
        offset = state.get(file_path, 0)
        succeeded = 0
        remaining_failed = False
        with open(file_path, "r", encoding="utf-8") as f:
            for index, line in enumerate(f):
                if index < offset:
                    continue
                if limit is not None and replayed >= limit:
                    remaining_failed = True
                    break
                item = json.loads(line)
                try:
                    publish_result_event(item["stream"], item["payload"], allow_spool_fallback=False)
                    replayed += 1
                    succeeded = index + 1
                    state[file_path] = succeeded
                except Exception:
                    state["replay_failures"] = state.get("replay_failures", 0) + 1
                    remaining_failed = True
                    break
        if not remaining_failed:
            state.pop(file_path, None)
            _archive_spool_file(file_path)
        _write_spool_state(state)
        if limit is not None and replayed >= limit:
            break
    return replayed


def publish_result_event(stream_name, payload, allow_spool_fallback=True):
    client = _get_stream_client()
    if client is None:
        broker_url = getattr(settings, "CELERY_BROKER_URL", "")
        if broker_url.startswith("memory://") and not bool(getattr(settings, "RESULT_EVENT_FORCE_SPOOL", False)):
            with _memory_lock:
                global _memory_id
                _memory_id += 1
                _memory_streams[stream_name].append({
                    "id": str(_memory_id),
                    "payload": payload,
                })
            return {"backend": "memory", "stream": stream_name, "id": str(_memory_id)}
        return append_spool_event(stream_name, payload)

    try:
        result = client.xadd(_stream_key(stream_name), {"event": json.dumps(payload, ensure_ascii=False)})
        return {"backend": "redis", "stream": stream_name, "id": result.decode() if isinstance(result, bytes) else result}
    except Exception:
        if allow_spool_fallback:
            return append_spool_event(stream_name, payload)
        raise


def publish_result_events(stream_name, payloads):
    results = []
    for payload in payloads:
        results.append(publish_result_event(stream_name, payload))
    return results


def _ensure_stream_group(client, stream_name):
    key = _stream_key(stream_name)
    group = getattr(settings, "RESULT_EVENT_STREAM_GROUP", DEFAULT_STREAM_GROUP)
    try:
        client.xgroup_create(key, group, id="0", mkstream=True)
    except Exception:
        pass
    return group


def consume_result_events(stream_name, consumer_name="writer", count=None):
    if count is None:
        count = int(getattr(settings, "RESULT_EVENT_BATCH_SIZE", DEFAULT_STREAM_BATCH_SIZE))
    client = _get_stream_client()
    if client is None:
        with _memory_lock:
            events = []
            for _ in range(min(count, len(_memory_streams[stream_name]))):
                item = _memory_streams[stream_name].pop(0)
                _memory_pending[stream_name][item["id"]] = {
                    "payload": item["payload"],
                    "claimed_at": time.time(),
                    "consumer": consumer_name,
                }
                events.append({"id": item["id"], "payload": item["payload"]})
        return events

    group = _ensure_stream_group(client, stream_name)
    response = client.xreadgroup(group, consumer_name, {_stream_key(stream_name): ">"}, count=count, block=1)
    events = []
    for _, entries in (response or []):
        for entry_id, data in entries:
            raw = data.get(b"event") or data.get("event")
            if isinstance(raw, bytes):
                raw = raw.decode()
            events.append({"id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id, "payload": json.loads(raw)})
    return events


def reclaim_pending_result_events(stream_name, consumer_name="writer", idle_seconds=None, count=None):
    if idle_seconds is None:
        idle_seconds = int(getattr(settings, "RESULT_EVENT_PENDING_IDLE_SECONDS", DEFAULT_PENDING_IDLE_SECONDS))
    if count is None:
        count = int(getattr(settings, "RESULT_EVENT_BATCH_SIZE", DEFAULT_STREAM_BATCH_SIZE))
    client = _get_stream_client()
    if client is None:
        now = time.time()
        events = []
        with _memory_lock:
            for entry_id, pending in list(_memory_pending[stream_name].items()):
                if now - pending["claimed_at"] < idle_seconds:
                    continue
                pending["claimed_at"] = now
                pending["consumer"] = consumer_name
                events.append({"id": entry_id, "payload": pending["payload"]})
                if len(events) >= count:
                    break
        return events

    group = _ensure_stream_group(client, stream_name)
    response = client.xautoclaim(
        _stream_key(stream_name),
        group,
        consumer_name,
        min_idle_time=int(idle_seconds * 1000),
        start_id="0-0",
        count=count,
    )
    events = []
    if response:
        _, entries = response[0], response[1]
        for entry_id, data in entries:
            raw = data.get(b"event") or data.get("event")
            if isinstance(raw, bytes):
                raw = raw.decode()
            events.append({"id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id, "payload": json.loads(raw)})
    return events


def ack_result_events(stream_name, event_ids):
    if not event_ids:
        return 0
    client = _get_stream_client()
    if client is None:
        with _memory_lock:
            for event_id in event_ids:
                _memory_pending[stream_name].pop(event_id, None)
        return len(event_ids)

    group = _ensure_stream_group(client, stream_name)
    return client.xack(_stream_key(stream_name), group, *event_ids)


def get_pending_count(stream_name):
    client = _get_stream_client()
    if client is None:
        with _memory_lock:
            return len(_memory_pending[stream_name])
    group = _ensure_stream_group(client, stream_name)
    summary = client.xpending(_stream_key(stream_name), group)
    return summary.get("pending", 0) if isinstance(summary, dict) else summary[0]


def get_stream_depth(stream_name):
    client = _get_stream_client()
    if client is None:
        with _memory_lock:
            return len(_memory_streams[stream_name])
    return client.xlen(_stream_key(stream_name))


def _trim_stream(stream_name, maxlen=100):
    """裁剪 stream，只保留最近 maxlen 条。跳过 memory backend。"""
    client = _get_stream_client()
    if client is None:
        return
    try:
        client.xtrim(_stream_key(stream_name), maxlen=maxlen, approximate=False)
    except Exception:
        pass


def build_identify_event_payloads(task_id, url, header, title, content, status_code, ip_address, host, port, protocol, country, products, uri_path="", favicon=None, favicon_md5=None, cert_org=None, cert_org_unit=None, cert_common_name=None, cert_serial=None, province=None, city=None, isp=None, zone_id=None):
    # 写入路径硬约束：zone_id 不可为空。若为 None 说明上游未正确传递区域归属，兜底公网并记录。
    if zone_id is None:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "build_identify_event_payloads: zone_id is None for task=%s host=%s port=%s — 兜底公网",
            task_id, host, port,
        )
        try:
            from app_cybersparker.models import AssetZone
            # 公网区域 id 固定为 1。兜底时确保系统区域存在（测试环境可能被 truncate）。
            try:
                from app_cybersparker.models import AssetZone
                AssetZone.objects.get_or_create(
                    id=1,
                    defaults={"code": "public", "name": "公网", "is_system": True},
                )
            except Exception:
                pass
            zone_id = 1
        except Exception:
            pass
    product_list = sorted({item for item in (products or []) if item})
    if not product_list:
        product_list = [""]
    payloads = []
    for product in product_list:
        payloads.append({
            "event_id": f"identify:{task_id}:{url}:{product or '__none__'}",
            "task_id": task_id,
            "target": url,
            "product": product,
            "ip": ip_address,
            "host": (host or "")[:255],
            "port": port,
            "protocol": protocol,
            "country": (country or "")[:64],
            "title": title,
            "header": header,
            "html": content,
            "status_code": status_code,
            "uri_path": (uri_path or "")[:512],
            "favicon": favicon,
            "favicon_md5": favicon_md5,
            "cert_org": cert_org,
            "cert_org_unit": cert_org_unit,
            "cert_common_name": cert_common_name,
            "cert_serial": cert_serial,
            "province": (province or "")[:64],
            "city": (city or "")[:128],
            "isp": (isp or "")[:64],
            "zone_id": zone_id,
        })
    return payloads


def build_auto_exp_event_payload(task_id, exp_id, target, product, result, plugin_name=None, task_type=1, zone_id=None):
    payload = {
        "event_id": f"auto_exp:{task_id}:{target}:{exp_id or plugin_name or 'unknown'}",
        "task_id": task_id,
        "task_type": task_type,
        "exp_id": exp_id,
        "plugin_name": plugin_name,
        "target": target,
        "product": product,
        "result": result,
        "zone_id": zone_id,
    }
    return payload


def build_batch_result_event_payload(task_id, target, plugin_name, result):
    return {
        "event_id": f"batch_exp:{task_id}:{target}:{plugin_name}",
        "task_id": task_id,
        "target": target,
        "plugin_name": plugin_name,
        "result": result,
    }


def _strip_nul(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _write_identify_event(payload):
    product = _strip_nul(payload.get("product") or "")
    defaults = {
        "ip": _strip_nul((payload.get("ip") or "")[:45]),
        "uri_path": _strip_nul((payload.get("uri_path") or "")[:512]),
        "country": _strip_nul((payload.get("country") or "")[:64]),
        "title": _strip_nul((payload.get("title") or "")[:255]),
        "header": _strip_nul(payload["header"]),
        "html": _strip_nul(payload["html"]),
        "status_code": payload["status_code"],
        "favicon": _strip_nul(payload.get("favicon") or ""),
        "favicon_md5": _strip_nul((payload.get("favicon_md5") or "")[:32]),
        "cert_org": _strip_nul((payload.get("cert_org") or "")[:255]),
        "cert_org_unit": _strip_nul((payload.get("cert_org_unit") or "")[:255]),
        "cert_common_name": _strip_nul(payload.get("cert_common_name") or ""),
        "cert_serial": _strip_nul((payload.get("cert_serial") or "")[:128]),
        "province": _strip_nul((payload.get("province") or "")[:64]),
        "city": _strip_nul((payload.get("city") or "")[:128]),
        "isp": _strip_nul((payload.get("isp") or "")[:64]),
        "products": [product] if product else [],
    }
    zone_id = payload.get("zone_id")
    if zone_id is None:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "_write_identify_event: payload 缺少 zone_id，兜底公网。target=%s",
            payload.get("target", ""),
        )
        try:
            from app_cybersparker.models import AssetZone
            # 公网区域 id 固定为 1。兜底时确保系统区域存在（测试环境可能被 truncate）。
            try:
                from app_cybersparker.models import AssetZone
                AssetZone.objects.get_or_create(
                    id=1,
                    defaults={"code": "public", "name": "公网", "is_system": True},
                )
            except Exception:
                pass
            zone_id = 1
        except Exception:
            pass
    match_keys = {
        "zone_id": zone_id,
        "protocol": _strip_nul((payload.get("protocol") or "")[:20]),
        "host": _strip_nul((payload.get("host") or "")[:255]),
        "port": payload["port"],
        "uri_path": "" if (payload.get("uri_path") or "").strip() == "/" else ((payload.get("uri_path") or "").strip() or "")[:512],
    }
    row = models.auto_scan_indentify_result.objects.filter(**match_keys).first()
    if row:
        if product:
            merged = sorted(set(row.products or []) | {product})
        else:
            merged = list(row.products or [])
        defaults["products"] = merged
        # 已有行时不覆盖 uri_path 为空值，保留历史值
        if not defaults.get("uri_path"):
            defaults.pop("uri_path", None)
        models.auto_scan_indentify_result.objects.filter(**match_keys).update(**defaults)
    else:
        defaults.pop("uri_path", None)  # match_keys 已经包含 uri_path，避免重复
        row = models.auto_scan_indentify_result.objects.create(
            target=_strip_nul(payload["target"][:128] if payload.get("target") else ""),
            **match_keys,
            **defaults,
        )

    global _relation_buffer
    _relation_buffer.append(
        models.AssetTaskRelation(task_id=payload["task_id"], identify_result=row)
    )
    if len(_relation_buffer) >= 500:
        _flush_relations()


def _resolve_identify_result_id(target, zone_id):
    if zone_id is None:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "_resolve_identify_result_id: zone_id is None for target=%s — 兜底公网",
            target,
        )
        try:
            from app_cybersparker.models import AssetZone
            # 公网区域 id 固定为 1。兜底时确保系统区域存在（测试环境可能被 truncate）。
            try:
                from app_cybersparker.models import AssetZone
                AssetZone.objects.get_or_create(
                    id=1,
                    defaults={"code": "public", "name": "公网", "is_system": True},
                )
            except Exception:
                pass
            zone_id = 1
        except Exception:
            pass
    if "://" not in target:
        target = "http://" + target
    parsed = urlparse(target)
    protocol = parsed.scheme or "http"
    host = parsed.hostname or ""
    port = parsed.port or (443 if protocol == "https" else 80)
    raw_path = (parsed.path or "").strip()
    uri_path = "" if raw_path == "/" else raw_path[:512]
    asset, _ = models.auto_scan_indentify_result.objects.get_or_create(
        zone_id=zone_id, protocol=protocol, host=host, port=port, uri_path=uri_path,
        defaults={"target": f"{protocol}://{host}:{port}{uri_path}", "products": [], "source_type": 1},
    )
    return asset.id


def _write_auto_exp_event(payload):
    target = _strip_nul(payload["target"])[:128]
    identify_result_id = _resolve_identify_result_id(target, payload.get("zone_id"))
    exp_id = payload.get("exp_id")
    if exp_id is None:
        plugin_name = _strip_nul(payload.get("plugin_name") or "")
        match = re.search(r"\[(.*?)\](.*)", plugin_name)
        if match:
            exp_obj = models.EXP.objects.filter(CVE=match.group(1), title=match.group(2)).first()
        else:
            exp_obj = models.EXP.objects.filter(title=plugin_name).first()
    else:
        exp_obj = models.EXP.objects.get(id=int(exp_id))
    if not exp_obj:
        raise ValueError("missing exp mapping for auto exp result event")
    models.auto_scan_exp_result.objects.create(
        task_id=payload["task_id"],
        task_type=payload.get("task_type", 1),
        identify_result_id=identify_result_id,
        target=target,
        EXP_id=exp_obj,
        product=_strip_nul(payload.get("product", ""))[:128],
        result=_strip_nul(payload.get("result", "")),
    )


def _write_batch_event(payload):
    _, created = models.EXPTask_result.objects.get_or_create(
        task_type=2,
        task_id=payload["task_id"],
        target=_strip_nul(payload["target"])[:128],
        plugin_name=_strip_nul(payload["plugin_name"])[:128],
        defaults={"result": _strip_nul(payload.get("result", ""))},
    )
    if not created:
        models.EXPTask_result.objects.filter(
            task_type=2,
            task_id=payload["task_id"],
            target=_strip_nul(payload["target"])[:128],
            plugin_name=_strip_nul(payload["plugin_name"])[:128],
        ).update(result=_strip_nul(payload.get("result", "")))


def _write_event(stream_name, payload):
    with transaction.atomic():
        if stream_name == STREAM_IDENTIFY:
            _write_identify_event(payload)
        elif stream_name == STREAM_AUTO_EXP:
            _write_auto_exp_event(payload)
        elif stream_name == STREAM_BATCH_EXP:
            _write_batch_event(payload)
        else:
            raise ValueError(f"unsupported stream: {stream_name}")


def throttle_dispatch_result_writer(stream_name):
    """同一 stream 5 秒内只投递一次 writer task，避免高频重复投递。"""
    client = _get_stream_client()
    if client is None:
        from app_cybersparker.services.celery_runtime_service import dispatch_task
        from app_cybersparker.tasks import run_result_writer_task
        dispatch_task(run_result_writer_task, stream_name, queue="result_writer")
        return
    key = f"_writer_throttle:{stream_name}"
    if client.set(key, "1", nx=True, ex=5):
        from app_cybersparker.services.celery_runtime_service import dispatch_task
        from app_cybersparker.tasks import run_result_writer_task
        dispatch_task(run_result_writer_task, stream_name, queue="result_writer")


def process_result_stream(stream_name, consumer_name="writer", count=None):
    events = consume_result_events(stream_name, consumer_name=consumer_name, count=count)
    if not events:
        events = reclaim_pending_result_events(stream_name, consumer_name=consumer_name, count=count)
    if not events:
        return {"stream": stream_name, "processed": 0, "pending": get_pending_count(stream_name)}

    processed_ids = []
    for event in events:
        try:
            _write_event(stream_name, event["payload"])
            processed_ids.append(event["id"])
        except (OperationalError, DatabaseError, TimeoutError):
            break
    ack_result_events(stream_name, processed_ids)
    _trim_stream(stream_name)
    _flush_relations()
    return {"stream": stream_name, "processed": len(processed_ids), "pending": get_pending_count(stream_name)}


def process_result_streams(stream_names=None, consumer_name="writer", count=None):
    stream_names = stream_names or STREAM_NAMES
    results = []
    for stream_name in stream_names:
        results.append(process_result_stream(stream_name, consumer_name=consumer_name, count=count))
    return results
