from datetime import datetime
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django import forms as django_forms
from django.http import JsonResponse
import cybersparker.settings as sett
from app_cybersparker.permissions import deny_user

pwd = sett.THIS_DIR


def error_log(e_info, tips, time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open(error_log_path, "a+") as f:
            f.write(f"[expload {tips}] {time} : " + e_info + "\n")
    except:
        pass


# ======================== Dict Group ========================

class DictGroupForm(BootStrapModelForm):
    class Meta:
        model = models.DirScanDictGroup
        fields = ["name", "description"]


def dict_group_list(request):
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.DirScanDictGroup.objects.filter(
            Q(name__icontains=search_data) | Q(description__icontains=search_data)
        )
    else:
        queryset = models.DirScanDictGroup.objects.all().order_by("-id")
    form = DictGroupForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data
    }
    return render(request, 'project/expload/dict_group.html', context)


@deny_user
def dict_group_add(request):
    try:
        form = DictGroupForm(data=request.POST)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dict_group_add error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "add error"})


@deny_user
def dict_group_edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.DirScanDictGroup.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
        form = DictGroupForm(data=request.POST, instance=row_object)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dict_group_edit error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "edit error"})


@deny_user
def dict_group_delete(request):
    uid = request.GET.get("uid")
    data = models.DirScanDictGroup.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "删除失败，数据不存在。"})
    models.DirScanDictGroup.objects.filter(id=uid).delete()
    return JsonResponse({"status": True})


def dict_group_detail(request):
    uid = request.GET.get("uid")
    row_object = models.DirScanDictGroup.objects.filter(id=uid).values("name", "description").first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
    return JsonResponse({"status": True, 'data': row_object})


# ======================== Dict Group JSON API ========================

from django.http import QueryDict

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def _paginate(request, queryset):
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
    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PR:
        GET = qd
    return Pagination(_PR(), queryset)


def dict_group_list_api(request):
    q = request.GET.get("q", "")
    queryset = models.DirScanDictGroup.objects.all().order_by("-id")
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(description__icontains=q))
    po = _paginate(request, queryset)
    items = [{"id": o.id, "name": o.name, "description": o.description, "creatime": o.creatime.strftime("%Y-%m-%d %H:%M")} for o in po.page_queryset]
    return JsonResponse({
        "items": items, "page": po.page, "rows_per_page": po.page_size,
        "total": po.total_count, "total_pages": po.total_page_count,
        "filters": {"q": q}, "legacy_list_url": "/dict/group/list",
    })


@deny_user
def dict_group_create_api(request):
    try:
        form = DictGroupForm(data=request.POST)
        if form.is_valid():
            obj = form.save()
            return JsonResponse({"status": True, "data": {"id": obj.id, "name": obj.name, "description": obj.description}})
        return JsonResponse({"status": False, "errors": form.errors})
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


def dict_group_detail_api(request, uid):
    obj = models.DirScanDictGroup.objects.filter(id=uid).values("id", "name", "description").first()
    if not obj:
        return JsonResponse({"status": False, "error": "数据不存在"})
    return JsonResponse({"status": True, "data": obj})


@deny_user
def dict_group_update_api(request, uid):
    try:
        obj = models.DirScanDictGroup.objects.filter(id=uid).first()
        if not obj:
            return JsonResponse({"status": False, "error": "数据不存在"})
        form = DictGroupForm(data=request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "errors": form.errors})
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


@deny_user
def dict_group_delete_api(request, uid):
    row_object = models.DirScanDictGroup.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, "error": "not found"}, status=404)
    row_object.delete()
    return JsonResponse({"status": True})


@deny_user
def dict_group_batch_delete_api(request):
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.DirScanDictGroup.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


# ======================== Dict ========================

class DictForm(BootStrapModelForm):
    bootstrap_exclude_fields = ["groups"]

    groups = django_forms.ModelMultipleChoiceField(
        label="所属组",
        queryset=models.DirScanDictGroup.objects.all().order_by("name"),
        widget=django_forms.CheckboxSelectMultiple,
        required=False,
    )

    paths_text = django_forms.CharField(
        label="路径列表",
        widget=django_forms.Textarea(attrs={"rows": 15, "placeholder": "每行一条路径"}),
        required=False,
    )

    class Meta:
        model = models.DirScanDict
        fields = ["name", "groups"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["paths_text"].initial = "\n".join(self.instance.paths or [])

    def save(self, commit=True):
        instance = super().save(commit=False)
        paths_text = self.cleaned_data.get("paths_text", "")
        instance.paths = [p.strip() for p in paths_text.split("\n") if p.strip()]
        if commit:
            instance.save()
            self.save_m2m()
        return instance


def dict_list(request):
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.DirScanDict.objects.filter(name__icontains=search_data)
    else:
        queryset = models.DirScanDict.objects.all().order_by("-id")
    form = DictForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data
    }
    return render(request, 'project/expload/dict_list.html', context)


def dict_list_api(request):
    search_data = request.GET.get('q', '')
    queryset = models.DirScanDict.objects.prefetch_related('groups').all().order_by('-id')
    if search_data:
        queryset = queryset.filter(name__icontains=search_data)
    page_object = Pagination(request, queryset)

    items = []
    for obj in page_object.page_queryset:
        items.append(
            {
                'id': obj.id,
                'name': obj.name,
                'path_count': len(obj.paths or []),
                'groups': [group.name for group in obj.groups.all()],
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
            'legacy_list_url': '/dict/list',
        }
    )


@deny_user
def dict_add(request):
    try:
        form = DictForm(data=request.POST)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dict_add error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "add error"})


@deny_user
def dict_edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.DirScanDict.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
        form = DictForm(data=request.POST, instance=row_object)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dict_edit error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "edit error"})


@deny_user
def dict_delete(request):
    uid = request.GET.get("uid")
    data = models.DirScanDict.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "删除失败，数据不存在。"})
    models.DirScanDict.objects.filter(id=uid).delete()
    return JsonResponse({"status": True})


def dict_detail(request):
    uid = request.GET.get("uid")
    row_object = models.DirScanDict.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
    return JsonResponse({
        "status": True,
        'data': {
            "name": row_object.name,
            "paths_text": "\n".join(row_object.paths or []),
            "groups": [g.id for g in row_object.groups.all()],
        }
    })


@deny_user
def dict_batch_delete_api(request):
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.DirScanDict.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


@deny_user
def dict_create_api(request):
    try:
        form = DictForm(data=request.POST)
        if form.is_valid():
            obj = form.save()
            return JsonResponse({"status": True, "data": {"id": obj.id, "name": obj.name}})
        return JsonResponse({"status": False, "errors": form.errors})
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


def dict_detail_api(request, uid):
    obj = models.DirScanDict.objects.filter(id=uid).first()
    if not obj:
        return JsonResponse({"status": False, "error": "数据不存在"})
    return JsonResponse({
        "status": True,
        "data": {
            "id": obj.id,
            "name": obj.name,
            "paths_text": "\n".join(obj.paths or []),
            "groups": [g.id for g in obj.groups.all()],
        }
    })


@deny_user
def dict_update_api(request, uid):
    try:
        obj = models.DirScanDict.objects.filter(id=uid).first()
        if not obj:
            return JsonResponse({"status": False, "error": "数据不存在"})
        form = DictForm(data=request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "errors": form.errors})
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


@deny_user
def dict_delete_api(request, uid):
    obj = models.DirScanDict.objects.filter(id=uid).first()
    if not obj:
        return JsonResponse({"status": False, "error": "not found"}, status=404)
    obj.delete()
    return JsonResponse({"status": True})
