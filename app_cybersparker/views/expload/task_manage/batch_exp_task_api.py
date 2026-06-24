"""API endpoints for batch exploit task management (/api/v1/batch-tasks/*)."""

from django.db.models import Q
from django.http import JsonResponse, QueryDict

from app_cybersparker import models
from app_cybersparker.permissions import deny_user
from app_cybersparker.utils.pagination import Pagination

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def _status_label(obj):
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


def _task_to_item(obj):
    status_key, status_label_text, status_class = _status_label(obj)
    return {
        "id": obj.id,
        "task_name": obj.task_name,
        "status": obj.status,
        "status_key": status_key,
        "status_label": status_label_text,
        "status_class": status_class,
        "process": obj.process or "0%",
        "pause_requested": bool(getattr(obj, "pause_requested", False)),
        "queued": bool(getattr(obj, "queued", False)),
        "input_type": obj.input_type,
        "startTime": obj.startTime.strftime("%Y-%m-%d %H:%M") if obj.startTime else None,
        "endTime": obj.endTime.strftime("%Y-%m-%d %H:%M") if obj.endTime else None,
        "remark": obj.remark,
        "run_mode": obj.run_mode,
        "exp_select_mode": obj.exp_select_mode,
        "result_url": f"/batch_exploadTask/{obj.id}/result",
        "react_result_url": f"/react-shell/exp-results?task_id={obj.id}",
        "react_edit_url": f"/react-shell/batch-tasks#edit-{obj.id}",
    }


def batch_task_list_api(request):
    """GET /api/v1/batch-tasks"""
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

    queryset = models.batch_EXPTask.objects.all().order_by("-id")
    if q:
        queryset = queryset.filter(Q(task_name__icontains=q))

    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PR:
        def __init__(self):
            self.GET = qd

    page_object = Pagination(_PR(), queryset)
    items = [_task_to_item(obj) for obj in page_object.page_queryset]

    return JsonResponse({
        "items": items,
        "page": page_object.page,
        "rows_per_page": page_object.page_size,
        "total": page_object.total_count,
        "total_pages": page_object.total_page_count,
        "filters": {"q": q},
        "legacy_list_url": "/batch_expload_Task/list",
    })


def batch_task_detail_api(request, uid):
    """GET /api/v1/batch-tasks/<uid>"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import detail as _detail
    request.GET = request.GET.copy()
    request.GET["uid"] = str(uid)
    return _detail(request)


def batch_task_status_api(request, uid):
    """GET /api/v1/batch-tasks/<uid>/status"""
    obj = models.batch_EXPTask.objects.filter(id=uid).values(
        "status", "process", "pause_requested", "queued", "startTime",
    ).first()
    if not obj:
        return JsonResponse({"status": False, "error": "not found"}, status=404)

    status_str, _, _ = _status_label(_FauxObj(obj))

    return JsonResponse({
        "status": True,
        "data": {
            "process": obj["process"] or "0%",
            "status": status_str,
            "pause_requested": bool(obj["pause_requested"]),
        },
    })


class _FauxObj:
    """把 values() 返回的 dict 包装成可属性访问的对象，供 _status_label 复用。"""
    def __init__(self, d):
        self.__dict__.update(d)

def batch_task_status_batch_api(request):
    """GET /api/v1/batch-tasks/status-batch?ids=1,2,3"""
    ids_str = request.GET.get("ids", "")
    if not ids_str:
        return JsonResponse({"status": True, "data": {}})
    ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
    if not ids:
        return JsonResponse({"status": True, "data": {}})
    objs = models.batch_EXPTask.objects.filter(id__in=ids).values(
        "id", "status", "process", "pause_requested", "queued", "startTime",
    )
    result = {}
    for obj in objs:
        status_str, _, _ = _status_label(_FauxObj(obj))
        result[obj["id"]] = {
            "process": obj["process"] or "0%",
            "status": status_str,
            "pause_requested": bool(obj["pause_requested"]),
            "queued": bool(obj["queued"]),
        }
    return JsonResponse({"status": True, "data": result})


def batch_task_choices_api(request):
    """GET /api/v1/batch-tasks/choices"""
    proxy_choices = [
        {"value": p.id, "label": f"{p.get_proxy_type_display()} | {p.proxy_address}:{p.proxy_port}"}
        for p in models.ProxySetting.objects.all().order_by("id")
    ]
    proxy_choices.insert(0, {"value": "", "label": "不选择代理"})

    plugins = [
        {"value": p["id"], "label": f"[{p['id']}] {p['title']}"}
        for p in models.EXP.objects.all().order_by("id").values("id", "title")
    ]
    all_tags = [
        {"value": t["id"], "label": t["name"]}
        for t in models.Tag.objects.all().order_by("name").values("id", "name")
    ]

    return JsonResponse({
        "status": True,
        "proxy_choices": proxy_choices,
        "engine_proxy_choices": list(proxy_choices),
        "plugins": plugins,
        "severity_choices": [{"value": v, "label": l} for v, l in models.EXP.severity_choices],
        "tag_choices": all_tags,
        "task_type_choices": [{"value": v, "label": l} for v, l in models.batch_EXPTask.task_type_choices],
        "input_type_choices": [
            {"value": 1, "label": "从文件上传"},
            {"value": 2, "label": "历史漏洞资产"},
            {"value": 3, "label": "历史上传文件"},
            {"value": 4, "label": "空间测绘引擎"},
            {"value": 5, "label": "历史测绘结果"},
            {"value": 6, "label": "从检索语句导入"},
        ],
        "engine_type_choices": [
            {"value": "fofa", "label": "fofa"}, {"value": "zoomeye", "label": "zoomeye"},
            {"value": "quake", "label": "quake"}, {"value": "hunter", "label": "hunter"},
            {"value": "shodan", "label": "shodan"},
        ],
        "engine_proxy_mode_choices": [
            {"value": 0, "label": "跟随引擎配置"},
            {"value": 1, "label": "不使用代理"}, {"value": 2, "label": "强制代理"},
        ],
        "run_mode_choices": [
            {"value": 1, "label": "多线程"}, {"value": 2, "label": "协程"},
        ],
    })


def batch_task_plugins_api(request):
    """GET /api/v1/batch-tasks/plugins"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import get_all_plugin
    return get_all_plugin(request)


def batch_task_exp_detail_api(request, uid):
    """GET /api/v1/batch-tasks/<uid>/exp-detail"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import exp_detail
    request.GET = request.GET.copy()
    request.GET["uid"] = str(uid)
    return exp_detail(request)


@deny_user
def batch_task_create_api(request):
    """POST /api/v1/batch-tasks/create"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import add
    if hasattr(request.POST, '_mutable'):
        request.POST._mutable = True
    return add(request)


@deny_user
def batch_task_update_api(request, uid):
    """POST /api/v1/batch-tasks/<uid>/update"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import edit
    request.GET = request.GET.copy()
    request.GET['uid'] = str(uid)
    if hasattr(request.POST, '_mutable'):
        request.POST._mutable = True
    return edit(request)


@deny_user
def batch_task_operate_api(request, uid):
    """POST /api/v1/batch-tasks/<uid>/operate"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import operate
    mutable_post = request.POST.copy() if hasattr(request.POST, 'copy') else request.POST
    if not hasattr(mutable_post, '_mutable'):
        mutable_post._mutable = True
    mutable_post['uid'] = str(uid)
    request.POST = mutable_post
    return operate(request)


@deny_user
def batch_task_delete_api(request, uid):
    """POST /api/v1/batch-tasks/<uid>/delete"""
    from app_cybersparker.views.expload.task_manage.batch_exp_task import delete as _delete
    request.method = 'GET'
    request.GET = request.GET.copy()
    request.GET['uid'] = str(uid)
    return _delete(request)


@deny_user
def batch_task_batch_delete_api(request):
    """POST /api/v1/batch-tasks/batch-delete  body: {"uids": [1,2,3]}"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    from app_cybersparker.views.expload.task_manage.batch_exp_task import delete
    for uid in uids:
        try:
            request.GET = request.GET.copy(); request.GET['uid'] = str(uid)
            delete(request)
        except Exception:
            pass
    return JsonResponse({"status": True})


def batch_task_history_files_api(request):
    """GET /api/v1/batch-tasks/history-files"""
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
