from threading import active_count
from typing import Any, cast

from django.conf import settings
from django.db import connections
from django.db.models import Count, Q
from django.utils import timezone

from dj_db_conn_pool.core import pool_container

from app_cybersparker import models


TASK_MODELS = {
    "batch": models.batch_EXPTask,
    "auto": models.auto_scan_tasks,
}

TASK_HANDLES = {
    "batch": settings.BATH_TASK_DIC,
    "auto": settings.KILL_AUTO_TASK_DIC,
}

TASK_QUEUE_FIELDS = {
    "batch": ("queue_input", "queue_output"),
    "auto": ("queue_input", "queue_fingerpoint_input", "queue_EXP_input", "queue_EXP_result"),
}


def _get_runtime_config():
    return {
        "observe_only": getattr(settings, "SCHEDULER_BASELINE_OBSERVE_ONLY", True),
        "global_http_inflight_limit": getattr(settings, "GLOBAL_HTTP_INFLIGHT_LIMIT", 2000),
        "global_thread_limit": getattr(settings, "GLOBAL_THREAD_LIMIT", 1800),
        "global_coroutine_limit": getattr(settings, "GLOBAL_COROUTINE_LIMIT", 8000),
        "global_db_writer_limit": getattr(settings, "GLOBAL_DB_WRITER_LIMIT", 8),
        "postgres_max_connections_target": getattr(settings, "POSTGRES_MAX_CONNECTIONS_TARGET", 100),
    }


def _normalize_task_id(task_id):
    if task_id in (None, ""):
        return None
    return str(task_id)


def _find_handle(task_type, task_id):
    handle_map = TASK_HANDLES.get(task_type)
    normalized_task_id = _normalize_task_id(task_id)
    if not handle_map or normalized_task_id is None:
        return None

    candidates: list[object] = [normalized_task_id]
    try:
        candidates.append(int(normalized_task_id))
    except (TypeError, ValueError):
        pass

    for candidate in candidates:
        if candidate in handle_map:
            return handle_map[candidate]
    return None


def _get_queue_lengths(task_type, handle):
    if handle is None:
        return {}

    queue_lengths = {}
    for field_name in TASK_QUEUE_FIELDS.get(task_type, ()):
        queue_obj = getattr(handle, field_name, None)
        qsize = getattr(queue_obj, "qsize", None)
        if not callable(qsize):
            continue
        try:
            queue_lengths[field_name] = qsize()
        except Exception:
            continue
    return queue_lengths


def _get_task_elapsed_seconds(task_type, task_id):
    task_model = TASK_MODELS.get(task_type)
    normalized_task_id = _normalize_task_id(task_id)
    if task_model is None or normalized_task_id is None:
        return 0

    task = task_model.objects.filter(id=normalized_task_id).values("startTime").first()
    if not task or not task["startTime"]:
        return 0

    elapsed = int((timezone.now() - task["startTime"]).total_seconds())
    return max(elapsed, 0)


def _get_db_pool_snapshot(alias="default"):
    if not pool_container.has(alias):
        return {"checked_out": 0, "size": 0, "overflow": 0}

    db_pool = pool_container.get(alias)
    checked_out = db_pool.checkedout()
    wrapper = connections[alias]
    if getattr(wrapper, "connection", None) is not None:
        checked_out = max(checked_out - 1, 0)

    return {
        "checked_out": checked_out,
        "size": db_pool.size(),
        "overflow": db_pool.overflow(),
    }


def _get_exp_task_usage():
    exp_task_model = cast(Any, models.EXPTask)
    exp_task_manager = exp_task_model.objects
    task_type_counts = []
    for item in exp_task_manager.values("taskType").annotate(total=Count("id")).order_by("taskType"):
        task_type_counts.append(
            {
                "task_type": item["taskType"],
                "label": exp_task_model(taskType=item["taskType"]).get_taskType_display(),
                "total": item["total"],
            }
        )

    cmd_input_non_empty_count = exp_task_manager.exclude(
        Q(cmd_input__isnull=True) | Q(cmd_input="")
    ).count()

    return {
        "task_type_counts": task_type_counts,
        "cmd_input_non_empty_count": cmd_input_non_empty_count,
    }


def _get_status_model_plan():
    return {
        "state_sources": {
            "db": "business_terminal_source",
            "redis": "runtime_coordination_source",
            "memory_dicts": "local_handle_cache_only",
        },
        "legacy_handle_dicts": ["THREAD_DIC", "BATH_TASK_DIC", "KILL_AUTO_TASK_DIC"],
        "planned_fields": list(getattr(settings, "SCHEDULER_STATUS_MODEL_FIELDS", ())),
        "ui_mapping": {
            "queued": "waiting",
            "failed": "failed",
            "finish": "finish",
            "running": "running",
            "stop": "stop",
        },
    }


def get_runtime_diagnostics(task_type=None, task_id=None):
    normalized_task_type = task_type if task_type in TASK_MODELS else None
    handle = _find_handle(normalized_task_type, task_id)
    queue_lengths = _get_queue_lengths(normalized_task_type, handle)
    elapsed_seconds = _get_task_elapsed_seconds(normalized_task_type, task_id)
    exp_task_usage = _get_exp_task_usage()
    db_pool_snapshot = _get_db_pool_snapshot()

    return {
        "task_type": normalized_task_type,
        "task_id": _normalize_task_id(task_id),
        "thread_count": active_count(),
        "db_pool_checked_out": db_pool_snapshot["checked_out"],
        "db_pool_size": db_pool_snapshot["size"],
        "db_pool_overflow": db_pool_snapshot["overflow"],
        "queue_lengths": queue_lengths,
        "elapsed_seconds": elapsed_seconds,
        "handle_counts": {
            "batch": len(settings.BATH_TASK_DIC),
            "auto": len(settings.KILL_AUTO_TASK_DIC),
        },
        "resource_config": _get_runtime_config(),
        "exp_task_usage": exp_task_usage,
        "status_model_plan": _get_status_model_plan(),
    }
