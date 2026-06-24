import codecs
import csv
from datetime import datetime
import io
import re
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from app_cybersparker.permissions import deny_user, get_role
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import resolve_exp_by_name
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import HttpResponse, JsonResponse
import cybersparker.settings as sett
from django.db.models import F

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
        model = models.auto_scan_exp_result
        exclude = ["creat_time","update_time"]

def get_id_for_EXP_db(input_string):
    # get cve
    match_first_bracket_content = re.search(r'\[([^\]]+)\]', input_string)
    cve = match_first_bracket_content.group(1) if match_first_bracket_content else None
    # get title
    match_after_first_bracket = re.search(r'\]\s*(.+)', input_string)
    title = match_after_first_bracket.group(1) if match_after_first_bracket else None
    
    if cve and title:
        data_dict = models.EXP.objects.filter(CVE=cve,title=title).values("id").first()
        if data_dict:
            return data_dict["id"]
        else:
            return None
    return None

def list(request):
    form = ExploadModelForm()
    id = request.GET.get('id')
    target = request.GET.get('target')
    product = request.GET.get('product')
    plugin = request.GET.get('selected_plugin')
    result = request.GET.get('result')
    creatime = request.GET.get('creatime')
    conditions = {}
    if id:
        conditions['id__icontains'] = str(id).strip()
    if target:
        conditions['target__icontains'] = str(target).strip()
    if product:
        conditions['product__icontains'] = str(product).strip()
    if plugin:
        exp_id = get_id_for_EXP_db(plugin)
        if exp_id:
            conditions['EXP_id__id'] = int(exp_id)
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
    if result:
        conditions['result__icontains'] = str(result).strip()
    if not conditions:
        queryset = models.auto_scan_exp_result.objects.all().order_by("-id")
        page_object = Pagination(request, queryset)
        context = {
            'form': form,
            'queryset': page_object.page_queryset,
            'page_string': page_object.html(),
        }
    else:
        # 使用 Q 对象将条件组合起来
        query_conditions = Q(**conditions)
        queryset = models.auto_scan_exp_result.objects.filter(query_conditions)
        page_object = Pagination(request, queryset)
        context = {
            'form': form,
            'queryset': page_object.page_queryset,
            'page_string': page_object.html(),
        }
        if target is not None:
            context["target"] = target
        if product is not None:
            context["product"] = product
        if result is not None:
                context["result"] = result
        if plugin is not None:
            context["select_plugin"] = plugin
        if id is not None:
            context["id"] = id
        if creatime is not None:
            context["creatime"] = creatime
        context = {key: value for key, value in context.items() if value is not None and value != ''}
    return render(request, 'project/expload/result_manage/all_auto_exp_result.html', context)




@deny_user
def download(request):
    try:
        data = request.POST.getlist('id_list[]')
        if data :
            results = models.auto_scan_exp_result.objects.filter(id__in=data).values("id","task_id","target","product","result","EXP_id","creatime")
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
                            pattern = r"\[(.*?)\](.*)"
                            match = re.search(pattern, value)
                            if match:
                                cve = match.group(1)   
                                title = match.group(2)
                                exp_obj = models.EXP.objects.filter(CVE=cve,title=title).values("id").first()
                                EXP_id = exp_obj["id"]
                                _query &= Q(**{"EXP_id": EXP_id})
                        else:
                            _query &= Q(**{key: value})
                    else:  # 模糊匹配的字段
                        if key == "select_plugin" and (value =="" or value =="select_plugin"):
                            pass
                        else:   
                            _query &= Q(**{key + '__icontains': value})
            if search_dict:
                results = models.auto_scan_exp_result.objects.filter(_query).values("id","task_id","target","product","result","EXP_id","creatime")
            else:
                results = models.auto_scan_exp_result.objects.all().values("id","task_id","target","product","result","EXP_id","creatime")
        
        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=exp_reuslt.csv'
        csv_data = io.StringIO()
        writer = csv.writer(csv_data, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL, lineterminator='\n')
        headers = ["id","task_id","target","product","result","exp","creatime"]
        writer.writerow(headers)
        for item in results:
            exp_id = item["EXP_id"]
            exp_data = models.EXP.objects.filter(id=exp_id).values("id","CVE","title").first()
            if exp_data:
                item["EXP_id"] = str(exp_data["id"])  + "-[" + str(exp_data["CVE"]) + "]" + str(exp_data["title"])
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
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "download error"
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "error": str(e)})
    
# ======================== JSON API ========================

from app_cybersparker.utils.pagination import Pagination as _Pagination


@deny_user
def auto_exp_result_batch_delete_api(request):
    """POST /api/v1/auto-exp-results/batch-delete — 批量删除自动扫描利用结果"""
    import json as _json
    try:
        body = _json.loads(request.body)
        uids = body.get('uids', [])
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not uids:
        return JsonResponse({"status": False, "tips": "No items selected"})
    models.auto_scan_exp_result.objects.filter(id__in=uids).delete()
    return JsonResponse({"status": True})


@deny_user
def auto_exp_result_clear_api(request):
    """POST /api/v1/auto-exp-results/clear — 清空指定任务的所有自动扫描漏洞结果"""
    import json as _json
    try:
        body = _json.loads(request.body)
        task_id = body.get('task_id')
    except Exception:
        return JsonResponse({"status": False, "tips": "Invalid JSON"}, status=400)
    if not task_id:
        return JsonResponse({"status": False, "tips": "task_id is required"})
    models.auto_scan_exp_result.objects.filter(task_id=task_id, task_type=1).delete()
    return JsonResponse({"status": True})


@deny_user
def auto_exp_result_download_api(request):
    """POST /api/v1/auto-exp-results/download — 下载自动扫描利用结果 CSV"""
    return download(request)
from django.http import QueryDict

ROWS_PER_PAGE_WHITELIST = {5, 10, 13, 100}


def auto_exp_result_list_api(request):
    q_id = request.GET.get("id", "")
    q_task_id = request.GET.get("task_id", "")
    q_target = request.GET.get("target", "")
    q_product = request.GET.get("product", "")
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

    # 默认只查自动扫描结果（task_type=1），批量任务结果（task_type=3）走 expResult.py 的 EXPTask_result 表
    queryset = models.auto_scan_exp_result.objects.select_related("EXP_id").filter(task_type=1).order_by("-id")
    query_conditions = Q()
    if q_id:
        query_conditions &= Q(id__icontains=str(q_id).strip())
    if q_target:
        query_conditions &= Q(target__icontains=str(q_target).strip())
    if q_product:
        query_conditions &= Q(product__icontains=str(q_product).strip())
    if q_plugin:
        exp_id = get_id_for_EXP_db(q_plugin)
        if exp_id:
            query_conditions &= Q(EXP_id__id=int(exp_id))
        else:
            query_conditions &= Q(EXP_id__title__icontains=str(q_plugin).strip())
    if q_task_id:
        try:
            # 注意：此表同时包含 auto_scan(task_type=1) 和 batch(task_type=3) 的结果，
            # task_id 在两张任务表中可能碰撞，这里只按 task_id 过滤不做 task_type 区分，
            # 如需精确筛选请配合其他过滤条件使用。
            query_conditions &= Q(task_id=int(q_task_id))
        except (ValueError, TypeError):
            pass
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

    queryset = queryset.filter(query_conditions) if query_conditions else queryset
    qd = QueryDict(mutable=True)
    qd["page"] = str(page)
    qd["rows_per_page"] = str(rows)

    class _PR:
        GET = qd

    po = _Pagination(_PR(), queryset)

    items = []
    for obj in po.page_queryset:
        exp_obj = obj.EXP_id
        plugin_label = f"{exp_obj.id}-[{exp_obj.CVE}]{exp_obj.title}" if exp_obj else "-"
        items.append({
            "id": obj.id,
            "task_id": obj.task_id,
            "target": obj.target,
            "product": obj.product,
            "plugin_name": plugin_label,
            "result": obj.result[:200] if obj.result else "",
            "creatime": obj.creatime.strftime("%Y-%m-%d %H:%M") if obj.creatime else "",
        })

    return JsonResponse({
        "items": items,
        "page": po.page,
        "rows_per_page": po.page_size,
        "total": po.total_count,
        "total_pages": po.total_page_count,
        "filters": {
            "id": q_id,
            "target": q_target,
            "product": q_product,
            "plugin": q_plugin,
            "result": q_result,
            "creatime": q_creatime,
        },
        "legacy_list_url": "/auto_exp_result",
    })


def delete(request):
    if request.method == "GET":
        uid = request.GET.get("uid")
        obj = models.auto_scan_exp_result.objects.get(id=uid)
        if obj:
            obj.delete()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": "The data does not exist, please refresh and try again"})
    else:
        if request.method in ('POST', 'PUT', 'DELETE'):
            if get_role(request) == 'user':
                return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

        operate = request.POST.get("operate")
        id_list = request.POST.getlist("content[]")
        if operate == "batch_delete":
            try:
                models.auto_scan_exp_result.objects.filter(id__in=id_list).delete()
                return JsonResponse({"status": True})
            except:
                return JsonResponse({"status": False, "error": "Please refresh page and select the ID that needs to be deleted"})
        else:
            return JsonResponse({"status": False, "error": "Please select the ID that needs to be deleted"})
