from datetime import datetime
import json
import os
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
import cybersparker.settings as sett
from app_cybersparker.services.request_runtime_config_service import refresh_conf_from_db
from app_cybersparker.permissions import deny_user


pwd = sett.THIS_DIR
def error_log(e_info,tips,time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open (error_log_path,"a+") as f:
            f.write(f"[expload {tips}] {time} : " +  e_info + "\n")
            f.close()
    except:
        pass

class ModelForm(BootStrapModelForm):
    class Meta:
        model = models.ProxySetting
        exclude = ["creatime",]


PROXY_TYPE_CHOICES = [
    {"value": value, "label": label}
    for value, label in models.ProxySetting.protocol_choices
]


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
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.ProxySetting.objects.filter(Q(proxy_address__icontains=search_data) | Q(proxy_port__icontains=search_data))
    else:
        queryset = models.ProxySetting.objects.all().order_by("-id")
    form = ModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data
    }
    return render(request, 'project/expload/proxy_setting.html', context)


def list_api(request):
    search_data = request.GET.get('q', '')
    queryset = models.ProxySetting.objects.all().order_by('-id')
    if search_data:
        queryset = queryset.filter(
            Q(proxy_address__icontains=search_data) | Q(proxy_port__icontains=search_data)
        )
    page_object = Pagination(request, queryset)

    items = []
    for obj in page_object.page_queryset:
        items.append(
            {
                'id': obj.id,
                'proxy_type_label': obj.get_proxy_type_display(),
                'proxy_address': obj.proxy_address,
                'proxy_port': obj.proxy_port,
                'created_at': obj.creatime.strftime('%Y-%m-%d %H:%M'),
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
            'proxy_type_choices': PROXY_TYPE_CHOICES,
            'legacy_list_url': '/proxy_setting',
        }
    )


@deny_user
def add(request):
    try:
        form = ModelForm(data=request.POST)
        if form.is_valid():
            form.save()
            refresh_conf_from_db()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "plugin add error"})

@deny_user
def edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.ProxySetting.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
        form = ModelForm(data=request.POST,instance=row_object)
        if form.is_valid():
            form.save()
            refresh_conf_from_db()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "ProxySetting_edit error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "ProxySetting_edit error"})

@deny_user
def delete(request):
    uid = request.GET.get("uid")
    data = models.ProxySetting.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
    models.ProxySetting.objects.filter(id=uid).delete()
    refresh_conf_from_db()
    return JsonResponse({"status": True})

def detail(request):
    uid = request.GET.get("uid")
    row_object = models.ProxySetting.objects.filter(id=uid).values("proxy_type","proxy_address","proxy_port").first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
    return JsonResponse({"status": True, 'data': row_object})



def detail_api(request, uid):
    row_object = models.ProxySetting.objects.filter(id=uid).values(
        "id", "proxy_type", "proxy_address", "proxy_port", "remark"
    ).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "proxy not found"}, status=404)
    return JsonResponse({"status": True, "data": row_object, "proxy_type_choices": PROXY_TYPE_CHOICES})


@deny_user
def create_api(request):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    payload = _get_api_payload(request)
    if payload is None:
        return JsonResponse({"status": False, "error": "invalid json"}, status=400)
    form = ModelForm(data=payload)
    if form.is_valid():
        row_object = form.save()
        refresh_conf_from_db()
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def update_api(request, uid):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    row_object = models.ProxySetting.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "proxy not found"}, status=404)
    payload = _get_api_payload(request)
    if payload is None:
        return JsonResponse({"status": False, "error": "invalid json"}, status=400)
    form = ModelForm(data=payload, instance=row_object)
    if form.is_valid():
        row_object = form.save()
        refresh_conf_from_db()
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def proxy_batch_delete_api(request):
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.ProxySetting.objects.filter(id__in=uids).delete()
    refresh_conf_from_db()
    return JsonResponse({"status": True})
