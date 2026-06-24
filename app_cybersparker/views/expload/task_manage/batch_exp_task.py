import json
import logging
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
import time
import re
from uuid import uuid4
from threading import Thread
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
import traceback
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.permissions import deny_user, get_role
from app_cybersparker.services.celery_runtime_service import dispatch_task
from app_cybersparker.services.cyberspace_engine_service import fetch_and_dump_targets, get_engine_asset_file_path, is_engine_asset_target, remove_engine_asset_file, get_absolute_target_path
from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal, set_pause_signal, set_stop_signal
from app_cybersparker.services.task_state_cas_service import initialize_task_runtime
from app_cybersparker.tasks import run_batch_scan_task
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from app_cybersparker.utils.pagination import Pagination
import app_cybersparker.views.expload.task_manage.batch_task_executor as batch_exec
from app_cybersparker.views.expload.task_manage.gevent_batch_runner import run_gevent_task_in_subprocess
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import load_runtime_module_from_poc, call_runtime_method, resolve_exp_by_name
from django.conf import settings
from django.db.models import Q, Case, When, Value, CharField
import cybersparker.settings as sett

pwd = sett.THIS_DIR

class ProcessTaskKiller:
    def __init__(self, process, pause_requested=None, stop_requested=None):
        self.process = process
        self._pause_requested = pause_requested
        self._stop_requested = stop_requested

    @property
    def pause_requested(self):
        if self._pause_requested is not None:
            return self._pause_requested.value
        return False

    @property
    def stop_requested(self):
        if self._stop_requested is not None:
            return self._stop_requested.value
        return False

    def kill_task(self):
        try:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
        except Exception:
            pass



def error_log(e_info, tips, time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open(error_log_path, "a+") as f:
            f.write(f"[bath_exploadTask {tips}] {time} : " + e_info + "\n")
            f.close()
    except:
        pass


class batch_ExpTask_ModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['target']

    class Meta:
        model = models.batch_EXPTask
        fields = ["task_name", "thread_num", "sleep_time", "http_timeout", "run_mode", "input_type", "target",
                  "search_query",
                  "engine_type", "engine_query", "engine_max_assets", "engine_proxy_mode", "engine_proxy",
                  "proxy", "remark",
                  "exp_select_mode", "severity_filter", "tag_filter", "filter_logic", "task_args", "zone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zone"].required = False

    def clean_thread_num(self):
        thread_num = self.cleaned_data.get('thread_num')
        if thread_num and thread_num > settings.MAX_EXPLOIT_THREAD_NUM:
            raise ValidationError(f'线程数不能超过 {settings.MAX_EXPLOIT_THREAD_NUM}')
        return thread_num


def Task_list(request):
    data_dict = {}
    search_data = request.GET.get('q', "")
    if search_data:
        data_dict["task_name__contains"] = search_data

    queryset = models.batch_EXPTask.objects.filter(**data_dict).order_by("-id")
    form = batch_ExpTask_ModelForm()
    page_object = Pagination(request, queryset)

    all_tags = models.Tag.objects.all()
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data,
        "severity_choices": models.EXP.severity_choices,
        "tag_choices": [(t.id, t.name) for t in all_tags],
    }
    return render(request, 'project/expload/task_manage/bath_exp_task_list.html', context)


def get_all_plugin(request):
    exp = models.EXP.objects.all().values("id", "title")
    a = []
    for data in exp:
        item = "[" + str(data["id"]) + "] " + data["title"]
        a.append(item)
    if exp:
        context = {"plugin": a,}
        return JsonResponse({"status": True, "data": context})
    return JsonResponse({"status": False, "data": "请先添加插件"})


def get_exp_input_dir():
    return os.path.dirname(os.path.abspath(pwd)).replace("\\", "/") + "/EXP_input"


def _format_form_error(form):
    """Django form.errors → 单行可读字符串。"""
    parts = []
    for field, messages in form.errors.items():
        msgs = messages if isinstance(messages, (list, tuple)) else [messages]
        for m in msgs:
            field_obj = form.fields.get(field)
            label = field_obj.label if field_obj and hasattr(field_obj, 'label') else field
            parts.append(f"{label}: {m}")
    return "; ".join(parts) if parts else "表单校验失败"


def _serialize_form_errors(form):
    """Django form.errors → {field_name: first_error_message} 平坦 dict。"""
    result = {}
    for field, messages in form.errors.items():
        msgs = messages if isinstance(messages, (list, tuple)) else [messages]
        result[field] = msgs[0] if msgs else ""
    return result


def parse_selected_exp_ids(plugin_str):
    plugin_str = str(plugin_str or "").strip()
    if plugin_str == "all" or not plugin_str:
        return "all", []
    exp_ids = [item.strip() for item in plugin_str.split(",") if item.strip().isdigit()]
    return "ids", exp_ids


def get_plugin_names(plugin_mode, exp_ids):
    if plugin_mode == "all":
        exp_queryset = models.EXP.objects.all().values("CVE", "title")
    else:
        exp_queryset = models.EXP.objects.filter(id__in=exp_ids).values("CVE", "title")
    return ["[" + obj["CVE"] + "]" + obj["title"] for obj in exp_queryset]


def get_merged_dir():
    merged = os.path.join(get_exp_input_dir(), ".merged")
    os.makedirs(merged, exist_ok=True)
    return merged


def build_target_file_from_targets(targets):
    unique_targets = []
    seen = set()
    for target in targets:
        value = str(target).strip()
        if value and value not in seen:
            seen.add(value)
            unique_targets.append(value)

    if not unique_targets:
        return None

    unique_filename = f"{uuid4().hex}.txt"
    relative_path = f"EXP_input/.merged/{unique_filename}"
    full_path = os.path.join(get_merged_dir(), unique_filename)
    with open(full_path, "w", encoding="utf-8", errors="ignore") as file_obj:
        file_obj.write("\n".join(unique_targets))
    return relative_path


def collect_targets_from_history_vul_assets(plugin_id, zone_id=None):
    plugin_mode, exp_ids = parse_selected_exp_ids(plugin_id)
    targets = []

    # 只消费 auto_scan_exp_result（本期不纳入 EXPTask_result）
    if plugin_mode == "all":
        auto_queryset = models.auto_scan_exp_result.objects.filter(
            task_type__in=[1, 2, 3], identify_result_id__isnull=False,
        )
    else:
        auto_queryset = models.auto_scan_exp_result.objects.filter(
            EXP_id_id__in=exp_ids, task_type__in=[1, 2, 3],
            identify_result_id__isnull=False,
        )
    # zone 过滤：通过 identify_result_id -> asset.zone
    if zone_id:
        auto_queryset = auto_queryset.filter(
            identify_result__zone_id=zone_id,
        ).select_related("identify_result")
    targets.extend(auto_queryset.values_list("target", flat=True))

    # EXPTask_result 本期跳过，不纳入 zone 化范围
    return targets


def collect_targets_from_history_files(file_names):
    targets = []
    exp_input_dir = get_exp_input_dir()
    for file_name in file_names:
        safe_name = os.path.basename(str(file_name).strip())
        if not safe_name:
            continue
        file_path = os.path.join(exp_input_dir, safe_name)
        if not os.path.isfile(file_path):
            continue
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
            for line in file_obj:
                line = line.strip()
                if line:
                    targets.append(line)
    return targets


def collect_targets_from_engine_history_files(file_paths):
    targets = []
    for file_path in file_paths:
        abs_path = get_engine_asset_file_path(str(file_path).strip())
        if not abs_path or not os.path.isfile(abs_path):
            continue
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as file_obj:
            for line in file_obj:
                line = line.strip()
                if line:
                    targets.append(line)
    return targets


def get_history_files_from_request(request):
    history_files = request.POST.getlist("history_files[]")
    if not history_files:
        history_files = request.POST.getlist("history_files")
    safe_files = []
    for file_name in history_files:
        safe_name = os.path.basename(str(file_name).strip())
        if safe_name and safe_name not in safe_files:
            safe_files.append(safe_name)
    return safe_files


def get_engine_history_files_from_request(request):
    file_paths = request.POST.getlist("history_engine_files[]")
    if not file_paths:
        file_paths = request.POST.getlist("history_engine_files")
    safe_files = []
    for file_path in file_paths:
        clean = str(file_path).strip()
        if clean and clean not in safe_files:
            safe_files.append(clean)
    return safe_files


def list_exp_input_files():
    exp_input_dir = get_exp_input_dir()
    if not os.path.isdir(exp_input_dir):
        return []

    file_info_list = []
    for file_name in os.listdir(exp_input_dir):
        file_path = os.path.join(exp_input_dir, file_name)
        if not os.path.isfile(file_path):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
        file_info_list.append({"file_name": file_name, "mtime": mtime})

    file_info_list.sort(key=lambda item: item["mtime"], reverse=True)
    return file_info_list


def count_non_empty_lines(file_path, chunk_size=1024 * 1024):
    count = 0
    has_non_space = False
    with open(file_path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            for byte in chunk:
                if byte == 10:
                    if has_non_space:
                        count += 1
                    has_non_space = False
                elif byte not in (9, 10, 11, 12, 13, 32):
                    has_non_space = True
    if has_non_space:
        count += 1
    return count


def list_history_engine_results():
    """Return deduplicated historical engine query results from auto/batch tasks."""
    auto_engine_tasks = models.auto_scan_tasks.objects.filter(
        input_type=4, target__isnull=False
    ).values(
        "target", "engine_type", "engine_query", "task_name", "creat_time"
    )
    batch_engine_tasks = models.batch_EXPTask.objects.filter(
        input_type=4, target__isnull=False
    ).values(
        "target", "engine_type", "engine_query", "task_name", "creat_time"
    )

    engine_tasks = list(auto_engine_tasks) + list(batch_engine_tasks)
    engine_tasks.sort(key=lambda row: row["creat_time"] or datetime.min, reverse=True)

    seen_target = set()
    result_list = []

    for row in engine_tasks:
        target = str(row["target"] or "").strip()
        if not target or target in seen_target:
            continue
        seen_target.add(target)

        target_count = 0
        abs_path = get_engine_asset_file_path(target)
        try:
            if os.path.isfile(abs_path):
                target_count = count_non_empty_lines(abs_path)
        except Exception:
            pass

        result_list.append({
            "target": target,
            "engine_type": row["engine_type"] or "",
            "engine_query": row["engine_query"] or "",
            "task_name": row["task_name"] or "",
            "creat_time": datetime.strftime(row["creat_time"], "%Y-%m-%d %H:%M:%S") if row["creat_time"] else "",
            "target_count": target_count,
        })

    return result_list


def clear_engine_fields(form):
    form.instance.engine_type = None
    form.instance.engine_query = None
    form.instance.engine_max_assets = None
    form.instance.engine_proxy_mode = 0
    form.instance.engine_proxy = None


def validate_engine_source_fields(form):
    engine_type = str(form.instance.engine_type or "").strip()
    engine_query = str(form.instance.engine_query or "").strip()
    engine_proxy_mode = form.instance.engine_proxy_mode
    engine_max_assets = form.instance.engine_max_assets

    if not engine_type:
        return False, {"engine_type": ["此字段为必填项"]}
    if not engine_query:
        return False, {"engine_query": ["此字段为必填项"]}

    try:
        engine_max_assets = int(engine_max_assets)
    except Exception:
        return False, {"engine_max_assets": ["请输入有效整数"]}

    if engine_max_assets <= 0:
        return False, {"engine_max_assets": ["数值必须大于 0"]}

    if engine_proxy_mode is None:
        engine_proxy_mode = 0

    if int(engine_proxy_mode) == 2 and not form.instance.engine_proxy_id:
        return False, {"engine_proxy": ["强制代理模式下必须选择代理"]}

    if int(engine_proxy_mode) != 2:
        form.instance.engine_proxy = None

    form.instance.engine_max_assets = engine_max_assets
    return True, None


def _can_reuse_engine_data(task_dict):
    target = str(task_dict.get("target") or "").strip()
    if not target or not is_engine_asset_target(target):
        return False
    return os.path.isfile(get_absolute_target_path(target))


def parse_progress_value(progress):
    try:
        return float(str(progress or "0").strip().rstrip("%"))
    except Exception:
        return 0.0


def prepare_engine_target_before_start(task_obj, is_restart=False, force_refresh=False):
    if int(task_obj.input_type or 1) != 4:
        return True, None

    progress_value = parse_progress_value(task_obj.process)
    need_refresh = any([
        is_restart and progress_value >= 100.0,
        int(task_obj.status or 3) == 1,
        force_refresh,
    ])

    target_value = str(task_obj.target or "").strip()
    target_exists = bool(target_value and os.path.isfile(get_absolute_target_path(target_value)))

    if need_refresh:
        if target_value and is_engine_asset_target(target_value):
            remove_engine_asset_file(target_value)
        task_obj.target = None
        task_obj.save(update_fields=["target"])
        target_value = ""
        target_exists = False

    if target_exists and is_engine_asset_target(target_value):
        return True, None

    try:
        relative_path = fetch_and_dump_targets(task_obj)
    except Exception as e:
        return False, str(e)

    task_obj.target = relative_path
    task_obj.save(update_fields=["target"])
    return True, None

def resolve_target_source(request, form, plugin_id, old_input_type=None, old_task_obj=None, old_engine_query=None, old_target=None, old_engine_type=None, old_search_query=None):
    try:
        input_type = int(request.POST.get("input_type", 1))
    except Exception:
        input_type = 1

    form.instance.input_type = input_type

    if input_type != 4:
        clear_engine_fields(form)

    if input_type == 1:
        form.instance.history_files = ""
        if old_input_type is None and not request.FILES.get("target"):
            return False, {"target": ["此字段为必填项"]}
        if old_input_type is not None and old_input_type != 1 and not request.FILES.get("target"):
            return False, {"target": ["此字段为必填项"]}
        return True, None

    if input_type == 2:
        zone_id = form.instance.zone_id
        targets = collect_targets_from_history_vul_assets(plugin_id, zone_id=zone_id)
        target_file = build_target_file_from_targets(targets)
        if not target_file:
            return False, {"input_type": ["未找到历史漏洞资产"]}
        form.instance.target = target_file
        form.instance.history_files = ""
        return True, None

    if input_type == 3:
        history_files = get_history_files_from_request(request)
        if not history_files:
            return False, {"history_files": ["请至少选择一个历史文件"]}
        targets = collect_targets_from_history_files(history_files)
        target_file = build_target_file_from_targets(targets)
        if not target_file:
            return False, {"history_files": ["所选文件中未找到有效目标"]}
        form.instance.target = target_file
        form.instance.history_files = ",".join(history_files)
        return True, None

    if input_type == 4:
        form.instance.history_files = ""
        is_valid, error = validate_engine_source_fields(form)
        if not is_valid:
            return False, error

        new_engine = str(form.instance.engine_type or "").strip()
        new_query = str(form.instance.engine_query or "").strip()
        previous_target = str(old_target or "").strip()
        old_engine = str(old_engine_type or "").strip()
        old_query = str(old_engine_query or "").strip()

        # If engine fields unchanged and old target file still exists, keep it.
        # This prevents unnecessary re-fetch when only unrelated params change.
        if old_input_type == 4 and old_engine == new_engine and old_query == new_query and previous_target:
            if is_engine_asset_target(previous_target):
                abs_path = get_absolute_target_path(previous_target)
                if os.path.isfile(abs_path):
                    form.instance.reuse_engine_data = True
                    return True, None

        reuse_requested = str(request.POST.get("reuse_engine_data", "")).lower() in ("true", "1", "yes")
        if reuse_requested and old_input_type == 4 and old_task_obj is not None:
            if old_engine == new_engine and old_query == new_query and previous_target and is_engine_asset_target(previous_target):
                abs_path = get_absolute_target_path(previous_target)
                if os.path.isfile(abs_path):
                    form.instance.reuse_engine_data = True
                    return True, None

        form.instance.target = None
        form.instance.reuse_engine_data = False
        return True, None

    if input_type == 5:
        engine_files = get_engine_history_files_from_request(request)
        if not engine_files:
            return False, {"history_engine_files": ["请至少选择一个历史测绘结果"]}
        targets = collect_targets_from_engine_history_files(engine_files)
        target_file = build_target_file_from_targets(targets)
        if not target_file:
            return False, {"history_engine_files": ["所选文件中未找到有效目标"]}
        form.instance.target = target_file
        form.instance.history_files = ",".join(engine_files)
        clear_engine_fields(form)
        return True, None

    if input_type == 6:
        form.instance.history_files = ""
        search_query = (request.POST.get("search_query") or "").strip()
        if not search_query:
            return False, {"search_query": ["检索语句不能为空"]}
        from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure
        from django.db.models import Max, Q
        try:
            tree = parse_condition(search_query)
        except Exception:
            return False, {"search_query": ["检索语句语法错误，请检查搜索条件"]}
        q = to_query_structure(tree)
        # 限定到任务所选 zone，防止跨区域串数据
        task_zone_id = form.instance.zone_id
        if task_zone_id:
            q = Q(zone_id=task_zone_id) & q
        qs = models.auto_scan_indentify_result.objects.filter(q)
        count = qs.count()
        if count == 0:
            return False, {"search_query": ["无匹配资产"]}
        form.instance.parsed_query = tree
        form.instance.frozen_max_id = qs.aggregate(Max('id'))['id__max']
        form.instance.last_id = 0
        if old_search_query is not None:
            old_query = (old_search_query or "").strip()
            if search_query != old_query:
                if old_task_obj.status == 2:
                    from app_cybersparker.services.task_runtime_signal_service import send_stop_signal
                    send_stop_signal('batch_scan', old_task_obj.id)
                form.instance.status = 3
                form.instance.last_id = 0
        return True, None

    return False, {"input_type": ["无效的输入类型"]}


@deny_user
def add(request):
    plugin_id = request.POST.get("plugin") or ""
    post_data = request.POST.copy()
    if 'zone_id' in post_data and 'zone' not in post_data:
        post_data['zone'] = post_data['zone_id']
    form = batch_ExpTask_ModelForm(data=post_data, files=request.FILES)
    if form.is_valid():
        if plugin_id:
            form.instance.EXP = str(plugin_id)
        form.instance.creat_time = datetime.now(timezone.utc)
        form.instance.status = 3

        is_ok, error = resolve_target_source(request, form, plugin_id)
        if not is_ok:
            return JsonResponse({"status": False, "error": error})

        form.save()
        return JsonResponse({"status": True})
    return JsonResponse({"status": False, "error": _format_form_error(form), "errors": _serialize_form_errors(form)})


def detail(request, method=None):
    uid = request.GET.get("uid")
    try:
        method = request.GET.get("method")
    except:
        pass
    if not method:
        row_dict = models.batch_EXPTask.objects.filter(id=uid).values(
            "task_name", "EXP", "run_mode", "thread_num", "sleep_time", "http_timeout", "remark", "input_type", "history_files",
            "engine_type", "engine_query", "engine_max_assets", "engine_proxy_mode", "engine_proxy",
            "reuse_engine_data", "target", "proxy",
            "search_query", "parsed_query", "frozen_max_id", "last_id",
            "exp_select_mode", "severity_filter", "tag_filter", "filter_logic",
            "task_args", "task_type", "cmd_input", "zone_id",
        ).first()
        if not row_dict:
            return JsonResponse({"status": False, "error": "数据不存在"})

        can_reuse = False
        if int(row_dict.get("input_type") or 1) == 4:
            can_reuse = _can_reuse_engine_data(row_dict)

        target_val = str(row_dict.get("target") or "")
        row_dict["target"] = os.path.basename(target_val) if "/" in target_val else target_val
        exp = str(row_dict.get("EXP") or "").strip()
        expName_list = []
        if exp and exp not in ("None", "") and int(row_dict.get("exp_select_mode") or 1) == 1:
            expID_list = [e for e in exp.split(",") if e.strip() and e.strip().isdigit()]
            for exp_id in expID_list:
                if exp_id != "all":
                    exp_dict = models.EXP.objects.filter(id=int(exp_id)).values("title", "id").first()
                    if exp_dict:
                        item = "[" + str(exp_dict["id"]) + "] " + exp_dict["title"]
                        expName_list.append(item)

        result = {
            "status": True,
            "data": row_dict,
            "expName": expName_list,
            "can_reuse_engine_data": can_reuse,
        }
        return JsonResponse(result)
    else:
        row_dict = models.batch_EXPTask.objects.filter(id=uid).values(
            "task_name", "EXP", "run_mode", "thread_num", "sleep_time", "remark", "status", "target", "input_type", "process", "pause_requested"
        ).first()
        if not row_dict:
            return JsonResponse({"status": "error", "error": "数据不存在"})
        row_dict["target"] = os.path.basename(str(row_dict.get("target") or ""))
        if row_dict["status"] == 4:
            row_dict["status"] = "pause"
        elif row_dict["status"] == 3:
            row_dict["status"] = "stop"
        elif row_dict["status"] == 2 and row_dict.get("pause_requested"):
            row_dict["status"] = "pausing"
        elif row_dict["status"] == 2:
            row_dict["status"] = "running"
        else:
            row_dict["status"] = "finish"
        result = {
            "status": "success",
            "data": row_dict
        }
        return JsonResponse(result)


@deny_user
def edit(request):
    uid = request.GET.get("uid")
    plugin_id = request.POST.get("plugin") or ""
    row_object = models.batch_EXPTask.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "数据不存在,Please refresh page and try again"})

    old_input_type = row_object.input_type
    old_engine_type = row_object.engine_type
    old_engine_query = row_object.engine_query
    old_target = row_object.target
    old_search_query = row_object.search_query
    post_data = request.POST.copy()
    if 'zone_id' in post_data and 'zone' not in post_data:
        post_data['zone'] = post_data['zone_id']
    form = batch_ExpTask_ModelForm(data=post_data, files=request.FILES, instance=row_object)
    if form.is_valid():
        if plugin_id:
            form.instance.EXP = str(plugin_id)
        form.instance.creat_time = datetime.now(timezone.utc)

        is_ok, error = resolve_target_source(
            request,
            form,
            plugin_id,
            old_input_type=old_input_type,
            old_task_obj=row_object,
            old_engine_type=old_engine_type,
            old_engine_query=old_engine_query,
            old_target=old_target,
            old_search_query=old_search_query,
        )
        if not is_ok:
            return JsonResponse({"status": False, "error": error})

        # 输入源变更时清理旧合并文件，防止 .merged/ 堆积
        new_target = str(form.instance.target or "").strip()
        old_target_str = str(old_target or "").strip()
        if new_target and new_target != old_target_str and ".merged/" in old_target_str:
            remove_target_file(old_target_str)

        form.save()
        return JsonResponse({"status": True})
    return JsonResponse({"status": False, "error": _format_form_error(form), "errors": _serialize_form_errors(form)})


def remove_target_file(file_name):
    try:
        safe_name = str(file_name or "").strip()
        if not safe_name:
            return False
        base = get_exp_input_dir()
        # Check .merged/ first (new merged files), then root (legacy)
        for sub in (".merged", ""):
            file_path = os.path.join(base, sub, os.path.basename(safe_name)) if sub else os.path.join(base, os.path.basename(safe_name))
            if os.path.isfile(file_path):
                os.remove(file_path)
                return True
        return False
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "remove_expTarget_file error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info, tips, time_str)
        return False


def history_files(request):
    if request.method != "GET":
        return JsonResponse({"status": False, "error": "请求方法不允许"})
    files = list_exp_input_files()
    return JsonResponse({"status": True, "data": {"files": files}})


@deny_user
def history_files_delete(request):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "请求方法不允许"})

    file_name = request.POST.get("file_name")
    if not file_name:
        return JsonResponse({"status": False, "error": "文件名不能为空"})

    if remove_target_file(file_name):
        return JsonResponse({"status": True})
    return JsonResponse({"status": False, "error": "文件不存在"})


def history_engine_results(request):
    if request.method != "GET":
        return JsonResponse({"status": False, "error": "请求方法不允许"})
    results = list_history_engine_results()
    return JsonResponse({"status": True, "data": {"results": results}})


def _batch_delete_merged_files(task_id):
    """清理 EXP_input/.merged/ 下匹配 *_{task_id}_* 的合并文件。"""
    import glob as _glob
    merged_dir = os.path.join(sett.THIS_DIR, "EXP_input", ".merged")
    if not os.path.isdir(merged_dir):
        return
    pattern = os.path.join(merged_dir, f"*_{task_id}_*")
    for f in _glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass


def _batch_delete_one(task_obj):
    """删除单个批量任务（含级联清理）。"""
    uid = task_obj.id
    if int(task_obj.status or 0) == 2:
        set_stop_signal("batch_scan", uid)
        models.batch_EXPTask.objects.filter(id=uid).update(stop_requested=True)
        for _ in range(30):
            row = models.batch_EXPTask.objects.filter(id=uid).values("status").first()
            if not row or row["status"] != 2:
                break
            time.sleep(1)

    _batch_delete_merged_files(uid)
    task_obj.delete()
    try:
        clear_stop_signal("batch_scan", uid)
    except Exception:
        pass


def delete(request):
    if request.method == "GET":
        uid = request.GET.get("uid")
        task_obj = models.batch_EXPTask.objects.filter(id=uid).first()
        if not task_obj:
            return JsonResponse({"status": False, "error": "删除失败，数据不存在"})
        _batch_delete_one(task_obj)
        return JsonResponse({"status": True})

    if request.method in ('POST', 'PUT', 'DELETE'):
        if get_role(request) == 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    task_operate = request.POST.get("operate")
    id_list = request.POST.getlist("contents[]")
    if task_operate == "delete":
        try:
            # 批量：先发所有停止信号
            for tid in id_list:
                task_obj = models.batch_EXPTask.objects.filter(id=tid).first()
                if task_obj and int(task_obj.status or 0) == 2:
                    set_stop_signal("batch_scan", tid)
                    models.batch_EXPTask.objects.filter(id=tid).update(stop_requested=True)
            deadline = time.time() + 30
            while time.time() < deadline:
                running = models.batch_EXPTask.objects.filter(
                    id__in=id_list, status=2
                ).count()
                if running == 0:
                    break
                time.sleep(1)
            for tid in id_list:
                task_obj = models.batch_EXPTask.objects.filter(id=tid).first()
                if not task_obj:
                    continue
                _batch_delete_merged_files(int(tid))
                task_obj.delete()
                try:
                    clear_stop_signal("batch_scan", tid)
                except Exception:
                    pass
            return JsonResponse({"status": True})
        except Exception:
            return JsonResponse(
                {"status": False, "error": "请刷新页面并选择要删除的ID"})
    elif task_operate == "start":
        return operate(request, id_list)
    else:
        return JsonResponse({"status": False, "error": "请选择要删除的ID"})
def startTask(row_dict, uid, dispatch_token=None, owner=None, force_refresh_engine=False):
    close_old_connections()
    try:
        task_obj = models.batch_EXPTask.objects.filter(id=uid).first()
    finally:
        connection.close()
    if task_obj:
        is_restart = row_dict.get('process') == "100%" or row_dict.get('process') is None
        is_ok, error = prepare_engine_target_before_start(task_obj, is_restart=is_restart, force_refresh=force_refresh_engine)
        if not is_ok:
            try:
                models.batch_EXPTask.objects.filter(id=uid).update(
                    status=1,
                    queued=False,
                    dispatch_token="",
                    owner="",
                    failed=True,
                    pause_requested=False,
                    last_error=error or "测绘引擎数据获取失败",
                    endTime=datetime.now(timezone.utc),
                )
            finally:
                connection.close()
            return None
        row_dict["target"] = str(task_obj.target or "")

    str_exp_id = row_dict.get("EXP") or ""
    target = row_dict["target"]
    run_mode = row_dict.get("run_mode", 1)
    thread_num = row_dict["thread_num"]
    sleep_time = row_dict["sleep_time"]
    progress = row_dict['process']

    startTime = datetime.now(timezone.utc)
    try:
        models.batch_EXPTask.objects.filter(id=uid).update(startTime=startTime)
    finally:
        connection.close()
    data = {
        "uid": uid,
        "exp": str_exp_id,
        "target_file": target,
        "run_mode": run_mode,
        "thread_num": thread_num,
        "sleep_time": sleep_time,
        "http_timeout": row_dict.get("http_timeout", 10),
        "progress": progress,
        "input_type": int(getattr(task_obj, "input_type", 1) or 1) if task_obj else 1,
        "search_query": getattr(task_obj, "search_query", None) if task_obj else None,
        "parsed_query": getattr(task_obj, "parsed_query", None) if task_obj else None,
        "frozen_max_id": getattr(task_obj, "frozen_max_id", 0) if task_obj else 0,
        "last_id": getattr(task_obj, "last_id", 0) if task_obj else 0,
        "dispatch_token": dispatch_token,
        "owner": owner,
        "proxy": task_obj.proxy_id if task_obj else None,
        "task_type": row_dict.get("task_type", 1),
        "cmd_input": row_dict.get("cmd_input") or "",
        "exp_select_mode": int(getattr(task_obj, "exp_select_mode", 1) or 1) if task_obj else 1,
        "severity_filter": getattr(task_obj, "severity_filter", None) if task_obj else None,
        "tag_filter": getattr(task_obj, "tag_filter", None) if task_obj else None,
        "filter_logic": getattr(task_obj, "filter_logic", "AND") if task_obj else "AND",
        "task_args": getattr(task_obj, "task_args", None) if task_obj else None,
        "zone_id": task_obj.zone_id if task_obj else None,
    }

    try:
        data["task_args"] = json.loads(data.get("task_args") or "{}")
    except Exception:
        logging.warning("task_args JSON parse failed for batch task %s", uid)
        data["task_args"] = {}

    try:
        normalized_run_mode = int(run_mode)
    except Exception:
        normalized_run_mode = 1

    uid_key = str(uid)
    if normalized_run_mode == 2:
        current_process = multiprocessing.current_process()
        if getattr(current_process, "daemon", False):
            data["run_mode"] = 1
            exp_thread = batch_exec.Task_handler(data)
            sett.BATH_TASK_DIC[uid_key] = exp_thread
            exp_thread.start()
            return exp_thread
        ctx = multiprocessing.get_context("spawn")
        pause_val = multiprocessing.Value('b', False)
        stop_val = multiprocessing.Value('b', False)
        data["_pause_requested"] = pause_val
        data["_stop_requested"] = stop_val
        process = ctx.Process(target=run_gevent_task_in_subprocess, args=(data,), daemon=True)
        runner = ProcessTaskKiller(process, pause_requested=pause_val, stop_requested=stop_val)
        sett.BATH_TASK_DIC[uid_key] = runner
        process.start()
        return runner
    exp_thread = batch_exec.Task_handler(data)
    sett.BATH_TASK_DIC[uid_key] = exp_thread
    exp_thread.start()
    return exp_thread

@deny_user
def operate(request, uid_list=None):
    def resolve_exp_ids(row_dict):
        # 筛选模式：EXP 由引擎运行时按条件动态解析，无需从 EXP 字段校验
        if int(row_dict.get("exp_select_mode") or 1) == 2:
            return "__filter__"
        exp_raw = str(row_dict.get("EXP") or "").strip()
        # 空 EXP 等同于全选（兼容 React 编辑遗留的空 EXP 字段）
        if exp_raw in ("all", ""):
            if not models.EXP.objects.exists():
                return None
            return "all"
        exp_id_list = [item.strip() for item in exp_raw.split(",") if item.strip().isdigit()]
        if not exp_id_list:
            return None
        matching_ids = models.EXP.objects.filter(id__in=exp_id_list).values_list('id', flat=True)
        exist_exp_id = ",".join(str(item) for item in matching_ids)
        if not exist_exp_id:
            return None
        return exist_exp_id

    def enqueue_batch_task(uid, row_dict, reset_process, force_refresh_engine=False):
        dispatch_token = uuid4().hex
        update_kwargs = {
            "status": 2,
            "startTime": datetime.now(timezone.utc),
            "endTime": None,
            "pause_requested": False,
            "stop_requested": False,
        }
        if reset_process:
            update_kwargs["process"] = "0%"
        if int(task_obj.input_type or 1) == 6 and reset_process:
            update_kwargs["last_id"] = 0
        models.batch_EXPTask.objects.filter(id=uid).update(**update_kwargs)
        initialize_task_runtime(models.batch_EXPTask, uid, dispatch_token, None, queued=True)
        clear_stop_signal("batch_scan", uid)
        clear_pause_signal("batch_scan", uid)
        try:
            try:
                normalized_run_mode = int(row_dict.get("run_mode", 1))
            except Exception:
                normalized_run_mode = 1
            queue_name = "batch_scan_gevent" if normalized_run_mode == 2 else "batch_scan"
            dispatch_task(run_batch_scan_task, int(uid), dispatch_token, force_refresh_engine=force_refresh_engine, queue=queue_name)
        except Exception:
            models.batch_EXPTask.objects.filter(id=uid).update(
                status=3,
                queued=False,
                failed=True,
                last_error="任务派发失败",
                endTime=datetime.now(timezone.utc),
            )
            raise
        return dispatch_token

    if uid_list:
        success_count = 0
        error_list = []
        for uid in uid_list:
            task_obj = models.batch_EXPTask.objects.filter(id=uid).first()
            if not task_obj:
                error_list.append(str(uid))
                continue
            row_dict = models.batch_EXPTask.objects.filter(id=uid).values(
                "task_name", "EXP", "run_mode", "thread_num", "sleep_time", "target",
                "creat_time", "status", "process", "startTime", "endTime", "remark",
                "exp_select_mode"
            ).first()
            exist_exp_id = resolve_exp_ids(row_dict)
            if not exist_exp_id:
                error_list.append(str(uid))
                continue
            row_dict["EXP"] = exist_exp_id
            try:
                enqueue_batch_task(uid, row_dict, reset_process=True)
                success_count += 1
            except Exception:
                error_list.append(str(uid))
        if success_count > 0:
            tips = f"start {success_count} task success"
            if error_list:
                tips = tips + "; failed ids: " + ",".join(error_list)
            return JsonResponse({"status": True, "tips": tips, "error_uids": error_list})
        return JsonResponse({"status": False, "error": "启动任务失败", "error_uids": error_list})

    uid = request.POST.get("uid")
    status = request.POST.get("status")
    task_obj = models.batch_EXPTask.objects.filter(id=uid).first()
    if not task_obj:
        return JsonResponse({"status": False, "error": "数据不存在"})

    row_dict = models.batch_EXPTask.objects.filter(id=uid).values(
        "task_name", "EXP", "run_mode", "thread_num", "sleep_time", "status",
        "target", "process", "startTime", "endTime", "remark", "exp_select_mode"
    ).first()

    if status == "pause":
        row = models.batch_EXPTask.objects.filter(id=uid).values(
            "heartbeat_at", "status", "owner", "endTime", "queued", "pause_requested",
        ).first()
        if not row or row["status"] != 2 or row["endTime"] is not None:
            return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})

        from django.conf import settings
        heartbeat_sec = int(getattr(settings, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", 10))
        stale_at = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_sec * 3)
        is_alive = bool(row["owner"]) and row["heartbeat_at"] is not None and row["heartbeat_at"] >= stale_at

        if is_alive and not row["pause_requested"]:
            updated = models.batch_EXPTask.objects.filter(id=uid, status=2).update(pause_requested=True)
            if not updated:
                return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})
            set_pause_signal("batch_scan", uid)
            return JsonResponse({"status": True, "tips": "暂停信号已发送"})

        updated = models.batch_EXPTask.objects.filter(id=uid, status=2).update(
            status=4,
            queued=False,
            pause_requested=False,
            stop_requested=False,
            last_error="executor lost (server restarted)" if not is_alive else "executor not found",
            endTime=datetime.now(timezone.utc),
        )
        if not updated:
            return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})
        clear_pause_signal("batch_scan", uid)
        clear_stop_signal("batch_scan", uid)
        return JsonResponse({"status": True, "tips": "任务已暂停（executor 已丢失）"})

    # exp_select_mode=2（按条件筛选）或已配置过 severity/tag 过滤条件时，不依赖 EXP 字段
    if int(task_obj.exp_select_mode or 1) == 2 or (task_obj.severity_filter or task_obj.tag_filter):
        exist_exp_id = "__filter__"
    else:
        exist_exp_id = resolve_exp_ids(row_dict)
        if not exist_exp_id:
            return JsonResponse({"status": False, "error": "插件已被删除"})
    row_dict["EXP"] = exist_exp_id

    force_refresh_engine = False
    if int(task_obj.input_type or 1) == 4:
        if status == "0":
            force_refresh_engine = True
        elif status == "1":
            reuse_val = str(request.POST.get("reuse_engine_data", "true")).lower()
            force_refresh_engine = reuse_val not in ("true", "1", "yes")

    if status == "0":
        enqueue_batch_task(uid, row_dict, reset_process=True, force_refresh_engine=force_refresh_engine)
        return JsonResponse({"status": True, "tips": "启动任务成功"})
    elif status == "1":
        enqueue_batch_task(uid, row_dict, reset_process=True, force_refresh_engine=force_refresh_engine)
        return JsonResponse({"status": True, "tips": "re启动任务成功"})
    elif status in ("3", "resume"):
        reset_process = status != "resume" and request.POST.get("action", "") != "resume"
        enqueue_batch_task(uid, row_dict, reset_process=reset_process, force_refresh_engine=force_refresh_engine)
        tips = "续跑任务成功"
        return JsonResponse({"status": True, "tips": tips})
    return JsonResponse({"status": False, "error": "启动任务失败"})

def task_result(request, uid):
    info_dict = request.session.get("info")
    if not info_dict:
        return HttpResponse(status=404)
    task_name = models.batch_EXPTask.objects.filter(id=uid).values("task_name").first()
    Task_name = task_name["task_name"]
    plugin_list = []
    data_dice = models.batch_EXPTask.objects.filter(id=uid).values("EXP", "exp_select_mode", "severity_filter", "tag_filter", "filter_logic").first()
    if data_dice:
        exp_sel_mode = int(data_dice.get("exp_select_mode") or 1)
        if exp_sel_mode == 2:
            # 筛选模式：用过滤条件动态查询插件列表
            from app_cybersparker.views.expload.task_manage.batch_task_executor import resolve_exp_filter
            exp_qs = resolve_exp_filter(
                data_dice.get("severity_filter"),
                data_dice.get("tag_filter"),
                data_dice.get("filter_logic", "AND"),
            )
            plugin_obj = exp_qs.values("CVE", "title")
        else:
            exp_id = data_dice.get("EXP") or ""
            exp_id_list = [item.strip() for item in exp_id.split(",") if item.strip().isdigit()]
            plugin_obj = models.EXP.objects.filter(id__in=exp_id_list).values("CVE", "title") if exp_id_list else models.EXP.objects.none()
        plugin_list = []
        for obj in plugin_obj:
            cve = obj["CVE"]
            title = obj["title"]
            plugin = "[" + cve + "]" + title
            plugin_list.append(plugin)

    search_dict = {}
    for key, value in request.GET.items():
        if key !="searchInfo" and value and key not in {"page", "per_page", "rows_per_page"}:
            search_dict[key] = value
    _query = Q()

    for key, value in search_dict.items():
        if value is not None:  
            if key == "id" or (key == "plugin_name" and value !="all"):  # 完全匹配的字段
                _query &= Q(**{key: value})
            else:  # 模糊匹配的字段
                if key == "plugin_name" and value =="all":
                    pass
                else:   
                    _query &= Q(**{key + '__icontains': value})
    if search_dict:
        queryset = models.EXPTask_result.objects.filter(_query, task_id=uid, task_type=2).values("id","plugin_name","target","creatime")
    else:
        queryset = models.EXPTask_result.objects.filter(task_id=uid, task_type=2).order_by("-id").values("id","plugin_name","target","creatime")

    page_object = Pagination(request, queryset)
    context = {
        "plugin_list":plugin_list,
        "task_name": Task_name,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_dict
    }
    return render(request, 'project/expload/task_manage/bath_exp_task_result.html', context)

def Result_delete(request):
    if request.method == "GET":
        uid = request.GET.get("uid")
        models.EXPTask_result.objects.filter(id=uid, task_type=2).delete()
        return JsonResponse({"status": True})

    if request.method in ('POST', 'PUT', 'DELETE'):
        if get_role(request) == 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    # batch delete
    operate = request.POST.get("operate")
    id_list = request.POST.getlist("contents[]")
    if operate == "batch_delete":
        try:
            models.EXPTask_result.objects.filter(id__in=id_list, task_type=2).delete()
            return JsonResponse({"status": True})
        except Exception:
            return JsonResponse(
                {"status": False, "error": "请刷新页面并选择要删除的ID"})
    else:
        return JsonResponse({"status": False, "error": "请选择要删除的ID"})

def exp_detail(request):
    uid = request.GET.get("uid")
    data_dice = models.batch_EXPTask.objects.filter(id=uid).values("EXP").first()
    if data_dice:
        exp_id = data_dice["EXP"] or ""
        exp_id_list = [e for e in exp_id.split(",") if e.strip().isdigit()]
        if not exp_id_list:
            return JsonResponse({"status": True, "data": []})
        queryset = models.EXP.objects.filter(id__in=exp_id_list).values("id", "CVE", "title", "plugin_language", "Type")
        mapping_rules = [
            When(plugin_language=1, then=Value('python3')),
            When(plugin_language=2, then=Value('nuclei_yaml')),
        ]
        type_mapping = [
            When(Type=1, then=Value('Command Execute')),
            When(Type=2, then=Value('Code Execute')),
            When(Type=3, then=Value('sql inject')),
            When(Type=4, then=Value('information leakage')),
            When(Type=5, then=Value('File upload')),
            When(Type=6, then=Value('File Reading')),
            When(Type=7, then=Value('Directory Traversal')),
            When(Type=8, then=Value('Cross-site request forgery')),
            When(Type=9, then=Value('Identity bypass')),
            When(Type=10, then=Value('weak password')),
            When(Type=11, then=Value('Path leakage')),
            # When(~Q(Type=1), then=Value('KK')),   # Type != 1
            # When(Q(Type=1) | Q(Type=2), then=Value('KK')),  # Type=1 or Type=2
            # When(Q(Type__ne=1) | Q(Type__ne=2), then=Value('KK')),   # Type!=1 or Type!=2
        ]
        mapped_queryset = queryset.annotate(
            mapped_Type=Case(*type_mapping, output_field=CharField()),
            mapped_plugin_language=Case(*mapping_rules, output_field=CharField()),
        ).values("id", "CVE", "title", "mapped_plugin_language", "mapped_Type")
        data = list(mapped_queryset)
        if data:
            return JsonResponse({"status": True, "data": data})
        return JsonResponse({"status": False, "error": "插件已被删除"})
    else:
        return JsonResponse({"status": False, "error": "请选择要删除的ID"})
    
def get_pligun_name(plugin_obj):
    return resolve_exp_by_name(plugin_obj)

def operate_result(request):
    plugin = str(request.GET.get("plugin"))
    exp_obj = get_pligun_name(plugin)
    if  exp_obj:
        obj = models.cveExtensions.objects.filter(CVE=exp_obj).values("function")
        function_list = []  # 功能列表
        for data in obj:
            function = data["function"]
            function_list.append(function)
        return JsonResponse({"status": True, "function_list": function_list})
    return JsonResponse({"status": False,"data":"未找到插件"})

@deny_user
def TaskResult_verify(request):
    try:
        target = request.POST.get("target")
        model = request.POST.get("model")
        plugin = request.POST.get("use_plugin")
        exp_obj = get_pligun_name(plugin)
        if not exp_obj:
            return JsonResponse({"status": False, "data": "未找到插件"})
        try:
            cmd = request.POST.get("cmd")
        except:
            cmd = ""

        exp = load_runtime_module_from_poc(exp_obj.poc, exp_id=exp_obj.id)
        result = call_runtime_method(exp, model, {"target": target, "task_args": {}}, cmd)
        if result:
            return JsonResponse({"status": True, "data": result})
        else:
            return JsonResponse({"status": False, "data": "验证失败"})
    except:
        return JsonResponse({"status": False, "data": str(traceback.format_exc())})
    
def Result_detail(request):
    uid = request.GET.get("uid")
    result_data =  models.EXPTask_result.objects.filter(id=uid, task_type=2).values("result").first()
    if uid and result_data:
        exp_result = result_data["result"]
        result = {"status": True,"data": exp_result}
        return JsonResponse(result)
    return JsonResponse({"status": False, "data": "数据不存在"})