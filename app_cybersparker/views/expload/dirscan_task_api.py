"""API endpoints for directory scan task management (/api/v1/dirscan-tasks/*)."""

from django.db.models import Q
from django.http import JsonResponse, QueryDict

from app_cybersparker import models
from app_cybersparker.permissions import deny_user
from app_cybersparker.utils.pagination import Pagination

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}

STATUS_MAP = {0: "pending", 1: "running", 2: "paused", 3: "stopped", 4: "finished"}
STATUS_LABEL = {0: "待执行", 1: "运行中", 2: "已暂停", 3: "已停止", 4: "已完成"}
STATUS_CLASS = {0: "status-unstarted", 1: "status-running", 2: "status-paused", 3: "status-stopped", 4: "status-finish"}
PHASE_LABEL = {0: "未初始化", 1: "正在Web扫描", 2: "正在漏洞扫描", 3: "清理中"}


def _task_to_item(obj):
    return {
        "id": obj.id, "task_name": obj.task_name,
        "status": obj.status,
        "status_key": STATUS_MAP.get(obj.status, "unknown"),
        "status_label": STATUS_LABEL.get(obj.status, str(obj.status)),
        "status_class": STATUS_CLASS.get(obj.status, ""),
        "phase": obj.phase,
        "phase_label": PHASE_LABEL.get(obj.phase, str(obj.phase)) if obj.status != 4 else "已完成",
        "progress": f"{obj.progress_done}/{obj.progress_total}" if obj.progress_total else "0/0",
        "creatime": obj.creatime.strftime("%Y-%m-%d %H:%M") if obj.creatime else None,
        "start_time": obj.start_time.strftime("%Y-%m-%d %H:%M") if obj.start_time else None,
        "end_time": obj.end_time.strftime("%Y-%m-%d %H:%M") if obj.end_time else None,
    }


def dirscan_list_api(request):
    """GET /api/v1/dirscan-tasks"""
    q = request.GET.get("q", "")
    page_str = request.GET.get("page", "1")
    rows_str = request.GET.get("rows_per_page", "13")
    try: page = int(page_str)
    except (ValueError, TypeError): page = 1
    try: rows = int(rows_str)
    except (ValueError, TypeError): rows = 13
    if rows not in ROWS_PER_PAGE_WHITELIST: rows = 13

    queryset = models.DirScanTask.objects.all().order_by("-id")
    if q: queryset = queryset.filter(Q(task_name__icontains=q))

    qd = QueryDict(mutable=True); qd["page"] = str(page); qd["rows_per_page"] = str(rows)
    class _PR: GET = qd
    page_object = Pagination(_PR(), queryset)
    items = [_task_to_item(obj) for obj in page_object.page_queryset]

    return JsonResponse({"items": items, "page": page_object.page, "rows_per_page": page_object.page_size,
                         "total": page_object.total_count, "total_pages": page_object.total_page_count,
                         "filters": {"q": q}, "legacy_list_url": "/dirscan/task/list"})


def dirscan_status_api(request, uid):
    """GET /api/v1/dirscan-tasks/<uid>/status"""
    obj = models.DirScanTask.objects.filter(id=uid).values(
        "status", "phase", "progress_done", "progress_total", "pause_requested",
    ).first()
    if not obj: return JsonResponse({"status": False, "error": "not found"}, status=404)
    if obj["status"] == 1 and obj["pause_requested"]:
        status_str = "pausing"
    else:
        status_str = STATUS_MAP.get(obj["status"], "unknown")
    return JsonResponse({"status": True, "data": {
        "status": status_str,
        "phase": obj["phase"],
        "progress_done": obj["progress_done"] or 0,
        "progress_total": obj["progress_total"] or 0,
    }})

def dirscan_status_batch_api(request):
    """GET /api/v1/dirscan-tasks/status-batch?ids=1,2,3"""
    ids_str = request.GET.get("ids", "")
    if not ids_str:
        return JsonResponse({"status": True, "data": {}})
    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        return JsonResponse({"status": True, "data": {}})
    objs = models.DirScanTask.objects.filter(id__in=ids).values(
        "id", "status", "phase", "progress_done", "progress_total", "pause_requested",
    )
    result = {}
    for obj in objs:
        if obj["status"] == 1 and obj["pause_requested"]:
            status_str = "pausing"
        else:
            status_str = STATUS_MAP.get(obj["status"], "unknown")
        result[obj["id"]] = {
            "status": status_str,
            "phase": obj["phase"],
            "progress_done": obj["progress_done"] or 0,
            "progress_total": obj["progress_total"] or 0,
        }
    return JsonResponse({"status": True, "data": result})


@deny_user
def dirscan_create_api(request):
    """POST /api/v1/dirscan-tasks/create"""
    from app_cybersparker.views.expload.dirscan_task_manage import task_add
    if hasattr(request.POST, '_mutable'): request.POST._mutable = True
    return task_add(request)


@deny_user
def dirscan_update_api(request, uid):
    """POST /api/v1/dirscan-tasks/<uid>/update"""
    from app_cybersparker.views.expload.dirscan_task_manage import task_edit
    request.GET = request.GET.copy(); request.GET['uid'] = str(uid)
    if hasattr(request.POST, '_mutable'): request.POST._mutable = True
    return task_edit(request)


@deny_user
def dirscan_operate_api(request, uid):
    """POST /api/v1/dirscan-tasks/<uid>/operate"""
    from app_cybersparker.views.expload.dirscan_task_manage import task_operate
    mp = request.POST.copy() if hasattr(request.POST, 'copy') else request.POST
    if not hasattr(mp, '_mutable'): mp._mutable = True
    mp['uid'] = str(uid); request.POST = mp
    return task_operate(request)


@deny_user
def dirscan_delete_api(request, uid):
    """POST /api/v1/dirscan-tasks/<uid>/delete"""
    from app_cybersparker.views.expload.dirscan_task_manage import task_delete
    request.GET = request.GET.copy(); request.GET['uid'] = str(uid)
    return task_delete(request)


def dirscan_detail_api(request, uid):
    """GET /api/v1/dirscan-tasks/<uid>"""
    from app_cybersparker.views.expload.dirscan_task_manage import task_detail
    request.GET = request.GET.copy(); request.GET['uid'] = str(uid)
    return task_detail(request)


@deny_user
def dirscan_batch_delete_api(request):
    """POST /api/v1/dirscan-tasks/batch-delete  body: {"uids": [1,2,3]}"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    from app_cybersparker.views.expload.dirscan_task_manage import task_delete
    for uid in uids:
        try:
            request.GET = request.GET.copy(); request.GET['uid'] = str(uid)
            task_delete(request)
        except Exception:
            pass
    return JsonResponse({"status": True})
