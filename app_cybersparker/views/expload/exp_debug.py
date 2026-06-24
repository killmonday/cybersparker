from datetime import datetime
import re
import traceback
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
from django import forms
import os
import random
import string
from django.utils import timezone
import cybersparker.settings as sett
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import load_runtime_module_from_poc, call_runtime_method, resolve_exp_by_name
from app_cybersparker.views.expload.plugin_manage import update_exp_relate_fingerprints
from app_cybersparker.permissions import deny_user
from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
from app_cybersparker.lib.request_runtime.conf import conf as request_conf
from app_cybersparker.services.request_runtime_config_service import _build_proxy_from_setting

# ======================== JSON API wrappers ========================
import json as _json
import traceback as _traceback


@deny_user
def api_plugin_list(request):
    return debug_getPluginList(request)


@deny_user
def api_exp_info(request):
    """POST JSON: {plugin_id: int}"""
    try:
        body = _json.loads(request.body.decode("utf-8"))
        plugin_id = body.get("plugin_id")
        if not plugin_id:
            return JsonResponse({"status": False, "tips": "plugin_id is required"})

        exp_data = models.EXP.objects.filter(id=int(plugin_id)).first()
        if not exp_data:
            return JsonResponse({"status": False, "tips": "plugin not found"})

        file_path = str(exp_data.poc)
        with open(file_path, "r", encoding="UTF8") as f:
            poc_content = f.read()
        support_function = get_extentions_for_exp(exp_data.id)
        tag_list = list(exp_data.tags.values_list("id", flat=True))
        # 已关联指纹
        fingerprint_records = models.exp_relate_fingerprint.objects.filter(
            EXP_id=exp_data
        ).select_related("fingerprint_id")
        fingerprints = [
            {"id": r.fingerprint_id.id, "product": r.fingerprint_id.product}
            for r in fingerprint_records
        ]
        return JsonResponse({"status": True, "data": {
            "title": exp_data.title,
            "CVE": exp_data.CVE,
            "Type": exp_data.Type,
            "plugin_model": exp_data.plugin_language,
            "time": str(exp_data.time) if exp_data.time else "",
            "content": poc_content,
            "ExtensionsType": ExtensionsType,
            "support_function": support_function,
            "tags": tag_list,
            "fingerprints": fingerprints,
        }})
    except Exception as e:
        return JsonResponse({"status": False, "tips": str(e)})


@deny_user
def api_exp_execute(request):
    """POST JSON: {target, plugin_id, model, cmd, proxy_id, http_timeout}"""
    _orig_timeout = request_conf.timeout
    try:
        body = _json.loads(request.body.decode("utf-8"))
        plugin_id = body.get("plugin_id")
        target = body.get("target", "")
        model = body.get("model", "verify")
        cmd = body.get("cmd", "")
        proxy_id = body.get("proxy_id", "0")
        http_timeout = body.get("http_timeout")
        if http_timeout is not None:
            try:
                request_conf.timeout = float(http_timeout)
            except (TypeError, ValueError):
                pass
        _apply_debug_proxy(proxy_id)

        if not plugin_id:
            return JsonResponse({"status": False, "result": "plugin_id is required"})

        exp_dict = models.EXP.objects.filter(id=int(plugin_id)).values("id", "poc").first()
        if not exp_dict:
            return JsonResponse({"status": False, "result": "plugin not found"})

        exp = load_runtime_module_from_poc(exp_dict["poc"], exp_id=exp_dict["id"])
        if str(exp_dict.get("poc", "")).lower().endswith((".yaml", ".yml")):
            runtime_target = {"target": target, "__debug_trace": True, "__debug_plugin_id": exp_dict["id"]}
        else:
            runtime_target = {"target": target}
            task_args_raw = body.get("task_args", "")
            try:
                runtime_target["task_args"] = _json.loads(task_args_raw) if task_args_raw.strip() else {}
            except Exception:
                runtime_target["task_args"] = {}

        result = call_runtime_method(exp, model, runtime_target, cmd)

        # 归一化 matched：Python 插件返回值格式不统一（dict/matched、
        # dict/result、None、bool、str），统一提取布尔成功标志
        if isinstance(result, dict) and "matched" in result:
            matched = bool(result["matched"])
        elif isinstance(result, dict) and "result" in result:
            matched = bool(result["result"])
        else:
            matched = bool(result)

        if isinstance(result, dict) and "result" in result:
            display = str(result["result"])
        else:
            display = str(result)

        trace_lines = result.get("trace") if isinstance(result, dict) else None
        if trace_lines:
            trace_text = "\n".join(trace_lines)
            display = display + "\n\n--- 调试轨迹 ---\n" + trace_text if display else "--- 调试轨迹 ---\n" + trace_text

        return JsonResponse({"status": True, "matched": matched, "result": display})
    except Exception as e:
        return JsonResponse({"status": False, "result": str(e)})
    finally:
        set_task_proxy(None)
        request_conf.timeout = _orig_timeout


@deny_user
def api_exp_save(request):
    """POST JSON: plugin save (create or edit)"""
    try:
        body = _json.loads(request.body.decode("utf-8"))
        from django.http import QueryDict

        qd = QueryDict(mutable=True)
        qd["title_model"] = str(body.get("title_model", "edit plugin"))
        qd["plugin_id"] = str(body.get("plugin_id", ""))
        qd["poc_content"] = str(body.get("poc_content", ""))
        qd["CVE"] = str(body.get("CVE", ""))
        qd["title"] = str(body.get("title", ""))
        qd["Type"] = str(body.get("Type", "1"))
        qd["ctime"] = str(body.get("ctime", ""))
        if body.get("extentions"):
            qd["extentions"] = str(body.get("extentions", ""))
        if body.get("plugin_language"):
            qd["plugin_language"] = str(body.get("plugin_language", "1"))
        if body.get("tags"):
            qd.setlist("tags", [str(t) for t in body.get("tags", [])])
        if "affected_product" in body:
            qd["affected_product"] = str(body.get("affected_product", ""))
        qd._mutable = False
        request._post = qd
        return expload_save(request)
    except Exception as e:
        return JsonResponse({"status": False, "result": str(e)})


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
            f.write(f"[exploadDEbug {tips}] {time} : " +  e_info + "\n")
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
        exclude = ["creat_time","use","time","poc","update_time","poc_type","poc_content","current_line"]
        widgets = {
            'Type': forms.Select(attrs={'class': 'form-control',"style":"width: 88%;"}),
            'plugin_model': forms.Select(attrs={'class': 'form-control',"style":"width: 40%;"}),
            'plugin_language': forms.Select(attrs={'class': 'form-control',"style":"width: 74%;"}),
        }


def get_debug_plugin_queryset():
    return list(models.EXP.objects.all().values("id", "title", "CVE").order_by("-id"))


def format_plugin_label(cve, title):
    return f"[{cve}] {title}"


@deny_user
def exploadDebug(request):
    form = ExploadModelForm()
    all_tags = models.Tag.objects.all()
    data = {
        'form': form,
        "queryset": get_debug_plugin_queryset(),
        "ExtensionsType":ExtensionsType,
        "tag_choices": [(t.id, t.name) for t in all_tags],
    }
    return render(request,"project/expload/exp_debug.html",data)

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
def debug_getPluginList(request):
    try:
        q = request.GET.get("q", "").strip()
        offset = int(request.GET.get("offset", 0))
        limit = min(int(request.GET.get("limit", 50)), 100)

        if q:
            from django.db.models import Q
            qs = models.EXP.objects.filter(
                Q(title__icontains=q) | Q(CVE__icontains=q)
            ).values("id", "title", "CVE").order_by("-id")
        else:
            qs = models.EXP.objects.all().values("id", "title", "CVE").order_by("-id")

        # 多取一条判断 has_more，避免额外 COUNT 查询
        page = list(qs[offset:offset + limit + 1])
        has_more = len(page) > limit
        if has_more:
            page = page[:limit]

        plugin_options = [
            {
                "id": item["id"],
                "title": item["title"],
                "CVE": item["CVE"],
                "label": format_plugin_label(item["CVE"], item["title"]),
            }
            for item in page
        ]
        return JsonResponse({"status": True, "data": plugin_options, "has_more": has_more})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "debug_getPluginList error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info, tips, time_str)
        traceback.print_exc()
        return JsonResponse({"status": False, "tips": "get plugin list error"})


@deny_user
def debug_getExpInfo(req):
    try:
        plugin_id = req.POST.get("plugin_id")
        if plugin_id:
            exp_data = models.EXP.objects.filter(id=plugin_id).first()
        else:
            content = req.POST.get("content", "")
            exp_data = resolve_exp_by_name(content.strip()) if content else None
            if not exp_data:
                return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})

        if not exp_data:
            return JsonResponse({"status": False, 'tips': "The data does not exist. Please refresh and try again"})
        file_path = str(exp_data.poc)
        with open (file_path,"r",encoding="UTF8") as f:
            poc_content = f.read()
        support_function = get_extentions_for_exp(exp_data.id)
        tag_list = list(exp_data.tags.values_list("id", flat=True)) if exp_data else []
        context = {
            "title": exp_data.title,
            "CVE": exp_data.CVE,
            "Type": exp_data.Type,
            "plugin_model": exp_data.plugin_language,
            "time": exp_data.time,
            "content": poc_content,
            "ExtensionsType":ExtensionsType,
            "support_function":support_function,
            "tags": tag_list,
        }
        return JsonResponse({"status":True, 'data':context})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str) 
        traceback.print_exc()
        return JsonResponse({"status": False, "tips": "get plugin info error"})
        
def _apply_debug_proxy(proxy_id_raw):
    """解析 proxy_id，查库并调用 set_task_proxy。返回用于展示的代理名称。"""
    proxy_id = str(proxy_id_raw or "").strip()
    if proxy_id in ("", "0"):
        set_task_proxy({})  # 直连，不走代理
        return "直连"
    try:
        pid = int(proxy_id)
        proxy_obj = models.ProxySetting.objects.filter(id=pid).first()
        if proxy_obj:
            proxies = _build_proxy_from_setting(proxy_obj)
            set_task_proxy(dict(proxies))
            return str(proxy_obj.proxy_address or "")
        set_task_proxy({})
        return "直连（代理未找到）"
    except (ValueError, TypeError):
        set_task_proxy({})
        return "直连"


@deny_user
def debug_execute(request):
    target = request.POST.get("target")
    plugin_id = request.POST.get("plugin_id")
    model = request.POST.get("model")
    cmd = request.POST.get("cmd")
    proxy_id = request.POST.get("proxy_id", "0")
    _apply_debug_proxy(proxy_id)
    result = {}
    if plugin_id:
        exp_dict = models.EXP.objects.filter(id=plugin_id).values("id", "poc").first()
    else:
        # 兼容旧版前端（未传 plugin_id）
        exp_title = str(request.POST.get("select", "")).strip()
        exp_obj = resolve_exp_by_name(exp_title) if exp_title else None
        exp_dict = {"id": exp_obj.id, "poc": str(exp_obj.poc)} if exp_obj else None
    if not exp_dict:
        return JsonResponse({"status": False, "result": "plugin not found"})
    try:
        exp = load_runtime_module_from_poc(exp_dict["poc"], exp_id=exp_dict["id"])
        if str(exp_dict.get("poc", "")).lower().endswith((".yaml", ".yml")):
            runtime_target = {"target": target, "__debug_trace": True, "__debug_plugin_id": exp_dict["id"]}
            print(f"[nuclei-debug-trace] 调试页开始执行 YAML 插件 id={exp_dict['id']} target={target!r} model={model!r}")
        else:
            runtime_target = {"target": target}
            task_args_raw = request.POST.get("task_args", "")
            try:
                runtime_target["task_args"] = _json.loads(task_args_raw) if task_args_raw.strip() else {}
            except Exception:
                runtime_target["task_args"] = {}
        result = call_runtime_method(exp, model, runtime_target, cmd)
        if isinstance(result, dict) and "result" in result:
            display = str(result["result"])
        else:
            display = str(result)

        trace_lines = result.get("trace") if isinstance(result, dict) else None
        if trace_lines:
            trace_text = "\n".join(trace_lines)
            if display:
                display = display + "\n\n--- 调试轨迹 ---\n" + trace_text
            else:
                display = "--- 调试轨迹 ---\n" + trace_text

        if isinstance(result, dict) and "matched" in result:
            return JsonResponse({"status": bool(result.get("matched")), "matched": bool(result.get("matched")), "result": display})

        return JsonResponse({"status": True, "result": display})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status":False,"result":str(e)})
    finally:
        set_task_proxy(None)  # 清除当前线程的代理状态

def sanitize_filename(filename, max_length=255):
    # 定义非法字符
    illegal_chars = r'[<>:"/\\|?*\x00-\x1F]'  # Windows 和 Linux 的非法字符
    reserved_names = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }

    # 去掉非法字符
    sanitized = re.sub(illegal_chars, "_", filename)

    # 去掉前后的空白字符
    sanitized = sanitized.strip()

    # 如果文件名是保留关键字，则添加后缀
    if sanitized.upper() in reserved_names:
        sanitized += "_file"

    # 限制文件名长度
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    # 如果文件名为空，使用默认名称
    if not sanitized:
        sanitized = "default_file"

    return sanitized

def generate_random_file_name(folder_path,poc_content,cve_form,title,file_ext=".py"):
    try:
        filename = "[" + cve_form +"]" + title + "_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + file_ext
        filename = sanitize_filename(filename)
        # filename = "[" + cve_form +"]" + title + '.py'
        file_path = os.path.join(folder_path, filename)
        if os.path.exists(file_path):
            return generate_random_file_name(folder_path,poc_content,cve_form,title,file_ext)
        else:
            with open(file_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(poc_content)
            return filename
    except:
        traceback.print_exc()
        filename = str(datetime.now().strftime("%Y%m%d%H%M%S")) + file_ext
        file_path = os.path.join(folder_path, filename)
        try:
            with open(file_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(poc_content)
        except:
            traceback.print_exc()
        return filename

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
def expload_save(request):
    form = ExploadModelForm(data=request.POST)
    try:
        model_title = request.POST.get('title_model')
        poc_content = request.POST.get('poc_content')
        ctime_str = (request.POST.get('ctime') or '').replace('-', '/')
        if not ctime_str.strip():
            ctime_str = timezone.now().strftime('%Y/%m/%d')
        cve_form = request.POST.get('CVE')
        title = request.POST.get('title')
        Type = request.POST.get('Type')
        support_function = request.POST.get('extentions')

        if model_title in ("add plugin", "新增插件"):
            if form.is_valid():
                plugin_language = int(form.instance.plugin_language or 1)
                file_ext = ".py" if plugin_language == 1 else ".yaml"
                poc_filename = generate_random_file_name("EXP_plugin",poc_content,cve_form,title,file_ext)
                form.instance.time = datetime.strptime(ctime_str, '%Y/%m/%d').date()
                form.instance.poc = "EXP_plugin/" + poc_filename
                form.instance.creat_time = timezone.now()
                saved_object = form.save()
                if support_function:
                    try:
                        extentions = support_function.split(",")
                        for extention in extentions:
                            models.cveExtensions.objects.create(
                                CVE = saved_object,
                                function = int(extention)
                            )
                    except Exception as e:
                        traceback.print_exc()
                return JsonResponse({"status": True,"tips":"create success", "selected_label": format_plugin_label(saved_object.CVE, saved_object.title), "plugin_id": saved_object.id})
            return JsonResponse({"status": False, "error": form.errors})
        else:
            plugin_id = request.POST.get('plugin_id')
            if plugin_id:
                poc_dict = models.EXP.objects.filter(id=plugin_id).values("id","poc","CVE","title").first()
            else:
                # 兼容旧版前端（未传 plugin_id）
                exp_obj = resolve_exp_by_name(model_title)
                if not exp_obj:
                    return JsonResponse({"status": False, "error": "Unable to parse plugin title, please refresh the page and retry."})
                poc_dict = {"id": exp_obj.id, "poc": str(exp_obj.poc), "CVE": exp_obj.CVE or "", "title": exp_obj.title or ""}
            if poc_dict:
                poc_path = poc_dict["poc"]
                with open (poc_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(poc_content)
                if support_function:
                    try:
                        extentions_list = support_function.split(",")
                        update_db_cve_extions(extentions_list ,poc_dict["id"])
                    except:
                        traceback.print_exc()
                if 'affected_product' in request.POST:
                    try:
                        affected_product = request.POST.get('affected_product', '')
                        fingerprint_id_list = []
                        if affected_product.strip():
                            product_list = affected_product.split(",")
                            for id_product in product_list:
                                if not id_product.strip():
                                    continue
                                fp_id = int(id_product.strip())
                                fingerprint_id_list.append(fp_id)
                        EXP_object = models.EXP.objects.get(id=poc_dict["id"])
                        update_exp_relate_fingerprints(fingerprint_id_list, EXP_object, poc_dict["id"])
                    except Exception:
                        traceback.print_exc()
                if title != poc_dict["title"]:
                    if form.is_valid():
                        models.EXP.objects.filter(id=poc_dict["id"]).update(title=form.instance.title,
                                                                            CVE=form.instance.CVE,
                                                                            Type=form.instance.Type,
                                                                            time=datetime.strptime(ctime_str, '%Y/%m/%d').date(),
                                                                            update_time=timezone.now(),
                                                                            )
                        return JsonResponse({"status": True,"tips":"edit success", "selected_label": format_plugin_label(form.instance.CVE, form.instance.title)})
                    return JsonResponse({"status": False, "error": form.errors})
                else:
                    if not title:
                        return JsonResponse({"status": False, "error": {"title": ["This field is required."]}})
                    models.EXP.objects.filter(id=poc_dict["id"]).update(title=title,
                                                                        CVE=cve_form,
                                                                        Type=Type,
                                                                        time=datetime.strptime(ctime_str, '%Y/%m/%d').date(),
                                                                        update_time=timezone.now(),
                                                                        )
                    return JsonResponse({"status": True,"tips":"edit success", "selected_label": format_plugin_label(form.instance.CVE if form.is_valid() else cve_form, title)})
            return JsonResponse({"status": False, "error": "The data does not exist. Please refresh and try again" })
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_save error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        traceback.print_exc() 
        return JsonResponse({"status":False,"result":str(e)})