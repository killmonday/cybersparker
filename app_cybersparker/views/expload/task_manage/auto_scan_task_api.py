"""API endpoints for auto scan task management (/api/v1/identify-tasks/*).

Follows the same contract shapes as proxy_setting.py list_api / detail_api / create_api / update_api.
Operations (start/pause/resume/stop) continue to use the old /Identify_task/operate endpoint.
"""

from django.db.models import Q
from django.http import JsonResponse, QueryDict

from app_cybersparker import models
from app_cybersparker.permissions import deny_user
from app_cybersparker.utils.pagination import Pagination

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def _status_label(obj):
    """Compute the display status string matching the old template's 6-state logic."""
    if obj.status == 1:
        return "finish", "完成", "status-finish"
    if obj.status == 4:
        return "pause", "已暂停", "status-paused"
    if obj.status == 2 and getattr(obj, "pause_requested", False):
        return "pausing", "暂停中...", "status-pausing"
    if obj.status == 2 and getattr(obj, "queued", False):
        return "waiting", "等待中", "status-waiting"
    if obj.status == 2:
        return "running", "运行中", "status-running"
    if obj.status == 3:
        if obj.startTime is None:
            return "unstarted", "未启动", "status-unstarted"
        return "stopped", "已停止", "status-stopped"
    return "unknown", str(obj.status), ""


def _phase_label(phase):
    mapping = {1: "正在Web扫描", 2: "正在漏洞扫描", 3: "全部完成"}
    return mapping.get(phase, str(phase) if phase else "")


def _task_to_item(obj):
    status_key, status_label_text, status_class = _status_label(obj)
    zone_name = obj.zone.name if obj.zone_id else ""
    return {
        "id": obj.id,
        "task_name": obj.task_name,
        "zone_id": obj.zone_id,
        "zone_name": zone_name,
        "status": obj.status,
        "status_key": status_key,
        "status_label": status_label_text,
        "status_class": status_class,
        "process": obj.process or "0%",
        "phase": obj.phase,
        "phase_label": _phase_label(obj.phase),
        "pause_requested": bool(getattr(obj, "pause_requested", False)),
        "queued": bool(getattr(obj, "queued", False)),
        "startTime": obj.startTime.strftime("%Y-%m-%d %H:%M") if obj.startTime else None,
        "endTime": obj.endTime.strftime("%Y-%m-%d %H:%M") if obj.endTime else None,
        "remark": obj.remark,
        "input_type": obj.input_type,
        "vulnerability_scanning": obj.Vulnerability_scanning,
        "result_url": f"/Identify_task/{obj.id}/result",
        "react_result_url": f"/react-shell/identify-tasks/{obj.id}/results",
    }


def task_list_api(request):
    """GET /api/v1/identify-tasks"""
    q = request.GET.get("q", "")
    page_str = request.GET.get("page", "1")
    rows_str = request.GET.get("rows_per_page", "13")
    try:
        page = int(page_str)
    except (ValueError, TypeError):
        page = 1
    try:
        rows = int(rows_str)
    except (ValueError, TypeError):
        rows = 13
    if rows not in ROWS_PER_PAGE_WHITELIST:
        rows = 13

    queryset = models.auto_scan_tasks.objects.all().order_by("-id")
    if q:
        queryset = queryset.filter(Q(task_name__icontains=q))

    # Build a QueryDict with the sanitized params for Pagination
    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PaginationRequest:
        def __init__(self):
            self.GET = qd

    page_object = Pagination(_PaginationRequest(), queryset)

    items = [_task_to_item(obj) for obj in page_object.page_queryset]

    return JsonResponse({
        "items": items,
        "page": page_object.page,
        "rows_per_page": page_object.page_size,
        "total": page_object.total_count,
        "total_pages": page_object.total_page_count,
        "filters": {"q": q},
        "legacy_list_url": "/Identify_task/list",
    })


def task_detail_api(request, uid):
    """GET /api/v1/identify-tasks/<uid>"""
    obj = models.auto_scan_tasks.objects.filter(id=uid).values(
        "id", "task_name", "thread_num", "vulnerability_thread_num",
        "sleep_time", "http_timeout", "input_type", "search_query",
        "history_files", "engine_type", "engine_query", "engine_max_assets",
        "engine_proxy_mode", "engine_proxy_id",
        "Vulnerability_scanning", "proxy_id", "remark",
        "reuse_engine_data", "parsed_query", "frozen_max_id", "last_id",
        "target", "task_args", "fscanx_file", "conflict_strategy",
        "zone_id",
    ).first()
    if not obj:
        return JsonResponse({"status": False, "error": "未找到"}, status=404)

    target_val = obj.get("target") or ""
    obj["target"] = target_val.split("/")[-1] if "/" in target_val else target_val

    can_reuse = False
    if int(obj.get("input_type") or 1) == 4:
        from app_cybersparker.views.expload.task_manage.auto_scan_task import _can_reuse_engine_data
        can_reuse = _can_reuse_engine_data(obj)
    return JsonResponse({
        "status": True,
        "data": obj,
        "can_reuse_engine_data": can_reuse,
    })


def task_status_api(request, uid):
    """GET /api/v1/identify-tasks/<uid>/status — lightweight polling endpoint"""
    obj = models.auto_scan_tasks.objects.filter(id=uid).values(
        "status", "phase", "process", "pause_requested", "queued", "startTime",
    ).first()
    if not obj:
        return JsonResponse({"status": False, "error": "未找到"}, status=404)

    status_str, _, _ = _status_label(_FauxObj(obj))

    return JsonResponse({
        "status": True,
        "data": {
            "process": obj["process"] or "0%",
            "status": status_str,
            "phase": obj["phase"],
            "pause_requested": bool(obj["pause_requested"]),
            "queued": bool(obj["queued"]),
        },
    })


class _FauxObj:
    """把 values() 返回的 dict 包装成可属性访问的对象，供 _status_label 复用。"""
    def __init__(self, d):
        self.__dict__.update(d)

def task_status_batch_api(request):
    """GET /api/v1/identify-tasks/status-batch?ids=1,2,3"""
    ids_str = request.GET.get("ids", "")
    if not ids_str:
        return JsonResponse({"status": True, "data": {}})
    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        return JsonResponse({"status": True, "data": {}})
    objs = models.auto_scan_tasks.objects.filter(id__in=ids).values(
        "id", "status", "phase", "process", "pause_requested", "queued", "startTime",
    )
    result = {}
    for obj in objs:
        status_str, _, _ = _status_label(_FauxObj(obj))
        result[obj["id"]] = {
            "process": obj["process"] or "0%",
            "status": status_str,
            "phase": obj["phase"],
            "pause_requested": bool(obj["pause_requested"]),
            "queued": bool(obj["queued"]),
        }
    return JsonResponse({"status": True, "data": result})


def task_choices_api(request):
    """GET /api/v1/identify-tasks/choices — dropdown options for the add/edit form"""
    proxy_choices = [
        {"value": p.id, "label": f"{p.get_proxy_type_display()} | {p.proxy_address}:{p.proxy_port}"}
        for p in models.ProxySetting.objects.all().order_by("id")
    ]
    proxy_choices.insert(0, {"value": "", "label": "不选择代理"})

    engine_proxy_choices = list(proxy_choices)

    return JsonResponse({
        "status": True,
        "proxy_choices": proxy_choices,
        "engine_proxy_choices": engine_proxy_choices,
        "input_type_choices": [
            {"value": 1, "label": "从文件上传"},
            {"value": 2, "label": "fscanx输出文件"},
            {"value": 3, "label": "历史上传文件"},
            {"value": 4, "label": "空间测绘引擎"},
            {"value": 5, "label": "历史测绘结果"},
            {"value": 6, "label": "从检索语句导入"},
        ],
        "engine_type_choices": [
            {"value": "fofa", "label": "fofa"},
            {"value": "zoomeye", "label": "zoomeye"},
            {"value": "quake", "label": "quake"},
            {"value": "hunter", "label": "hunter"},
            {"value": "shodan", "label": "shodan"},
        ],
        "engine_proxy_mode_choices": [
            {"value": 0, "label": "跟随引擎配置"},
            {"value": 1, "label": "不使用代理"},
            {"value": 2, "label": "强制代理"},
        ],
        "vulnerability_scanning_choices": [
            {"value": 0, "label": "不进行漏洞扫描"},
            {"value": 1, "label": "Web扫描后漏洞扫描"},
            {"value": 2, "label": "仅漏洞扫描（跳过Web探测）"},
        ],
    })


def task_history_files_api(request):
    """GET /api/v1/identify-tasks/history-files"""
    import os
    from django.conf import settings as s

    target_dir = os.path.join(os.path.dirname(s.THIS_DIR), "EXP_input")
    files = []
    if os.path.isdir(target_dir):
        for fname in sorted(os.listdir(target_dir), reverse=True):
            fpath = os.path.join(target_dir, fname)
            if os.path.isfile(fpath):
                mtime = os.path.getmtime(fpath)
                from datetime import datetime
                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                fsize = os.path.getsize(fpath)
                files.append({"file_name": fname, "mtime": mtime_str, "size": fsize})
    return JsonResponse({"status": True, "data": {"files": files}})


def task_history_engine_results_api(request):
    """GET /api/v1/identify-tasks/history-engine-results"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import list_history_engine_results
    results = list_history_engine_results()
    return JsonResponse({"status": True, "data": {"results": results}})


@deny_user
def task_create_api(request):
    """POST /api/v1/identify-tasks/create — delegates to existing add()"""
    from app_cybersparker.views.expload.task_manage.auto_scan_task import add
    # Ensure POST is mutable for the add function
    if hasattr(request.POST, '_mutable'):
        request.POST._mutable = True
    return add(request)


@deny_user
def task_update_api(request, uid):
    """POST /api/v1/identify-tasks/<uid>/update — delegates to existing edit()"""
    from app_cybersparker.views.expload.task_manage.auto_scan_task import edit
    request.GET = request.GET.copy()
    request.GET['uid'] = str(uid)
    return edit(request)


@deny_user
def task_operate_api(request, uid):
    """POST /api/v1/identify-tasks/<uid>/operate — delegates to existing Task_operate()"""
    from app_cybersparker.views.expload.task_manage.auto_scan_task import Task_operate
    mutable_post = request.POST.copy()
    mutable_post['uid'] = str(uid)
    request.POST = mutable_post
    return Task_operate(request)


@deny_user
def task_delete_api(request, uid):
    """DELETE /api/v1/identify-tasks/<uid>/delete — single delete via POST"""
    from app_cybersparker.views.expload.task_manage.auto_scan_task import delete as _delete
    if request.method not in ('POST', 'DELETE'):
        return JsonResponse({'status': False, 'error': '请求方法不允许'}, status=405)
    # Make a GET-style request for the existing single-delete logic
    request.method = 'GET'
    request.GET = request.GET.copy()
    request.GET['uid'] = str(uid)
    return _delete(request)


@deny_user
def task_batch_delete_api(request):
    """POST /api/v1/identify-tasks/batch-delete  body: {"uids": [1,2,3]}"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "请选择要删除的ID"})

    from app_cybersparker.views.expload.task_manage.auto_scan_task import _delete_auto_scan_task
    deleted = 0
    for uid in uids:
        try:
            task_obj = models.auto_scan_tasks.objects.filter(id=uid).first()
            if task_obj:
                _delete_auto_scan_task(task_obj)
                deleted += 1
        except Exception:
            pass
    return JsonResponse({"status": True, "tips": f"已删除 {deleted} 个任务"})
