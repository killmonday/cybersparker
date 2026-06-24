"""fscanx 导入任务 — 列表 API + 服务详情查询 API"""
import json
from django.http import JsonResponse
from django.db.models import Count
from app_cybersparker import models
from app_cybersparker.permissions import deny_user


def _task_row(task):
    zone_name = task.zone.name if task.zone_id else ""
    return {
        "id": task.id,
        "task_name": task.task_name,
        "zone_id": task.zone_id,
        "zone_name": zone_name,
        "status": task.status,
        "process": task.process or "0%",
        "creat_time": task.creat_time.strftime("%Y-%m-%d %H:%M") if task.creat_time else None,
        "startTime": task.startTime.strftime("%Y-%m-%d %H:%M") if task.startTime else None,
        "endTime": task.endTime.strftime("%Y-%m-%d %H:%M") if task.endTime else None,
        "conflict_strategy": task.conflict_strategy,
        "failed": task.failed,
        "last_error": task.last_error or "",
    }


def fscanx_task_list_api(request):
    """GET /api/v1/fscanx-tasks — fscanx 导入任务列表"""
    page = int(request.GET.get("page", 1))
    rows_per_page = int(request.GET.get("rows_per_page", 15))
    q = request.GET.get("q", "").strip()

    qs = models.auto_scan_tasks.objects.filter(input_type=2).order_by("-id")
    if q:
        qs = qs.filter(task_name__icontains=q)

    total = qs.count()
    total_pages = max(1, (total + rows_per_page - 1) // rows_per_page)
    offset = (page - 1) * rows_per_page
    tasks = qs[offset:offset + rows_per_page]

    task_ids = [t.id for t in tasks]
    # 批量查计数，避免每行单独查
    detail_counts = {}
    asset_counts = {}
    if task_ids:
        detail_counts = dict(
            models.fscanx_service_detail.objects
            .filter(task_id__in=task_ids)
            .values("task_id")
            .annotate(cnt=Count("id"))
            .values_list("task_id", "cnt")
        )
        asset_counts = dict(
            models.AssetTaskRelation.objects
            .filter(task_id__in=task_ids)
            .values("task_id")
            .annotate(cnt=Count("id"))
            .values_list("task_id", "cnt")
        )
    rows = []
    for t in tasks:
        row = _task_row(t)
        row["asset_count"] = asset_counts.get(t.id, 0)
        row["detail_count"] = detail_counts.get(t.id, 0)
        rows.append(row)

    return JsonResponse({
        "status": True,
        "rows": rows,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "rows_per_page": rows_per_page,
    })


def fscanx_task_detail_api(request, task_id):
    """GET /api/v1/fscanx-tasks/<id>/details — 服务详情列表"""
    page = int(request.GET.get("page", 1))
    rows_per_page = int(request.GET.get("rows_per_page", 20))
    result_type = request.GET.get("result_type", "")

    task = models.auto_scan_tasks.objects.filter(id=task_id, input_type=2).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    qs = models.fscanx_service_detail.objects.filter(task=task).order_by("id")
    if result_type:
        try:
            qs = qs.filter(result_type=int(result_type))
        except ValueError:
            pass

    total = qs.count()
    total_pages = max(1, (total + rows_per_page - 1) // rows_per_page)
    offset = (page - 1) * rows_per_page

    rows = []
    for d in qs[offset:offset + rows_per_page]:
        # 结果摘要：截断超长内容
        detail_preview = (d.result or "")[:200]
        rows.append({
            "id": d.id,
            "protocol": d.protocol,
            "host": d.host,
            "port": d.port,
            "result_type": d.result_type,
            "result_type_label": d.get_result_type_display(),
            "result_preview": detail_preview,
            "result_full": d.result,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else None,
        })

    return JsonResponse({
        "status": True,
        "task": _task_row(task),
        "detail_count": models.fscanx_service_detail.objects.filter(task=task).count(),
        "rows": rows,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "rows_per_page": rows_per_page,
        "result_type_choices": [
            {"value": v, "label": l}
            for v, l in models.fscanx_service_detail.RESULT_TYPE_CHOICES
        ],
    })


@deny_user
def fscanx_task_delete_api(request, task_id):
    """POST /api/v1/fscanx-tasks/<id>/delete — 删除 fscanx 导入任务"""
    import os as _os
    from django.db import connection as db_conn

    task = models.auto_scan_tasks.objects.filter(id=task_id, input_type=2).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    try:
        # 停止信号 + 删除 fscanx 上传文件
        models.auto_scan_tasks.objects.filter(id=task.id).update(stop_requested=True)

        # 删除磁盘文件
        if task.fscanx_file:
            try:
                task.fscanx_file.delete(save=False)
            except Exception:
                pass

        # 清 AssetTaskRelation（复用现有级联逻辑）
        asset_ids = list(
            models.AssetTaskRelation.objects.filter(task_id=task.id)
            .values_list("identify_result_id", flat=True)
        )
        models.AssetTaskRelation.objects.filter(task_id=task.id).delete()

        # 删孤立资产（先批量查出仍有引用的资产，避免逐条 EXISTS）
        if asset_ids:
            still_referenced = set(
                models.AssetTaskRelation.objects.filter(
                    identify_result_id__in=asset_ids
                ).values_list("identify_result_id", flat=True).distinct()
            )
            orphan_ids = [aid for aid in asset_ids if aid not in still_referenced]
            if orphan_ids:
                models.auto_scan_indentify_result.objects.filter(id__in=orphan_ids).delete()

        # fscanx_service_detail 由 FK CASCADE 自动删
        task.delete()

        db_conn.close()
        return JsonResponse({"status": True, "tips": "删除成功"})
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


@deny_user
def fscanx_detail_delete_api(request, detail_id):
    """POST /api/v1/fscanx-tasks/details/<id>/delete — 删除单条服务详情"""
    row = models.fscanx_service_detail.objects.filter(id=detail_id).first()
    if not row:
        return JsonResponse({"status": False, "error": "记录不存在"}, status=404)
    row.delete()
    return JsonResponse({"status": True, "tips": "删除成功"})
