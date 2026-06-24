import codecs
import csv
from datetime import datetime, timezone
import io
import json
import re
import traceback
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import HttpResponse, JsonResponse
import cybersparker.settings as sett
from app_cybersparker.permissions import deny_user, get_role
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import load_runtime_module_from_poc, call_runtime_method, resolve_exp_by_name

# ======================== JSON API ========================

from app_cybersparker.utils.pagination import Pagination as _Pagination


def exp_result_plugins_api(request):
    """GET /api/v1/exp-results/plugins — 获取插件列表（供验证下拉用）"""
    return get_plugin(request)


@deny_user
def exp_result_batch_delete_api(request):
    """POST /api/v1/exp-results/batch-delete — 批量删除漏洞利用结果"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.EXPTask_result.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


@deny_user
def exp_result_clear_api(request):
    """POST /api/v1/exp-results/clear — 清空指定任务的所有漏洞利用结果"""
    import json as _json
    try:
        body = _json.loads(request.body)
        task_id = body.get('task_id')
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not task_id:
        return JsonResponse({"status": False, "tips": "task_id is required"})
    models.EXPTask_result.objects.filter(task_id=task_id).delete()
    return JsonResponse({"status": True})


@deny_user
def exp_result_download_api(request):
    """POST /api/v1/exp-results/download — 下载漏洞利用结果 CSV"""
    return result_download(request)
from django.http import QueryDict

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def exp_result_list_api(request):
    q = request.GET.get("q", "")
    q_id = request.GET.get("id", "")
    q_task_id = request.GET.get("task_id", "")
    q_target = request.GET.get("target", "")
    q_plugin = request.GET.get("plugin", "")
    q_result = request.GET.get("result", "")
    q_creatime = request.GET.get("creatime", "")
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

    queryset = models.EXPTask_result.objects.all().order_by("-id")

    if q:
        queryset = queryset.filter(Q(plugin_name__icontains=q) | Q(target__icontains=q) | Q(result__icontains=q))
    else:
        query_conditions = Q()
        if q_id:
            query_conditions &= Q(id__icontains=str(q_id).strip())
        if q_task_id:
            try:
                query_conditions &= Q(task_id=int(q_task_id))
            except (ValueError, TypeError):
                pass
        if q_target:
            query_conditions &= Q(target__icontains=str(q_target).strip())
        if q_plugin:
            query_conditions &= Q(plugin_name__icontains=str(q_plugin).strip())
        if q_result:
            query_conditions &= Q(result__icontains=str(q_result).strip())
        if q_creatime:
            try:
                filter_date = datetime.strptime(q_creatime, "%Y-%m-%d")
                query_conditions &= Q(creatime__date=filter_date)
            except Exception:
                try:
                    filter_date = datetime.strptime(q_creatime, "%Y-%m")
                    query_conditions &= Q(creatime__date__year=filter_date.year, creatime__date__month=filter_date.month)
                except Exception:
                    try:
                        filter_date = datetime.strptime(q_creatime, "%Y")
                        query_conditions &= Q(creatime__date__year=filter_date.year)
                    except Exception:
                        pass
        if query_conditions:
            queryset = queryset.filter(query_conditions)

    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PR:
        GET = qd
    po = _Pagination(_PR(), queryset)

    items = []
    for obj in po.page_queryset:
        items.append({
            "id": obj.id,
            "task_type": obj.task_type,
            "task_id": obj.task_id,
            "plugin_name": obj.plugin_name,
            "target": obj.target,
            "result": obj.result[:300] if obj.result else "",
            "result_full": obj.result,
            "creatime": obj.creatime.strftime("%Y-%m-%d %H:%M") if obj.creatime else "",
        })

    return JsonResponse({
        "items": items,
        "page": po.page,
        "rows_per_page": po.page_size,
        "total": po.total_count,
        "total_pages": po.total_page_count,
        "filters": {"q": q, "id": q_id, "target": q_target, "plugin": q_plugin, "result": q_result, "creatime": q_creatime},
        "legacy_list_url": "/result_List",
    })


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

class ExploadModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['poc']
    class Meta:
        model = models.EXPTask_result
        exclude = ["creat_time","update_time"]

def result_list(request):
    search_data = request.GET.get('q', "")
    form = ExploadModelForm()

    if search_data:
        queryset = models.EXPTask_result.objects.filter(Q(title__icontains=search_data) | Q(CVE__icontains=search_data))
    else:
        target = request.GET.get('target')
        result = request.GET.get('result')
        select_plugin = request.GET.get('selected_plugin')
        id = request.GET.get('id')
        creatime = request.GET.get('creatime')
        conditions = {}
        if target:
            conditions['target__icontains'] = str(target).strip()
        if result:
            conditions['result__icontains'] = str(result).strip()
        if select_plugin:
            conditions['plugin_name__icontains'] = str(select_plugin).strip()
        if id:
            conditions['id__icontains'] = str(id).strip()
        if creatime:
            try:
                filter_date = datetime.strptime(creatime, '%Y-%m-%d')
                conditions['creatime__date'] = filter_date
            except ValueError:
                try:
                    filter_date = datetime.strptime(creatime, '%Y-%m')
                    conditions['creatime__date__year'] = filter_date.year
                    conditions['creatime__date__month'] = filter_date.month
                except ValueError:
                    try:
                        filter_date = datetime.strptime(creatime, '%Y')
                        conditions['creatime__date__year'] = filter_date.year
                    except ValueError:
                        pass  
        if not conditions:
            queryset = models.EXPTask_result.objects.all().order_by("-id")
            page_object = Pagination(request, queryset)
            context = {
                'form': form,
                'queryset': page_object.page_queryset,
                'page_string': page_object.html(),
                "search_data": search_data
            }
        else:
            queryset = models.EXPTask_result.objects.filter(**conditions)
            page_object = Pagination(request, queryset)
            context = {
                'form': form,
                'queryset': page_object.page_queryset,
                'page_string': page_object.html(),
                "search_data": search_data,
            }
            if target is not None:
                context["target"] = target
            if result is not None:
                context["result"] = result
            if id is not None:
                context["id"] = id
            if select_plugin is not None:
                context["select_plugin"] = select_plugin
            if creatime is not None:
                context["creatime"] = creatime
            context = {key: value for key, value in context.items() if value is not None and value != ''}
    return render(request, 'project/expload/result_manage/all_exp_result.html', context)


def getPluginInfo(request):
    plugin_name = request.GET.get("plugin_name")  # [cve]title 或纯 title
    if plugin_name:
        search_data_instance = resolve_exp_by_name(plugin_name)
        if search_data_instance:
            function_type = models.cveExtensions.objects.filter(CVE=search_data_instance)
            function_list = []
            for obj in function_type:
                function_list.append({"value": obj.function, "label": obj.get_function_display()})
            cve = search_data_instance.CVE
            return  JsonResponse({"status": True, "cve": cve, "function_list": function_list, "plugin_id": search_data_instance.id})
        return JsonResponse({"status": False, "error": "get info failed, data does not exist."})
    else:
        return JsonResponse({"status": False, "error": "Please refresh page and try again"})


def get_plugin(request):
    try:
        queryset = models.EXP.objects.values("CVE","title")
        if not queryset:
            return JsonResponse({"status": False, 'tips': "The result does not exist."})
        data_list = list(queryset)
        return JsonResponse({"status":True, 'data':data_list})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now(timezone.utc)
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        traceback.print_exc()
        return JsonResponse({"status": False, "tips": "get plugin info error"})


@deny_user
def targetRunVerify(request):
    try:
        target = request.POST.get("target")
        plugin_id = request.POST.get("plugin_id")
        plugin = request.POST.get("plugin")
        model = request.POST.get("model")
        try:
            cmd = request.POST.get("cmd")
        except:
            cmd = ""

        if not target:
            return JsonResponse({"status": False, "data": "target is required"})

        instance = None
        if plugin_id:
            instance = models.EXP.objects.filter(id=int(plugin_id)).first()
        elif plugin:
            instance = resolve_exp_by_name(plugin)
        else:
            return JsonResponse({"status": False, "data": "plugin_id or plugin is required"})

        if not instance:
            return JsonResponse({"status": False, "data": "plugin not found"})

        exp = load_runtime_module_from_poc(instance.poc, exp_id=instance.id)
        result = call_runtime_method(exp, model, {"target": target, "task_args": {}}, cmd)
        if result:
            return JsonResponse({"status": True, "data": result})
        else:
            return JsonResponse({"status": False, "data": "verify error"})
    except Exception as e:
        return JsonResponse({"status": False, "data": str(traceback.format_exc())})


@deny_user
def result_download(request):
    try:
        data = request.POST.getlist('id_list[]')
        if data :
            results = models.EXPTask_result.objects.filter(id__in=data).values("id","task_id","plugin_name","target","result","creatime")
        else:
            search_dict = {}
            for key, value in request.POST.items():
                if key !="NULL" and value !="":
                    search_dict[key] = value
            _query = Q()
            for key, value in search_dict.items():
                if value is not None:  
                    if key == "id" or (key == "select_plugin" and value):  # 完全匹配的字段
                        if key == "select_plugin":
                            key = "plugin_name"
                        _query &= Q(**{key: value})
                    else:  # 模糊匹配的字段
                        if key == "select_plugin" and (value =="" or value =="select_plugin"):
                            pass
                        else:   
                            _query &= Q(**{key + '__icontains': value})
            
            if search_dict:
                results = models.EXPTask_result.objects.filter(_query).values("id","task_id","plugin_name","target","result","creatime")
            else:
                results = models.EXPTask_result.objects.all().values("id","task_id","plugin_name","target","result","creatime")
        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=exp_reuslt.csv'
        csv_data = io.StringIO()
        writer = csv.writer(csv_data, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL, lineterminator='\n')
        headers = ["id","task_id","plugin_name","target","result","creatime"]
        writer.writerow(headers)
        for item in results:
            result = []
            for value in item.values():
                result.append(value)
            writer.writerow(result) 
        response.write(codecs.BOM_UTF8)
        response.write(csv_data.getvalue().encode('utf-8'))
        csv_data.close()
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
    except Exception as e:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "download error"
        error_log(e_info,tips,now)
        traceback.print_exc()
        return JsonResponse({"status": False, "error": str(e)})
    
def result_delete(request):
    if request.method == "GET":
        uid = request.GET.get("uid")
        plugin_name = request.GET.get("plugin")
        target = request.GET.get("target")
        exists = models.EXPTask_result.objects.filter(id=uid,plugin_name=plugin_name,target=target).exists()
        if not exists:
            if models.bath_EXPTask_result.objects.filter(id=uid,plugin_name=plugin_name,target=target):
                models.bath_EXPTask_result.objects.filter(id=uid).delete()
                return JsonResponse({"status": True})
            return JsonResponse({"status": False, "error": "Delete failed, data does not exist."})
        models.EXPTask_result.objects.filter(id=uid).delete()
        return JsonResponse({"status": True})
    else:
        if request.method in ('POST', 'PUT', 'DELETE'):
            if get_role(request) == 'user':
                return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

        operate = request.POST.get("operate")
        id_list = request.POST.getlist("content[]")
        if operate == "batch_delete":
            try:
                models.EXPTask_result.objects.filter(id__in=id_list).delete()
                return JsonResponse({"status": True})
            except Exception as e:
                return JsonResponse({"status": False, "error": "Please refresh page and select the ID that needs to be deleted"})
        else:
            return JsonResponse({"status": False, "error": "Please select the ID that needs to be deleted"})
