from django.conf import settings

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


STOP_KEY_TEMPLATE = "task-runtime:stop:{task_type}:{task_id}"
PAUSE_KEY_TEMPLATE = "task-runtime:pause:{task_type}:{task_id}"
SIGNAL_TTL_SECONDS = 60 * 60


def _get_redis_client():
    if redis is None:
        return None

    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    if not broker_url.startswith("redis://"):
        return None

    try:
        return redis.Redis.from_url(broker_url)
    except Exception:
        return None


def _build_stop_key(task_type, task_id):
    return STOP_KEY_TEMPLATE.format(task_type=task_type, task_id=task_id)


def _build_pause_key(task_type, task_id):
    return PAUSE_KEY_TEMPLATE.format(task_type=task_type, task_id=task_id)


# ---- stop signals ----

def set_stop_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        client.setex(_build_stop_key(task_type, task_id), SIGNAL_TTL_SECONDS, "1")
        return True
    except Exception:
        return False


def clear_stop_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        client.delete(_build_stop_key(task_type, task_id))
        return True
    except Exception:
        return False


def has_stop_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        return bool(client.get(_build_stop_key(task_type, task_id)))
    except Exception:
        return False


# ---- pause signals ----

def set_pause_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        client.setex(_build_pause_key(task_type, task_id), SIGNAL_TTL_SECONDS, "1")
        return True
    except Exception:
        return False


def clear_pause_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        client.delete(_build_pause_key(task_type, task_id))
        return True
    except Exception:
        return False


def has_pause_signal(task_type, task_id):
    client = _get_redis_client()
    if client is None:
        return False

    try:
        return bool(client.get(_build_pause_key(task_type, task_id)))
    except Exception:
        return False
