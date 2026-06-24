from django.db.models import Q
from django.utils import timezone


TERMINAL_STATES = {"success", "stopped", "paused", "failed"}


def initialize_task_runtime(task_model, task_id, dispatch_token, owner, queued=False):
    return bool(
        task_model.objects.filter(id=task_id).update(
            dispatch_token=dispatch_token,
            owner=owner,
            queued=queued,
            failed=False,
            stop_requested=False,
            pause_requested=False,
            heartbeat_at=timezone.now(),
            last_error=None,
            endTime=None,
        )
    )


def claim_task_execution(task_model, task_id, dispatch_token, owner):
    return bool(
        task_model.objects.filter(
            id=task_id,
            dispatch_token=dispatch_token,
            endTime__isnull=True,
        ).filter(Q(owner__isnull=True) | Q(owner="")).update(
            owner=owner,
            queued=False,
            failed=False,
            heartbeat_at=timezone.now(),
            last_error=None,
            status=2,
        )
    )


def compare_and_set_terminal_state(task_model, task_id, dispatch_token, owner, terminal_state, last_error=None):
    if terminal_state not in TERMINAL_STATES:
        raise ValueError(f"unsupported terminal state: {terminal_state}")

    now = timezone.now()
    updates = {
        "queued": False,
        "heartbeat_at": now,
    }
    has_phase_field = any(field.name == "phase" for field in task_model._meta.concrete_fields)
    if terminal_state == "success":
        updates.update(status=1, process="100%", failed=False, stop_requested=False, pause_requested=False, last_error=None, endTime=now)
        if has_phase_field:
            updates["phase"] = 3
    elif terminal_state == "stopped":
        updates.update(status=3, failed=False, stop_requested=True, pause_requested=False, last_error=None, endTime=now)
        if has_phase_field:
            updates["phase"] = 3
    elif terminal_state == "paused":
        updates.update(status=4, failed=False, stop_requested=False, pause_requested=False, last_error=None, endTime=now)
        if has_phase_field:
            updates["phase"] = 3
    else:
        updates.update(status=3, failed=True, stop_requested=False, pause_requested=False, last_error=last_error or "task failed", endTime=now)
        if has_phase_field:
            updates["phase"] = 3

    return bool(
        task_model.objects.filter(
            id=task_id,
            dispatch_token=dispatch_token,
            owner=owner,
            endTime__isnull=True,
        ).update(**updates)
    )
