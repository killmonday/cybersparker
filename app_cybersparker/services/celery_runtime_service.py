from django.conf import settings


DEFAULT_QUEUE_NAMES = ("auto_scan", "batch_scan", "batch_scan_gevent", "result_writer", "maintenance")
DEFAULT_EAGER_QUEUE = "maintenance"


def get_celery_queue_names():
    return tuple(getattr(settings, "CELERY_QUEUE_NAMES", DEFAULT_QUEUE_NAMES))


def get_connection_budget_snapshot():
    pool_options = settings.DATABASES["default"].get("POOL_OPTIONS", {})
    web_db_per_process = int(pool_options.get("POOL_SIZE", 0)) + int(pool_options.get("MAX_OVERFLOW", 0))
    celery_db_per_process = int(getattr(settings, "CELERY_DB_POOL_SIZE", 0)) + int(
        getattr(settings, "CELERY_DB_POOL_OVERFLOW", 0)
    )
    gevent_db_per_process = int(getattr(settings, "CELERY_GEVENT_DB_POOL_SIZE", 0)) + int(
        getattr(settings, "CELERY_GEVENT_DB_POOL_OVERFLOW", 0)
    )
    web_processes = int(getattr(settings, "WEB_CONCURRENCY", 1))
    celery_processes = int(getattr(settings, "CELERY_WORKER_CONCURRENCY", 1))
    gevent_processes = int(getattr(settings, "CELERY_GEVENT_CHILD_PROCESSES", 0))
    reserved = int(getattr(settings, "DB_CONNECTION_RESERVED", 0))
    target = int(getattr(settings, "POSTGRES_MAX_CONNECTIONS_TARGET", 100))
    projected_total = (
        web_processes * web_db_per_process
        + celery_processes * celery_db_per_process
        + gevent_processes * gevent_db_per_process
        + reserved
    )
    return {
        "target": target,
        "reserved": reserved,
        "web_processes": web_processes,
        "web_db_per_process": web_db_per_process,
        "celery_processes": celery_processes,
        "celery_db_per_process": celery_db_per_process,
        "gevent_processes": gevent_processes,
        "gevent_db_per_process": gevent_db_per_process,
        "projected_total": projected_total,
    }


def is_connection_budget_within_limit(snapshot=None):
    budget_snapshot = snapshot or get_connection_budget_snapshot()
    return budget_snapshot["projected_total"] <= budget_snapshot["target"]


def _build_budget_error(prefix):
    snapshot = get_connection_budget_snapshot()
    return RuntimeError(
        f"{prefix}: projected db connections {snapshot['projected_total']} exceed target {snapshot['target']} "
        f"(web={snapshot['web_processes']}x{snapshot['web_db_per_process']}, "
        f"celery={snapshot['celery_processes']}x{snapshot['celery_db_per_process']}, "
        f"gevent={snapshot['gevent_processes']}x{snapshot['gevent_db_per_process']}, reserved={snapshot['reserved']})"
    )


def assert_celery_connection_budget():
    if not is_connection_budget_within_limit():
        raise _build_budget_error("Celery worker startup rejected")
    return get_connection_budget_snapshot()


def ensure_celery_dispatch_enabled():
    if not is_connection_budget_within_limit():
        raise _build_budget_error("Celery dispatch rejected")
    return get_connection_budget_snapshot()


def dispatch_task(task, *args, queue=None, **kwargs):
    ensure_celery_dispatch_enabled()
    task_app = task._get_app()
    if bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)) or bool(task_app.conf.task_always_eager):
        return task.apply(args=args, kwargs=kwargs)

    route_queue = queue or getattr(task, "queue", None) or DEFAULT_EAGER_QUEUE
    return task.apply_async(args=args, kwargs=kwargs, queue=route_queue, routing_key=route_queue)
