import threading
import time
import uuid

from django.conf import settings
from django.utils import timezone

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


RESOURCE_LIMIT_GETTERS = {
    "http_inflight": lambda: int(getattr(settings, "GLOBAL_HTTP_INFLIGHT_LIMIT", 2000)),
    "threads": lambda: int(getattr(settings, "GLOBAL_THREAD_LIMIT", 1800)),
    "coroutines": lambda: int(getattr(settings, "GLOBAL_COROUTINE_LIMIT", 8000)),
    "db_writers": lambda: int(getattr(settings, "GLOBAL_DB_WRITER_LIMIT", 8)),
    "running_auto_scan": lambda: int(getattr(settings, "RUNNING_AUTO_SCAN_LIMIT", 1)),
    "running_batch_scan": lambda: int(getattr(settings, "RUNNING_BATCH_SCAN_LIMIT", 1)),
}

DEFAULT_LEASE_TTL_SECONDS = 30
DEFAULT_RETRY_DELAY_SECONDS = 5
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10

_memory_lock = threading.Lock()
_memory_leases = {}
_redis_client_lock = threading.Lock()
_redis_client_cache = {}


ACQUIRE_LEASE_SCRIPT = """
local amounts_key = KEYS[1]
local expiries_key = KEYS[2]
local owners_key = KEYS[3]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local amount = tonumber(ARGV[3])
local lease_id = ARGV[4]
local owner = ARGV[5]
local expires_at = tonumber(ARGV[6])
local ttl = tonumber(ARGV[7])
local expiries = redis.call('HGETALL', expiries_key)
local current = 0
for i=1,#expiries,2 do
  local id = expiries[i]
  local exp = tonumber(expiries[i+1]) or 0
  if exp <= now then
    redis.call('HDEL', expiries_key, id)
    redis.call('HDEL', amounts_key, id)
    redis.call('HDEL', owners_key, id)
  else
    current = current + tonumber(redis.call('HGET', amounts_key, id) or '0')
  end
end
if current + amount > limit then
  return ''
end
redis.call('HSET', amounts_key, lease_id, amount)
redis.call('HSET', expiries_key, lease_id, expires_at)
redis.call('HSET', owners_key, lease_id, owner)
redis.call('EXPIRE', amounts_key, ttl)
redis.call('EXPIRE', expiries_key, ttl)
redis.call('EXPIRE', owners_key, ttl)
return lease_id
"""

HEARTBEAT_LEASE_SCRIPT = """
local amounts_key = KEYS[1]
local expiries_key = KEYS[2]
local owners_key = KEYS[3]
local lease_id = ARGV[1]
local expires_at = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if redis.call('HEXISTS', expiries_key, lease_id) == 0 then
  return 0
end
redis.call('HSET', expiries_key, lease_id, expires_at)
redis.call('EXPIRE', amounts_key, ttl)
redis.call('EXPIRE', expiries_key, ttl)
redis.call('EXPIRE', owners_key, ttl)
return 1
"""

RELEASE_LEASE_SCRIPT = """
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('HDEL', KEYS[3], ARGV[1])
return 1
"""


class ResourceUnavailableError(RuntimeError):
    def __init__(self, resource_name):
        self.resource_name = resource_name
        super().__init__(f"waiting_resource:{resource_name}")


def _time_seconds():
    return time.time()


def _lease_ttl_seconds():
    return int(getattr(settings, "RESOURCE_LEASE_TTL_SECONDS", DEFAULT_LEASE_TTL_SECONDS))


def get_resource_retry_delay_seconds():
    return int(getattr(settings, "RESOURCE_RETRY_DELAY_SECONDS", DEFAULT_RETRY_DELAY_SECONDS))


def get_resource_heartbeat_interval_seconds():
    return int(getattr(settings, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", DEFAULT_HEARTBEAT_INTERVAL_SECONDS))


def get_resource_limit(resource_name):
    getter = RESOURCE_LIMIT_GETTERS[resource_name]
    return getter()


def _amounts_key(resource_name):
    return f"resource:amounts:{resource_name}"


def _expiries_key(resource_name):
    return f"resource:expiries:{resource_name}"


def _owners_key(resource_name):
    return f"resource:owners:{resource_name}"


def _get_redis_client():
    if redis is None:
        return None
    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    if not broker_url.startswith("redis://"):
        return None
    client = _redis_client_cache.get(broker_url)
    if client is not None:
        return client
    with _redis_client_lock:
        client = _redis_client_cache.get(broker_url)
        if client is not None:
            return client
        try:
            client = redis.Redis.from_url(broker_url)
        except Exception:
            return None
        _redis_client_cache[broker_url] = client
        return client


def reset_memory_leases():
    with _memory_lock:
        _memory_leases.clear()
    with _redis_client_lock:
        _redis_client_cache.clear()


def _cleanup_memory(resource_name, now_ts):
    resource_leases = _memory_leases.setdefault(resource_name, {})
    expired_ids = [lease_id for lease_id, lease in resource_leases.items() if lease["expires_at"] <= now_ts]
    for lease_id in expired_ids:
        resource_leases.pop(lease_id, None)
    return resource_leases


def _acquire_memory_lease(resource_name, owner, amount, limit, ttl_seconds):
    now_ts = _time_seconds()
    with _memory_lock:
        resource_leases = _cleanup_memory(resource_name, now_ts)
        current = sum(lease["amount"] for lease in resource_leases.values())
        if current + amount > limit:
            return None
        lease_id = uuid.uuid4().hex
        resource_leases[lease_id] = {
            "amount": amount,
            "owner": owner,
            "expires_at": now_ts + ttl_seconds,
        }
        return lease_id


def _heartbeat_memory_lease(resource_name, lease_id, ttl_seconds):
    now_ts = _time_seconds()
    with _memory_lock:
        resource_leases = _cleanup_memory(resource_name, now_ts)
        lease = resource_leases.get(lease_id)
        if not lease:
            return False
        lease["expires_at"] = now_ts + ttl_seconds
        return True


def _release_memory_lease(resource_name, lease_id):
    with _memory_lock:
        resource_leases = _memory_leases.setdefault(resource_name, {})
        resource_leases.pop(lease_id, None)
        return True


def _get_memory_snapshot(resource_name):
    now_ts = _time_seconds()
    with _memory_lock:
        resource_leases = _cleanup_memory(resource_name, now_ts)
        in_use = sum(lease["amount"] for lease in resource_leases.values())
        return {"resource": resource_name, "in_use": in_use, "leases": len(resource_leases)}


def acquire_resource_lease(resource_name, owner, amount=1, limit=None, ttl_seconds=None):
    ttl_seconds = ttl_seconds or _lease_ttl_seconds()
    limit = limit or get_resource_limit(resource_name)
    client = _get_redis_client()
    if client is None:
        lease_id = _acquire_memory_lease(resource_name, owner, amount, limit, ttl_seconds)
        if not lease_id:
            raise ResourceUnavailableError(resource_name)
        return {"resource": resource_name, "lease_id": lease_id, "owner": owner, "amount": amount}

    lease_id = uuid.uuid4().hex
    now_ts = _time_seconds()
    expires_at = now_ts + ttl_seconds
    result = client.eval(
        ACQUIRE_LEASE_SCRIPT,
        3,
        _amounts_key(resource_name),
        _expiries_key(resource_name),
        _owners_key(resource_name),
        now_ts,
        limit,
        amount,
        lease_id,
        owner,
        expires_at,
        ttl_seconds,
    )
    if not result:
        raise ResourceUnavailableError(resource_name)
    return {"resource": resource_name, "lease_id": lease_id, "owner": owner, "amount": amount}


def release_resource_lease(resource_name, lease_id):
    client = _get_redis_client()
    if client is None:
        return _release_memory_lease(resource_name, lease_id)
    client.eval(
        RELEASE_LEASE_SCRIPT,
        3,
        _amounts_key(resource_name),
        _expiries_key(resource_name),
        _owners_key(resource_name),
        lease_id,
    )
    return True


def heartbeat_resource_lease(resource_name, lease_id, ttl_seconds=None):
    ttl_seconds = ttl_seconds or _lease_ttl_seconds()
    client = _get_redis_client()
    if client is None:
        return _heartbeat_memory_lease(resource_name, lease_id, ttl_seconds)
    expires_at = _time_seconds() + ttl_seconds
    result = client.eval(
        HEARTBEAT_LEASE_SCRIPT,
        3,
        _amounts_key(resource_name),
        _expiries_key(resource_name),
        _owners_key(resource_name),
        lease_id,
        expires_at,
        ttl_seconds,
    )
    return bool(result)


def get_resource_snapshot(resource_name):
    client = _get_redis_client()
    if client is None:
        snapshot = _get_memory_snapshot(resource_name)
        snapshot["limit"] = get_resource_limit(resource_name)
        return snapshot

    now_ts = _time_seconds()
    expiries = client.hgetall(_expiries_key(resource_name))
    in_use = 0
    lease_count = 0
    for lease_id_bytes, expiry_bytes in expiries.items():
        lease_id = lease_id_bytes.decode()
        expiry = int(expiry_bytes.decode())
        if expiry <= now_ts:
            release_resource_lease(resource_name, lease_id)
            continue
        amount = int(client.hget(_amounts_key(resource_name), lease_id) or 0)
        in_use += amount
        lease_count += 1
    return {"resource": resource_name, "limit": get_resource_limit(resource_name), "in_use": in_use, "leases": lease_count}


def release_resource_leases(resource_leases):
    for lease in resource_leases or []:
        release_resource_lease(lease["resource"], lease["lease_id"])


def heartbeat_resource_leases(resource_leases):
    for lease in resource_leases or []:
        heartbeat_resource_lease(lease["resource"], lease["lease_id"])


def acquire_resource_leases(resource_requirements, owner):
    leases = []
    try:
        for requirement in resource_requirements:
            leases.append(
                acquire_resource_lease(
                    requirement["resource"],
                    owner,
                    amount=requirement.get("amount", 1),
                    limit=requirement.get("limit"),
                    ttl_seconds=requirement.get("ttl_seconds"),
                )
            )
        return leases
    except Exception:
        release_resource_leases(leases)
        raise


def build_auto_scan_resource_requirements(thread_num, vulnerability_thread_num=None, vulnerability_scanning=0):
    fingerprint_threads = min(max(int(thread_num), 1), 3)
    exp_threads = 0
    if int(vulnerability_scanning or 0) in (1, 2):
        if vulnerability_thread_num in (None, ""):
            vulnerability_thread_num = 40
        exp_threads = max(int(vulnerability_thread_num), 1)
    return [
        {"resource": "running_auto_scan", "amount": 1},
        {"resource": "threads", "amount": max(fingerprint_threads + exp_threads, 1)},
    ]


def build_batch_scan_resource_requirements(run_mode, thread_num):
    requirements = [{"resource": "running_batch_scan", "amount": 1}]
    if int(run_mode or 1) == 2:
        requirements.append({"resource": "coroutines", "amount": max(int(thread_num), 1)})
    else:
        requirements.append({"resource": "threads", "amount": max(int(thread_num), 1)})
    return requirements


def mark_waiting_for_resource(task_model, task_id, resource_name):
    return bool(
        task_model.objects.filter(id=task_id).update(
            queued=True,
            failed=False,
            owner=None,
            heartbeat_at=timezone.now(),
            last_error=f"waiting_resource:{resource_name}",
            status=2,
            endTime=None,
        )
    )
