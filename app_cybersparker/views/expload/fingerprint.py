from datetime import datetime
import json
import os
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q, Count

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from app_cybersparker.permissions import deny_user
from django.http import JsonResponse
import cybersparker.settings as sett


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
        model = models.fingerPrint
        exclude = ["create_time"]



def _get_api_payload(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None
    return request.POST


def _form_errors(form):
    return {name: errors[0] for name, errors in form.errors.items()}

@deny_user
def list(request):

    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.fingerPrint.objects.filter(Q(product__icontains=search_data) | Q(condition__icontains=search_data))
    else:
        queryset = models.fingerPrint.objects.all().order_by("-id")
    form = ModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data
    }
    return render(request, 'project/expload/fingerPrint_list.html', context)


@deny_user
def list_api(request):
    search_data = request.GET.get('q', '')
    queryset = models.fingerPrint.objects.annotate(
        exp_count=Count('exp_relate_fingerprint')
    ).all().order_by('-id')
    if search_data:
        queryset = queryset.filter(Q(product__icontains=search_data) | Q(condition__icontains=search_data))
    page_object = Pagination(request, queryset)

    items = []
    for obj in page_object.page_queryset:
        items.append(
            {
                'id': obj.id,
                'product': obj.product,
                'condition': obj.condition,
                'created_at': obj.create_time.strftime('%Y-%m-%d %H:%M'),
                'exp_count': obj.exp_count,
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
            'legacy_list_url': '/fingerprint_List',
        }
    )


@deny_user
def add(request):
    try:
        form = ModelForm(data=request.POST)
        if form.is_valid():
            form.save()
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
        row_object = models.fingerPrint.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
        form = ModelForm(data=request.POST,instance=row_object)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "fingerprint_edit error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str) 
        return JsonResponse({"status": False, "tips": "fingerprint_edit error"})

@deny_user
def delete(request):
    uid = request.GET.get("uid")
    data = models.fingerPrint.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
    models.fingerPrint.objects.filter(id=uid).delete()
    return JsonResponse({"status": True})

@deny_user
def detail(request):
    uid = request.GET.get("uid")
    row_object = models.fingerPrint.objects.filter(id=uid).values("product","condition").first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
    return JsonResponse({"status": True, 'data': row_object})



@deny_user
def detail_api(request, uid):
    row_object = models.fingerPrint.objects.filter(id=uid).values("id", "product", "condition").first()
    if not row_object:
        return JsonResponse({"status": False, "error": "fingerprint not found"}, status=404)
    return JsonResponse({"status": True, "data": row_object})


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
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def update_api(request, uid):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    row_object = models.fingerPrint.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "fingerprint not found"}, status=404)
    payload = _get_api_payload(request)
    if payload is None:
        return JsonResponse({"status": False, "error": "invalid json"}, status=400)
    form = ModelForm(data=payload, instance=row_object)
    if form.is_valid():
        row_object = form.save()
        return JsonResponse({"status": True, "data": {"id": row_object.id}})
    return JsonResponse({"status": False, "errors": _form_errors(form)}, status=400)


@deny_user
def fingerprint_batch_delete_api(request):
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.fingerPrint.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


# ======================== 指纹-插件关联 API ========================

@deny_user
def fingerprint_plugins_api(request, uid):
    """GET/POST /api/v1/fingerprints/<id>/plugins"""
    fp = models.fingerPrint.objects.filter(id=uid).first()
    if not fp:
        return JsonResponse({"status": False, "error": "fingerprint not found"}, status=404)

    if request.method == 'POST':
        payload = _get_api_payload(request)
        if payload is None:
            return JsonResponse({"status": False, "error": "invalid json"}, status=400)
        exp_id = payload.get('exp_id')
        if not exp_id:
            return JsonResponse({"status": False, "error": "exp_id is required"}, status=400)
        exp = models.EXP.objects.filter(id=int(exp_id)).first()
        if not exp:
            return JsonResponse({"status": False, "error": "plugin not found"}, status=404)
        models.exp_relate_fingerprint.objects.get_or_create(
            EXP_id=exp, fingerprint_id=fp
        )
        return JsonResponse({"status": True})

    # GET — 查询关联插件列表（分页）
    search = request.GET.get('q', '')
    queryset = models.EXP.objects.filter(
        exp_relate_fingerprint__fingerprint_id=fp
    ).order_by('-id')
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) | Q(CVE__icontains=search)
        )
    page_object = Pagination(request, queryset)
    items = []
    for exp in page_object.page_queryset:
        items.append({
            'id': exp.id,
            'title': exp.title,
            'CVE': exp.CVE or '',
            'type_label': exp.get_Type_display(),
            'severity_label': exp.get_severity_display() if exp.severity else '',
        })
    return JsonResponse({
        'status': True,
        'items': items,
        'page': page_object.page,
        'rows_per_page': page_object.page_size,
        'total': page_object.total_count,
        'total_pages': page_object.total_page_count,
        'filters': {'q': search},
    })


@deny_user
def fingerprint_delete_plugin_api(request, uid, exp_id):
    """DELETE /api/v1/fingerprints/<id>/plugins/<exp_id> — 删除一条关联"""
    if request.method != 'DELETE':
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)
    fp = models.fingerPrint.objects.filter(id=uid).first()
    if not fp:
        return JsonResponse({"status": False, "error": "fingerprint not found"}, status=404)
    deleted, _ = models.exp_relate_fingerprint.objects.filter(
        fingerprint_id=fp, EXP_id_id=int(exp_id)
    ).delete()
    if not deleted:
        return JsonResponse({"status": False, "error": "association not found"}, status=404)
    return JsonResponse({"status": True})
