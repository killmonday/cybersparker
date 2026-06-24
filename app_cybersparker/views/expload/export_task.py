import os

from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, QueryDict

from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from app_cybersparker.permissions import deny_user


def export_task_list(request):
    tasks = models.ExportTask.objects.all().order_by("-creatime")
    return render(request, "project/expload/export_task_list.html", {"tasks": tasks})


ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def export_task_list_api(request):
    try:
        page = int(request.GET.get("page", "1"))
    except Exception:
        page = 1
    try:
        rows = int(request.GET.get("rows_per_page", "13"))
    except Exception:
        rows = 13
    if rows not in ROWS_PER_PAGE_WHITELIST:
        rows = 13

    queryset = models.ExportTask.objects.all().order_by("-creatime")
    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PR:
        GET = qd
    po = Pagination(_PR(), queryset)

    items = []
    for obj in po.page_queryset:
        status_labels = {"processing": "处理中", "completed": "已完成", "failed": "失败"}
        type_labels = {"global": "全局检索", "task": "任务检索"}
        items.append({
            "id": obj.id,
            "task_type": obj.task_type,
            "task_type_label": type_labels.get(obj.task_type, obj.task_type),
            "task_name": obj.task_name,
            "status": obj.status,
            "status_label": status_labels.get(obj.status, obj.status),
            "total_rows": obj.total_rows,
            "creatime": obj.creatime.strftime("%Y-%m-%d %H:%M") if obj.creatime else "",
            "download_url": f"/api/v1/export-tasks/{obj.id}/download" if obj.status == "completed" and obj.csv_file else "",
        })

    return JsonResponse({
        "items": items,
        "page": po.page,
        "rows_per_page": po.page_size,
        "total": po.total_count,
        "total_pages": po.total_page_count,
        "legacy_list_url": "/export/tasks",
    })


@deny_user
def export_task_batch_delete_api(request):
    """POST /api/v1/export-tasks/batch-delete  body: {"uids": [1,2,3]}"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.ExportTask.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


def export_task_download(request, task_id):
    task = models.ExportTask.objects.filter(id=task_id).first()
    if not task or task.status != "completed" or not task.csv_file:
        return HttpResponse("文件不存在或导出未完成", status=404)

    csv_path = task.csv_file.lstrip("/")
    # csv_file 存的是 /static/exports/xxx.csv，STATIC_ROOT 即项目 static/ 目录
    filepath = os.path.join(settings.STATIC_ROOT, csv_path.replace("static/", "", 1))
    if not os.path.isfile(filepath):
        return HttpResponse("文件已不存在", status=404)

    with open(filepath, "rb") as f:
        content = f.read()

    filename = os.path.basename(filepath)
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
