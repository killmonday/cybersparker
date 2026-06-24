from datetime import datetime
import os
import re
import traceback
from django import forms
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.permissions import deny_user
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
import cybersparker.settings as sett
from django.utils import timezone

pwd = sett.THIS_DIR
ExtensionsType = [
        (1, "Verify"),
        (2, "Command Execute"),
        (3, "Code Execute"),
        (4, "File Reading"),
        (5, "Attact"),
    ]

def error_log(e_info,tips,time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open (error_log_path,"a+") as f:
            f.write(f"[expload {tips}] {time} : " +  e_info + "\n")
            f.close()
    except:
        pass

class ExploadModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['poc', 'tags']
    tags = forms.ModelMultipleChoiceField(
        queryset=models.Tag.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="标签",
    )
    class Meta:
        model = models.EXP
        exclude = ["creat_time","use","time","poc_content","poc_type","update_time"]

@deny_user
def expload_list(request):
    search_data = request.GET.get('q', "")
    severity_filter = request.GET.get('severity', "")
    tag_search = request.GET.get('tag', "")
    queryset = models.EXP.objects.prefetch_related('tags').all()
    if search_data:
        queryset = queryset.filter(Q(title__icontains=search_data) | Q(CVE__icontains=search_data))
    if severity_filter:
        queryset = queryset.filter(severity=severity_filter)
    if tag_search:
        queryset = queryset.filter(tags__name__icontains=tag_search)
    queryset = queryset.order_by("-id")
    form = ExploadModelForm()
    page_object = Pagination(request, queryset)
    product_data = models.fingerPrint.objects.values('id', 'product')
    product_names = ["[" + str(item['id'])+ "]" + item['product'] for item in product_data]

    # 预加载 tags 以减少 N+1
    all_tags = models.Tag.objects.all()
    tag_choices = [(t.id, t.name) for t in all_tags]
    severity_choices = models.EXP.severity_choices

    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data,
        "product_names":product_names,
        "ExtensionsType":ExtensionsType,
        "severity_choices": severity_choices,
        "tag_choices": tag_choices,
        "severity_filter": severity_filter,
        "tag_search": tag_search,
    }
    return render(request, 'project/expload/exp_list.html', context)


@deny_user
def expload_list_api(request):
    search_data = request.GET.get('q', '')
    severity_filter = request.GET.get('severity', '')
    tag_search = request.GET.get('tag', '')
    queryset = models.EXP.objects.prefetch_related('tags').all()
    if search_data:
        queryset = queryset.filter(Q(title__icontains=search_data) | Q(CVE__icontains=search_data))
    if severity_filter:
        queryset = queryset.filter(severity=severity_filter)
    if tag_search:
        queryset = queryset.filter(tags__name__icontains=tag_search)
    queryset = queryset.order_by('-id')
    page_object = Pagination(request, queryset)

    items = []
    for obj in page_object.page_queryset:
        items.append(
            {
                'id': obj.id,
                'title': obj.title,
                'CVE': obj.CVE,
                'severity': obj.severity,
                'severity_label': obj.get_severity_display() if obj.severity else '未设置',
                'plugin_language': obj.plugin_language,
                'plugin_language_label': obj.get_plugin_language_display(),
                'use': obj.use,
                'use_label': obj.get_use_display(),
                'type_label': obj.get_Type_display(),
                'tags': [tag.name for tag in obj.tags.all()],
                'detail_url': f'/expload/{obj.id}/detail',
            }
        )

    severity_choices = [
        {'value': value, 'label': label}
        for value, label in models.EXP.severity_choices
    ]
    return JsonResponse(
        {
            'items': items,
            'page': page_object.page,
            'rows_per_page': page_object.page_size,
            'total': page_object.total_count,
            'total_pages': page_object.total_page_count,
            'filters': {
                'q': search_data,
                'severity': severity_filter,
                'tag': tag_search,
            },
            'severity_choices': severity_choices,
            'legacy_list_url': '/expload/list',
        }
    )

@deny_user
def expload_detail(request,uid):
    if request.method == "GET":
        row_object = models.EXP.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
        file_path = str(row_object.poc)
        with open (file_path,"r",encoding="UTF8") as f:
            poc_content = f.read()
        context = {
            "data":row_object,
            "poc_content":poc_content,
        }
        return render(request,"project/expload/exp_detail.html",context)

@deny_user
def expload_detail_api(request, uid):
    row = models.EXP.objects.filter(id=uid).first()
    if not row:
        return JsonResponse({"status": False, "error": "Plugin not found"}, status=404)
    try:
        file_path = str(row.poc)
        with open(file_path, "r", encoding="UTF8") as f:
            poc_content = f.read()
    except Exception:
        poc_content = ""
    return JsonResponse({
        "status": True,
        "data": {
            "id": row.id,
            "title": row.title,
            "CVE": row.CVE,
            "type": row.Type,
            "type_label": row.get_Type_display(),
            "plugin_language": row.plugin_language,
            "plugin_language_label": row.get_plugin_language_display(),
            "severity": row.severity,
            "severity_label": row.get_severity_display() if row.severity else "",
            "use": row.use,
            "use_label": row.get_use_display(),
            "time": row.time.strftime("%Y-%m-%d") if row.time else "",
            "creat_time": row.creat_time.strftime("%Y-%m-%d") if row.creat_time else "",
            "update_time": row.update_time.strftime("%Y-%m-%d") if row.update_time else "",
            "tags": [t.name for t in row.tags.all()],
            "poc_content": poc_content,
        },
    })

def re_get_id_product(str):
    # 定义正则表达式模式
    pattern = re.compile(r'\[(\d+)\](.*)')
    # 使用正则表达式匹配字符串
    match = pattern.match(str)
    if match:
        # 获取方括号中的数字和方括号后的字符串
        number = match.group(1)
        rest_of_string = match.group(2)
        return number, rest_of_string
    else:
        return None, None  

@deny_user
def expload_add(request):
    try:
        form = ExploadModelForm(data=request.POST,files=request.FILES)
        affected_product = request.POST.get('affected_product')
        extentions = request.POST.get('extentions')
        if form.is_valid():
            upload_file = request.FILES.get("poc")
            if upload_file:
                ext = os.path.splitext(upload_file.name)[1].lower()
                plugin_language = int(form.instance.plugin_language or 1)
                if plugin_language == 1 and ext != ".py":
                    return JsonResponse({"status": False, "error": {"poc": ["python3 plugin requires .py file"]}})
                if plugin_language == 2 and ext not in (".yaml", ".yml"):
                    return JsonResponse({"status": False, "error": {"poc": ["nuclei_yaml plugin requires .yaml/.yml file"]}})
            ctime_str = request.POST.get('ctime')
            if ctime_str:
                try:
                    form.instance.time = datetime.strptime(ctime_str, '%m/%d/%Y').date()
                except:
                    try:
                        form.instance.time = datetime.strptime(ctime_str, '%Y/%m/%d').date()
                    except:
                        return JsonResponse({"status": False, "tips": "please choose the Exposure time"})
                form.instance.update_time = timezone.now()
                # form.instance.poc_type = "1"
                saved_object = form.save()
                if extentions:
                    extentions = extentions.split(",")
                    for extention in extentions:
                        try:
                            models.cveExtensions.objects.create(
                                CVE = saved_object,
                                function = int(extention)
                            )
                        except Exception as e:
                            print(e)
                if affected_product:
                    product_list =  str(affected_product).split(",")
                    for id_product in product_list:
                        id,product = re_get_id_product(id_product)
                        fingerprint_instance = models.fingerPrint.objects.get(id=id)
                        if fingerprint_instance:
                            try:
                                models.exp_relate_fingerprint.objects.create(
                                    EXP_id = saved_object,
                                    fingerprint_id = fingerprint_instance
                                )
                            except Exception as e:
                                print(e)
                        else:
                            return JsonResponse({"status": False, "tips": "fingetprint relate to exp error,please refresh page and try again "})

                return JsonResponse({"status": True})
            else:
                return JsonResponse({"status": False, "tips": "please choose the Exposure time"})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "plugin add error"})

def update_exp_relate_fingerprints(fingerprint_id_list, EXP_object,exp_id):
    try:
        # 获取 exp_relate_Fingerprint 表中当前 EXP_id 对应的所有记录
        existing_records = models.exp_relate_fingerprint.objects.filter(EXP_id=EXP_object)

        # 处理传递的 fingerprint_ids
        for fingerprint_id in fingerprint_id_list:
            fingerprint_instance = models.fingerPrint.objects.get(id=int(fingerprint_id))

            # 检查记录是否已经存在
            if not models.exp_relate_fingerprint.objects.filter(fingerprint_id=fingerprint_instance, EXP_id=EXP_object).exists():
                # 如果不存在，添加记录
                models.exp_relate_fingerprint.objects.create(EXP_id=EXP_object, fingerprint_id=fingerprint_instance)

        # 删除不在传递列表中的记录
        for record in existing_records:
            if record.fingerprint_id.id not in fingerprint_id_list:
                record.delete()
        return True
    
    except Exception as e:
        # 处理找不到相应实例的情况
        print(f"Error: {e}")
        return False

def update_db_cve_extions(extions_id_list,exp_id):
    try:
        existing_records = models.cveExtensions.objects.filter(CVE=exp_id)
        # 处理传递的 fingerprint_ids
        for extion_number in extions_id_list:
            _instance = models.EXP.objects.get(id=int(exp_id))
            # 检查记录是否已经存在
            if not models.cveExtensions.objects.filter(function=extion_number, CVE=_instance).exists():
                # 如果不存在，添加记录
                models.cveExtensions.objects.create(function=extion_number, CVE=_instance)
        
        # 删除不在传递列表中的记录
        for record in existing_records:
            if str(record.function) not in extions_id_list:
                record.delete()
        return True
    
    except Exception as e:
        # 处理找不到相应实例的情况
        print(f"Error: {e}")
        return False

@deny_user
def expload_edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.EXP.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
        form = ExploadModelForm(data=request.POST, files=request.FILES,instance=row_object)
        affected_product = request.POST.get('affected_product')
        extentions = request.POST.get('extentions')
        if form.is_valid():
            upload_file = request.FILES.get("poc")
            if upload_file:
                ext = os.path.splitext(upload_file.name)[1].lower()
                plugin_language = int(form.instance.plugin_language or 1)
                if plugin_language == 1 and ext != ".py":
                    return JsonResponse({"status": False, "error": {"poc": ["python3 plugin requires .py file"]}})
                if plugin_language == 2 and ext not in (".yaml", ".yml"):
                    return JsonResponse({"status": False, "error": {"poc": ["nuclei_yaml plugin requires .yaml/.yml file"]}})
            if request.FILES:   # upload file
                try:
                    row_dict = models.EXP.objects.filter(id=uid).values("poc").first()
                    poc_file = row_dict["poc"]
                    file_name = poc_file.split("EXP_plugin/")[1]
                    remove_plugin_file(file_name)
                except:
                    pass
            ctime_str = request.POST.get('ctime')
            try:
                form.instance.time = datetime.strptime(ctime_str, '%m/%d/%Y').date()
            except:
                form.instance.time = datetime.strptime(ctime_str, '%Y/%m/%d').date()
            form.instance.update_time = timezone.now()
            EXP_object = form.save()
            exp_id = EXP_object.id
            if extentions:
                try:
                    extentions_list = extentions.split(",")
                    update_db_cve_extions(extentions_list ,exp_id)
                except:
                    traceback.print_exc()
            if affected_product:
                    fingerprint_id_list = []
                    product_list =  str(affected_product).split(",")
                    for id_product in product_list:
                        id,product = re_get_id_product(id_product)
                        fingerprint_id_list.append(id)
                    result = update_exp_relate_fingerprints(fingerprint_id_list, EXP_object,exp_id)
                    if result:
                        return JsonResponse({"status": True})
                    else:
                        return JsonResponse({"status": False, "tips": "update fingetprint relate to exp error,please refresh page and try again " })
        if not form.errors:
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        traceback.print_exc()
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "plugin edit error"})

def get_fingerprints_for_exp(exp_id):
    try:
        # 获取 EXP 实例
        exp_instance = models.EXP.objects.get(id=exp_id)
        # 获取与 EXP 关联的 exp_relate_Fingerprint 记录
        related_records = models.exp_relate_fingerprint.objects.filter(EXP_id=exp_instance)
        # 获取每个 exp_relate_Fingerprint 记录关联的 fingerPrint 实例的 id 和 product
        fingerprints_data = []
        for record in related_records:
            fingerprint_id = record.fingerprint_id.id
            fingerprint_product = record.fingerprint_id.product
            fingerprints_data.append("[" + str(fingerprint_id) +"]" + str(fingerprint_product))
        return fingerprints_data
    
    except models.EXP.DoesNotExist as e:
        # 处理找不到相应 EXP 实例的情况
        print(f"Error: {e}")
        return None

def get_extentions_for_exp(exp_id):
    try:
        exp_instance = models.EXP.objects.get(id=exp_id)
        # 获取与 EXP 关联的 exp_relate_Fingerprint 记录
        related_records = models.cveExtensions.objects.filter(CVE=exp_instance)
        # 获取每个 exp_relate_Fingerprint 记录关联的 fingerPrint 实例的 id 和 product
        extentions_data = []
        for record in related_records:
            function_number = record.function
            
            extentions_data.append(function_number)
        return extentions_data
    except Exception as e:
         # 处理找不到相应 EXP 实例的情况
        print(f"Error: {e}")
        return None

@deny_user
def expload_Editdetail(request):
    uid = request.GET.get("uid")
    row_object = models.EXP.objects.filter(id=uid).values("title","CVE","Type","time","plugin_language","severity").first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
    exp_obj = models.EXP.objects.filter(id=uid).first()
    tag_list = list(exp_obj.tags.values_list("id", flat=True)) if exp_obj else []
    data = get_fingerprints_for_exp(uid)
    extention_number = get_extentions_for_exp(uid)
    return JsonResponse({"status": True, 'data': row_object, "affected_product":data, "extentions":extention_number, "severity": row_object.get("severity", ""), "tags": tag_list})

def remove_plugin_file(file_name):
    try:
        EXP_path = os.path.dirname(os.path.abspath(pwd)).replace("\\","/") + "/EXP_plugin/"
        if len(EXP_path) !=0:
            for root, dirs, files in os.walk(EXP_path):
                for file in files:
                    if file == file_name:
                        os.remove(os.path.join(root, file))
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "remove_plugin_file error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str) 
        return 

@deny_user
def expload_delete(request):
    uid = request.GET.get("uid")
    data = models.EXP.objects.filter(id=uid).values("poc").first()
    if not data:
        return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
    models.EXP.objects.filter(id=uid).delete()
    try:
        poc_file = data["poc"]
        file_name = poc_file.split("EXP_plugin/")[1]
        remove_plugin_file(file_name)
    except:
        pass
    return JsonResponse({"status": True})

@deny_user
def expload_batch_delete(request):
    uids = request.POST.getlist('uids[]') or request.POST.getlist('uids')
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    # 先批量查出所有 poc 文件路径
    pocs = list(models.EXP.objects.filter(id__in=uids).values_list("id", "poc"))
    # 批量删除
    models.EXP.objects.filter(id__in=uids).delete()
    # 清理磁盘文件
    for _exp_id, poc_file in pocs:
        if poc_file:
            try:
                file_name = poc_file.split("EXP_plugin/")[1]
                remove_plugin_file(file_name)
            except Exception:
                pass
    return JsonResponse({"status": True})


@deny_user
def api_plugin_batch_delete(request):
    """POST /api/v1/plugins/batch-delete  body: {"uids": [1,2,3]}"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    # 先批量查出所有 poc 文件路径
    pocs = list(models.EXP.objects.filter(id__in=uids).values_list("id", "poc"))
    # 批量删除
    models.EXP.objects.filter(id__in=uids).delete()
    # 清理磁盘文件
    for _exp_id, poc_file in pocs:
        if poc_file:
            try:
                file_name = poc_file.split("EXP_plugin/")[1]
                remove_plugin_file(file_name)
            except Exception:
                pass
    return JsonResponse({"status": True})


@deny_user
def expload_useStatus(request):
    uid = request.GET.get("uid")
    UseStatus = request.GET.get("UseStatus")
    if UseStatus == "1":
        UseStatus = "2"  #false
    else:
        UseStatus ="1"

    exists = models.EXP.objects.filter(id=uid).exists()
    if not exists:
        return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
    models.EXP.objects.filter(id=uid).update(use=UseStatus,update_time=timezone.now())
    return JsonResponse({"status": True})
     



