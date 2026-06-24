"""扫描区域 (AssetZone) CRUD API"""
import json
from django.db.models import Count, ProtectedError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from app_cybersparker import models
from app_cybersparker.models import AssetZone


def _count_by_zone(queryset, zone_ids):
    """按 zone_id 分组计数，返回 {zone_id: count}。"""
    rows = (
        queryset.filter(zone_id__in=zone_ids)
        .values("zone_id")
        .annotate(cnt=Count("id"))
        .values_list("zone_id", "cnt")
    )
    return dict(rows)


@require_http_methods(["GET"])
def zone_list_api(request):
    """GET /api/v1/zones — 返回全部区域。?counts=1 时附带各表计数。"""
    qs = AssetZone.objects.order_by("created_at")
    with_counts = request.GET.get("counts") == "1"

    if with_counts:
        zones = list(qs)
        if not zones:
            return JsonResponse({"zones": []})
        zone_ids = [z.id for z in zones]

        # 5 条独立 GROUP BY 查询，每条走 zone_id 索引，避免 JOIN 组合爆炸
        asset_counts = _count_by_zone(
            models.auto_scan_indentify_result.objects, zone_ids
        )
        auto_scan_counts = _count_by_zone(
            models.auto_scan_tasks.objects, zone_ids
        )
        batch_counts = _count_by_zone(
            models.batch_EXPTask.objects, zone_ids
        )
        dirscan_counts = _count_by_zone(
            models.DirScanTask.objects, zone_ids
        )
        dir_result_counts = _count_by_zone(
            models.auto_scan_directory_result.objects, zone_ids
        )

        return JsonResponse({
            "zones": [
                {
                    "id": z.id,
                    "code": z.code,
                    "name": z.name,
                    "description": z.description,
                    "is_system": z.is_system,
                    "created_at": z.created_at.isoformat(),
                    "asset_count": asset_counts.get(z.id, 0),
                    "auto_scan_task_count": auto_scan_counts.get(z.id, 0),
                    "batch_task_count": batch_counts.get(z.id, 0),
                    "dirscan_task_count": dirscan_counts.get(z.id, 0),
                    "directory_result_count": dir_result_counts.get(z.id, 0),
                }
                for z in zones
            ],
        })

    return JsonResponse({
        "zones": [
            {
                "id": z.id,
                "code": z.code,
                "name": z.name,
                "description": z.description,
                "is_system": z.is_system,
                "created_at": z.created_at.isoformat(),
                "asset_count": 0,
                "auto_scan_task_count": 0,
                "batch_task_count": 0,
                "dirscan_task_count": 0,
                "directory_result_count": 0,
            }
            for z in qs
        ],
    })


@require_http_methods(["POST"])
def zone_create_api(request):
    """POST /api/v1/zones/create — 新增区域"""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "请求体不是合法 JSON"}, status=400)

    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()

    if not code or not name:
        return JsonResponse({"error": "code 和 name 为必填"}, status=400)

    if AssetZone.objects.filter(code=code).exists():
        return JsonResponse({"error": f"编码 {code} 已存在"}, status=400)
    if AssetZone.objects.filter(name=name).exists():
        return JsonResponse({"error": f"名称 {name} 已存在"}, status=400)

    zone = AssetZone.objects.create(
        code=code, name=name, description=description,
    )
    return JsonResponse({"id": zone.id, "code": zone.code, "name": zone.name}, status=201)


@require_http_methods(["PUT"])
def zone_update_api(request, zone_id):
    """PUT /api/v1/zones/<id>/update — 改名/改备注"""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "请求体不是合法 JSON"}, status=400)

    try:
        zone = AssetZone.objects.get(id=zone_id)
    except AssetZone.DoesNotExist:
        return JsonResponse({"error": "区域不存在"}, status=404)

    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()

    if name and name != zone.name:
        if AssetZone.objects.filter(name=name).exists():
            return JsonResponse({"error": f"名称 {name} 已存在"}, status=400)
        zone.name = name
    if description:
        zone.description = description
    zone.save()
    return JsonResponse({"id": zone.id, "code": zone.code, "name": zone.name})


def _get_zone_ref_counts(zone):
    """返回五类引用计数"""
    return {
        "asset_count": zone.auto_scan_indentify_result_set.count(),
        "auto_scan_task_count": zone.auto_scan_tasks_set.count(),
        "batch_task_count": zone.batch_exptask_set.count(),
        "dirscan_task_count": zone.dirscantask_set.count(),
        "directory_result_count": zone.auto_scan_directory_result_set.count(),
    }


@require_http_methods(["DELETE"])
def zone_delete_api(request, zone_id):
    """DELETE /api/v1/zones/<id>/delete — 删除区域（有引用时拒绝）"""
    try:
        zone = AssetZone.objects.get(id=zone_id)
    except AssetZone.DoesNotExist:
        return JsonResponse({"error": "区域不存在"}, status=404)

    if zone.is_system:
        return JsonResponse({"error": "系统区域不能删除"}, status=400)

    refs = _get_zone_ref_counts(zone)
    total = sum(refs.values())
    if total > 0:
        return JsonResponse({
            "error": f"该区域下仍有 {total} 条引用，不能删除",
            "refs": refs,
        }, status=400)

    try:
        zone.delete()
    except ProtectedError:
        refs = _get_zone_ref_counts(zone)
        return JsonResponse({
            "error": f"该区域下仍有引用，不能删除",
            "refs": refs,
        }, status=400)

    return JsonResponse({"ok": True})
