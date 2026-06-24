from app_cybersparker import models
from django.http import JsonResponse
import json


def _mask_api_key(key: str) -> str:
    if len(key) <= 8:
        return key[:2] + "****" + key[-2:]
    return key[:4] + "****" + key[-4:]


def _validate_form(body: dict, is_edit: bool) -> tuple[dict, dict]:
    """返回 (cleaned_data, errors)"""
    data = {
        "name": body.get("name", "").strip(),
        "model_id": body.get("model_id", "").strip(),
        "api_url": body.get("api_url", "").strip(),
        "api_key": body.get("api_key", "").strip(),
        "model_type": body.get("model_type", "").strip(),
    }
    errors = {}
    if not data["name"]:
        errors["name"] = "名称不能为空"
    if not data["model_id"]:
        errors["model_id"] = "模型 ID 不能为空"
    if not data["api_url"]:
        errors["api_url"] = "API 地址不能为空"
    if not is_edit and not data["api_key"]:
        errors["api_key"] = "API Key 不能为空"
    if data["model_type"] not in ("thinking", "vision"):
        errors["model_type"] = "模型类型必须为 thinking 或 vision"
    return data, errors


def api_configs(request):
    """GET /api/v1/ai-model-configs — 列表"""
    if request.method == "GET":
        model_type = request.GET.get("model_type", "")
        queryset = models.AIModelConfig.objects.all().order_by("-created_at")
        if model_type in ("thinking", "vision"):
            queryset = queryset.filter(model_type=model_type)

        items = []
        for obj in queryset:
            items.append({
                "id": obj.id,
                "name": obj.name,
                "model_id": obj.model_id,
                "api_url": obj.api_url,
                "api_key": _mask_api_key(obj.api_key),
                "model_type": obj.model_type,
                "model_type_label": obj.get_model_type_display(),
                "created_at": obj.created_at.strftime("%Y-%m-%d %H:%M"),
            })

        return JsonResponse({
            "status": True,
            "items": items,
            "model_type_choices": [
                {"value": value, "label": label}
                for value, label in models.AIModelConfig.MODEL_TYPE_CHOICES
            ],
        })

    # POST /api/v1/ai-model-configs — 新增
    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        data, errors = _validate_form(body, is_edit=False)
        if errors:
            return JsonResponse({"status": False, "errors": errors}, status=400)
        obj = models.AIModelConfig.objects.create(**data)
        return JsonResponse({"status": True, "data": {"id": obj.id}})

    return JsonResponse({"status": False, "error": "method not allowed"}, status=405)


def api_config_detail(request, uid):
    """GET/POST/DELETE /api/v1/ai-model-configs/<id>"""
    obj = models.AIModelConfig.objects.filter(id=uid).first()
    if not obj:
        return JsonResponse({"status": False, "error": "配置不存在"}, status=404)

    # GET — 详情
    if request.method == "GET":
        return JsonResponse({
            "status": True,
            "data": {
                "id": obj.id,
                "name": obj.name,
                "model_id": obj.model_id,
                "api_url": obj.api_url,
                "api_key": _mask_api_key(obj.api_key),
                "model_type": obj.model_type,
                "model_type_label": obj.get_model_type_display(),
                "created_at": obj.created_at.strftime("%Y-%m-%d %H:%M"),
            },
        })

    # POST — 编辑
    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        data, errors = _validate_form(body, is_edit=True)
        if errors:
            return JsonResponse({"status": False, "errors": errors}, status=400)
        for field in ("name", "model_id", "api_url", "model_type"):
            setattr(obj, field, data[field])
        if data["api_key"]:
            obj.api_key = data["api_key"]
        obj.save()
        return JsonResponse({"status": True, "data": {"id": obj.id}})

    # DELETE — 删除
    if request.method == "DELETE":
        obj.delete()
        return JsonResponse({"status": True})

    return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
