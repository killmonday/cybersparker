from datetime import datetime
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone

from app_cybersparker import models
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from app_cybersparker.utils.pagination import Pagination
from app_cybersparker.permissions import deny_user


class ModelForm(BootStrapModelForm):
    class Meta:
        model = models.CyberspaceEngineSetting
        exclude = ["update_time"]


ENGINE_TYPE_CHOICES = [
    {"value": value, "label": label}
    for value, label in models.CyberspaceEngineSetting.engine_type_choices
]

# 各引擎默认配置：api 地址、是否需要邮箱
ENGINE_DEFAULTS = {
    "fofa": {"api_base_url": "https://fofa.info", "needs_email": True},
    "quake": {"api_base_url": "https://quake.360.net", "needs_email": True},
    "shodan": {"api_base_url": "https://api.shodan.io", "needs_email": True},
    "zoomeye": {"api_base_url": "https://api.zoomeye.org", "needs_email": False},
    "hunter": {"api_base_url": "https://hunter.qianxin.com/openApi/search", "needs_email": False},
}


def _get_api_payload(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None
    return request.POST


def _form_errors(form):
    return {name: errors[0] for name, errors in form.errors.items()}


def list(request):
    search_data = request.GET.get("q", "")
    if search_data:
        queryset = models.CyberspaceEngineSetting.objects.filter(
            Q(engine_type__icontains=search_data) |
            Q(api_base_url__icontains=search_data) |
            Q(account_email__icontains=search_data)
        ).order_by("engine_type")
    else:
        queryset = models.CyberspaceEngineSetting.objects.all().order_by("engine_type")

    form = ModelForm()
    page_object = Pagination(request, queryset)
    context = {
        "form": form,
        "queryset": page_object.page_queryset,
        "page_string": page_object.html(),
        "search_data": search_data,
    }
    return render(request, "project/expload/cyberspace_engine_setting.html", context)


def list_api(request):
    search_data = request.GET.get('q', '')
    queryset = models.CyberspaceEngineSetting.objects.select_related('proxy').all().order_by('engine_type')
    if search_data:
        queryset = queryset.filter(
            Q(engine_type__icontains=search_data)
            | Q(api_base_url__icontains=search_data)
            | Q(account_email__icontains=search_data)
        )
    page_object = Pagination(request, queryset)

    items = []
    for obj in page_object.page_queryset:
        items.append(
            {
                'id': obj.id,
                'engine_type': obj.engine_type,
                'api_base_url': obj.api_base_url,
                'account_email': obj.account_email or '',
                'use_proxy': obj.use_proxy,
                'proxy_label': str(obj.proxy) if obj.proxy else '',
                'remark': obj.remark or '',
            }
        )

    return JsonResponse(
        {
            'items': items,
            'page': page_object.page,
            'rows_per_page': page_object.page_size,
            'total': page_object.total_count,
            'total_pages': page_object.total_page_count,
            'filters': {'q': search_data},
            'engine_type_choices': ENGINE_TYPE_CHOICES,
            'engine_defaults': ENGINE_DEFAULTS,
            'proxy_choices': [
                {"value": proxy.id, "label": str(proxy)}
                for proxy in models.ProxySetting.objects.all().order_by('id')
            ],
            'legacy_list_url': '/cyberspace_engine_setting',
        }
    )


@deny_user
def add(request):
    form = ModelForm(data=request.POST)
    if form.is_valid():
        form.instance.update_time = timezone.now()
        form.save()
        return JsonResponse({"status": True})
    return JsonResponse({"status": False, "error": form.errors})


@deny_user
def edit(request):
    uid = request.GET.get("uid")
    row_object = models.CyberspaceEngineSetting.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, "tips": "The data does not exist. Please refresh and try again"})

    form = ModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.instance.update_time = timezone.now()
        form.save()
        return JsonResponse({"status": True})
    return JsonResponse({"status": False, "error": form.errors})


@deny_user
def delete(request):
    uid = request.GET.get("uid")
    data = models.CyberspaceEngineSetting.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
    data.delete()
    return JsonResponse({"status": True})


def detail(request):
    uid = request.GET.get("uid")
    row_object = models.CyberspaceEngineSetting.objects.filter(id=uid).values(
        "engine_type", "api_base_url", "account_email", "api_key", "use_proxy", "proxy", "remark"
    ).first()
    if not row_object:
        return JsonResponse({"status": False, "tips": "The data does not exist. Please refresh and try again"})
    return JsonResponse({"status": True, "data": row_object})



def detail_api(request, uid):
    row_object = models.CyberspaceEngineSetting.objects.filter(id=uid).values(
        "id", "engine_type", "api_base_url", "account_email", "api_key", "use_proxy", "proxy", "remark"
    ).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "engine not found"}, status=404)
    return JsonResponse(
        {
            "status": True,
            "data": row_object,
            "engine_type_choices": ENGINE_TYPE_CHOICES,
            "proxy_choices": [
                {"value": proxy.id, "label": str(proxy)}
                for proxy in models.ProxySetting.objects.all().order_by('id')
            ],
        }
    )


@deny_user
def create_api(request):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    payload = _get_api_payload(request)
    if payload is None:
        return JsonResponse({"status": False, "error": "invalid json"}, status=400)
    form = ModelForm(data=payload)
    if form.is_valid():
        row_object = form.save(commit=False)
        row_object.update_time = timezone.now()
        row_object.save()
        form.save_m2m()
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def update_api(request, uid):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    row_object = models.CyberspaceEngineSetting.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "engine not found"}, status=404)
    payload = _get_api_payload(request)
    if payload is None:
        return JsonResponse({"status": False, "error": "invalid json"}, status=400)
    form = ModelForm(data=payload, instance=row_object)
    if form.is_valid():
        row_object = form.save(commit=False)
        row_object.update_time = timezone.now()
        row_object.save()
        form.save_m2m()
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def engine_batch_delete_api(request):
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.CyberspaceEngineSetting.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})
