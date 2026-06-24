import json
import logging
from datetime import datetime
import os
import time
import uuid
from threading import Thread
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.db.models import Q

from app_cybersparker.permissions import deny_user, get_role
from app_cybersparker.services.celery_runtime_service import dispatch_task
from app_cybersparker.services.cyberspace_engine_service import fetch_and_dump_targets, get_engine_asset_file_path, is_engine_asset_target, remove_engine_asset_file, get_absolute_target_path
from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal, set_pause_signal, set_stop_signal
from app_cybersparker.services.task_state_cas_service import initialize_task_runtime
from app_cybersparker.tasks import run_auto_scan_task
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.conf import settings
from django.http import JsonResponse
import cybersparker.settings as sett
import app_cybersparker.views.expload.task_manage.auto_exp_task as auto_exp_task
from django.utils import timezone

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
    bootstrap_exclude_fields = ['target']

    class Meta:
        model = models.auto_scan_tasks
        fields = ["task_name", "thread_num", "vulnerability_thread_num", "sleep_time", "http_timeout", "input_type",
                  "search_query",
                  "history_files", "target", "engine_type", "engine_query", "engine_max_assets",
                  "engine_proxy_mode", "engine_proxy",
                  "Vulnerability_scanning", "proxy", "remark", "task_args",
                  "fscanx_file", "conflict_strategy", "zone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vulnerability_thread_num"].required = False
        self.fields["vulnerability_thread_num"].initial = 40
        self.fields["zone"].required = False

    def clean_thread_num(self):
        thread_num = self.cleaned_data.get('thread_num')
        if thread_num and thread_num > settings.MAX_EXPLOIT_THREAD_NUM:
            raise ValidationError(f'线程数不能超过 {settings.MAX_EXPLOIT_THREAD_NUM}')
        return thread_num

    def clean_vulnerability_thread_num(self):
        vulnerability_thread_num = self.cleaned_data.get('vulnerability_thread_num')
        if vulnerability_thread_num in (None, ""):
            return 40
        if vulnerability_thread_num > settings.MAX_EXPLOIT_THREAD_NUM:
            raise ValidationError(f'漏洞扫描线程数不能超过 {settings.MAX_EXPLOIT_THREAD_NUM}')
        if vulnerability_thread_num < 1:
            raise ValidationError('漏洞扫描线程数不能小于 1')
        return vulnerability_thread_num

def _format_form_error(form):
    """Django form.errors → 单行可读字符串。"""
    parts = []
    for field, messages in form.errors.items():
        msgs = messages if isinstance(messages, (list, tuple)) else [messages]
        for m in msgs:
            label = form.fields.get(field, {}).label or field
            parts.append(f"{label}: {m}" if hasattr(form.fields.get(field), 'label') else f"{field}: {m}")
    return "; ".join(parts) if parts else "表单校验失败"


def _serialize_form_errors(form):
    """Django form.errors → {field_name: first_error_message} 平坦 dict。"""
    result = {}
    for field, messages in form.errors.items():
        msgs = messages if isinstance(messages, (list, tuple)) else [messages]
        result[field] = msgs[0] if msgs else ""
    return result


def get_exp_input_dir():
    return os.path.dirname(os.path.abspath(pwd)).replace("\\", "/") + "/EXP_input"


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

    unique_filename = f"{uuid.uuid4().hex}.txt"
    relative_path = f"EXP_input/.merged/{unique_filename}"
    full_path = os.path.join(get_merged_dir(), unique_filename)
    with open(full_path, "w", encoding="utf-8", errors="ignore") as file_obj:
        file_obj.write("\n".join(unique_targets))
    return relative_path


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


def list_history_engine_results():
    from app_cybersparker.views.expload.task_manage.batch_exp_task import list_history_engine_results as _batch_list
    return _batch_list()


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

    print(f"[DEBUG engine] prepare_engine_target_before_start: is_restart={is_restart}, force_refresh={force_refresh}, progress={progress_value}, status={task_obj.status}, need_refresh={need_refresh}")

    target_value = str(task_obj.target or "").strip()
    target_exists = bool(target_value and os.path.isfile(get_absolute_target_path(target_value)))
    print(f"[DEBUG engine] prepare_engine_target_before_start: target={target_value!r}, target_exists={target_exists}")

    if need_refresh:
        if target_value and is_engine_asset_target(target_value):
            print(f"[DEBUG engine] prepare_engine_target_before_start: REFRESH — deleting old engine file: {target_value}")
            remove_engine_asset_file(target_value)
        task_obj.target = None
        task_obj.save(update_fields=["target"])
        target_value = ""
        target_exists = False

    if target_exists and is_engine_asset_target(target_value):
        print(f"[DEBUG engine] prepare_engine_target_before_start: REUSE — file exists, skipping fetch")
        return True, None

    print(f"[DEBUG engine] prepare_engine_target_before_start: FETCH — calling fetch_and_dump_targets()")
    try:
        relative_path = fetch_and_dump_targets(task_obj)
    except Exception as e:
        print(f"[DEBUG engine] prepare_engine_target_before_start: FETCH FAILED — {e}")
        return False, str(e)

    task_obj.target = relative_path
    task_obj.save(update_fields=["target"])
    print(f"[DEBUG engine] prepare_engine_target_before_start: FETCH OK — new target={relative_path!r}")
    return True, None


def resolve_target_source(request, form, old_input_type=None, old_task_obj=None, old_engine_type=None, old_engine_query=None, old_target=None, old_search_query=None):
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

        # If engine fields unchanged and old target file still exists, keep it
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
        from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure, _has_deep_search
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
                if old_task_obj.status in (2, 4):
                    from app_cybersparker.services.task_runtime_signal_service import send_stop_signal
                    send_stop_signal('auto_scan', old_task_obj.id)
                form.instance.status = 3
                form.instance.last_id = 0
        return True, None

    if input_type == 2:
        form.instance.history_files = ""
        if not request.FILES.get("fscanx_file"):
            if old_input_type is None:
                return False, {"fscanx_file": ["请上传 fscanx 输出文件"]}
            if old_input_type != 2:
                return False, {"fscanx_file": ["请上传 fscanx 输出文件"]}
        return True, None

    return False, {"input_type": ["无效的输入类型"]}


def task_list_view(request):
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.auto_scan_tasks.objects.filter(Q(task_name__icontains=search_data))
    else:
        queryset = models.auto_scan_tasks.objects.all().order_by("-id")
    form = ModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data
    }
    return render(request, 'project/expload/task_manage/auto_scan_task_list.html', context)

@deny_user
def add(request):
    try:
        # 前端表单发送的是 zone_id（AssetZone 的主键），但 Django ModelForm
        # 的字段名是 zone（ForeignKey 字段名）。不映射的话 zone 不会被填充，
        # ModelForm 会把 instance.zone 设为 None，然后模型 save() 的兜底
        # 逻辑会静默改为公网（id=1），导致用户选的区域被丢弃。
        post_data = request.POST.copy()
        if 'zone_id' in post_data and 'zone' not in post_data:
            post_data['zone'] = post_data['zone_id']
        form = ModelForm(data=post_data, files=request.FILES)
        if form.is_valid():
            form.instance.creat_time = timezone.now()
            form.instance.status = 3

            # 测绘引擎输入源强制 zone=public
            input_type = int(request.POST.get("input_type", 1))
            if input_type in (4, 5):
                from app_cybersparker.models import AssetZone
                form.instance.zone = AssetZone.objects.get(code="public")

            is_ok, error = resolve_target_source(request, form)
            if not is_ok:
                return JsonResponse({"status": False, "error": error})

            form.save()
            resp = {"status": True}
            if form.instance.fscanx_file:
                resp["fscanx_file"] = form.instance.fscanx_file.name
            if form.instance.target:
                resp["target"] = form.instance.target.name.split("/")[-1] if "/" in (form.instance.target.name or "") else (form.instance.target.name or "")
            return JsonResponse(resp)
        return JsonResponse({"status": False, "error": _format_form_error(form), "errors": _serialize_form_errors(form)})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "expload_add error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "添加任务失败"})
    
@deny_user
def edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.auto_scan_tasks.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
        old_input_type = row_object.input_type
        old_engine_type = row_object.engine_type
        old_engine_query = row_object.engine_query
        old_target = row_object.target
        old_search_query = row_object.search_query
        # 前端表单发送的是 zone_id（AssetZone 的主键），但 Django ModelForm
        # 的字段名是 zone（ForeignKey 字段名）。不映射的话 zone 不会被填充，
        # ModelForm 会把 instance.zone 设为 None，然后模型 save() 的兜底
        # 逻辑会静默改为公网（id=1），导致用户选的区域被丢弃。
        post_data = request.POST.copy()
        if 'zone_id' in post_data and 'zone' not in post_data:
            post_data['zone'] = post_data['zone_id']
        form = ModelForm(data=post_data, files=request.FILES, instance=row_object)
        if form.is_valid():
            # 测绘引擎输入源强制 zone=public
            input_type = int(request.POST.get("input_type", 1))
            if input_type in (4, 5):
                from app_cybersparker.models import AssetZone
                form.instance.zone = AssetZone.objects.get(code="public")

            is_ok, error = resolve_target_source(
                request,
                form,
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
                remove_target_file(old_target_str.split("EXP_input/")[1] if "EXP_input/" in old_target_str else old_target_str)

            form.save()
            resp = {"status": True}
            if form.instance.fscanx_file:
                resp["fscanx_file"] = form.instance.fscanx_file.name
            if form.instance.target:
                resp["target"] = form.instance.target.name.split("/")[-1] if "/" in (form.instance.target.name or "") else (form.instance.target.name or "")
            return JsonResponse(resp)
        return JsonResponse({"status": False, "error": _format_form_error(form), "errors": _serialize_form_errors(form)})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "Identify_tasks_edit error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": False, "tips": "编辑任务失败"})

def remove_target_file(file_name):
    target_path = get_absolute_target_path(os.path.join("EXP_input", str(file_name or "").strip()))
    if not target_path:
        return
    try:
        if os.path.exists(target_path):
            os.remove(target_path)
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "remove_expTarget_file error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return


def _delete_merged_files_for_task(task_id):
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


def _wait_for_executor_stop(task_model, task_id, stream_name, timeout=30):
    """写停止信号并等待执行器退出，返回 True 表示已停止。"""
    set_stop_signal(stream_name, task_id)
    task_model.objects.filter(id=task_id).update(stop_requested=True)
    for _ in range(timeout):
        row = task_model.objects.filter(id=task_id).values("status").first()
        if not row or row["status"] != 2:
            return True
        time.sleep(1)
    return False


def _can_delete_asset(asset_id):
    """四项引用全部为空时，资产才允许物理删除。"""
    return (
        not models.AssetTaskRelation.objects.filter(identify_result_id=asset_id).exists()
        and not models.AssetRootBinding.objects.filter(identify_result_id=asset_id).exists()
        and not models.auto_scan_directory_result.objects.filter(root_identify_result_id=asset_id).exists()
        and not models.auto_scan_exp_result.objects.filter(identify_result_id=asset_id).exists()
    )


def _delete_orphan_assets(asset_ids):
    """删掉没有剩余引用的资产（四重引用检查）。"""
    if not asset_ids:
        return
    for aid in asset_ids:
        if _can_delete_asset(aid):
            models.auto_scan_indentify_result.objects.filter(id=aid).delete()


def _delete_auto_scan_task(task_obj):
    """删除单个自动扫描任务（含级联清理）。"""
    uid = task_obj.id
    status = int(task_obj.status or 0)

    # 1. 运行中 → 写停止信号并等待
    if status == 2:
        _wait_for_executor_stop(models.auto_scan_tasks, uid, "auto_scan")

    # 2. 清理 .merged/ 合并文件（不删输入文件）
    _delete_merged_files_for_task(uid)

    # 3. 记录关联的资产 ID（用于后续孤立检查）
    asset_ids = list(
        models.AssetTaskRelation.objects.filter(task_id=uid)
        .values_list("identify_result_id", flat=True)
    )

    # 4. 删关联表
    models.AssetTaskRelation.objects.filter(task_id=uid).delete()

    # 5. 删任务行
    task_obj.delete()

    # 6. 清理 Redis 信号
    try:
        clear_stop_signal("auto_scan", uid)
    except Exception:
        pass

    # 7. 删孤立资产
    _delete_orphan_assets(asset_ids)


@deny_user
def delete(request):
    import time as _time
    if request.method == "GET":
        uid = request.GET.get("uid")
        task_obj = models.auto_scan_tasks.objects.filter(id=uid).first()
        if not task_obj:
            return JsonResponse({"status": False, "error": "删除失败，数据不存在"})
        _delete_auto_scan_task(task_obj)
        return JsonResponse({"status": True})

    if request.method in ('POST', 'PUT', 'DELETE'):
        if get_role(request) == 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    task_operate = request.POST.get("operate")
    id_list = request.POST.getlist("contents[]") or request.POST.getlist("contents")
    if task_operate != "delete":
        return JsonResponse({"status": False, "error": "请选择要删除的ID"})
    if len(id_list) == 0:
        return JsonResponse({"status": False, "error": "未选中任何项"})

    try:
        # 批量：先发所有停止信号
        for tid in id_list:
            task_obj = models.auto_scan_tasks.objects.filter(id=tid).first()
            if task_obj and int(task_obj.status or 0) == 2:
                set_stop_signal("auto_scan", tid)
                models.auto_scan_tasks.objects.filter(id=tid).update(stop_requested=True)
        # 统一等待
        deadline = _time.time() + 30
        while _time.time() < deadline:
            running = models.auto_scan_tasks.objects.filter(
                id__in=id_list, status=2
            ).count()
            if running == 0:
                break
            _time.sleep(1)

        for tid in id_list:
            task_obj = models.auto_scan_tasks.objects.filter(id=tid).first()
            if not task_obj:
                continue
            _delete_merged_files_for_task(int(tid))
            asset_ids = list(
                models.AssetTaskRelation.objects.filter(task_id=tid)
                .values_list("identify_result_id", flat=True)
            )
            models.AssetTaskRelation.objects.filter(task_id=tid).delete()
            task_obj.delete()
            try:
                clear_stop_signal("auto_scan", tid)
            except Exception:
                pass
            _delete_orphan_assets(asset_ids)
        return JsonResponse({"status": True})
    except Exception:
        return JsonResponse({"status": False, "error": "请刷新页面并选择要删除的ID"})

def detail(request):
    uid = request.GET.get("uid")
    row_dict = models.auto_scan_tasks.objects.filter(id=uid).values(
        "task_name", "thread_num", "vulnerability_thread_num", "sleep_time", "http_timeout", "remark",
        "Vulnerability_scanning", "proxy", "input_type", "history_files",
        "engine_type", "engine_query", "engine_max_assets", "engine_proxy_mode",
        "engine_proxy", "reuse_engine_data", "target",
        "search_query", "parsed_query", "frozen_max_id", "last_id",
    ).first()
    if not row_dict:
        return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})

    can_reuse = False
    if int(row_dict.get("input_type") or 1) == 4:
        can_reuse = _can_reuse_engine_data(row_dict)

    row_dict.pop("target", None)
    result = {
        "status": True,
        "data": row_dict,
        "can_reuse_engine_data": can_reuse,
    }
    return JsonResponse(result)

def Task_all_info(request):
    try:
        uid = request.GET.get("uid")
        row_dict = models.auto_scan_tasks.objects.filter(id=uid).values("task_name","thread_num","vulnerability_thread_num","sleep_time","http_timeout","target","creat_time","status","process","phase","pause_requested","queued","startTime","endTime","remark","Vulnerability_scanning","proxy","input_type","fscanx_file","conflict_strategy","history_files","search_query","engine_type","engine_query","engine_max_assets","engine_proxy_mode","engine_proxy_id","task_args").first()
        if not row_dict:
            return JsonResponse({"status": "error", "error": "数据不存在"})
        target_val = row_dict.get("target") or ""
        row_dict["target"] = target_val.split("/")[-1] if "/" in target_val else target_val
        fscanx_val = row_dict.get("fscanx_file") or ""
        row_dict["fscanx_file"] = fscanx_val.split("/")[-1] if "/" in fscanx_val else fscanx_val
        if row_dict["status"] == 3:
            row_dict["status"] = "stop"
        elif row_dict["status"] == 2 and row_dict.get("queued"):
            row_dict["status"] = "waiting"
        elif row_dict["status"] == 2:
            row_dict["status"] = "running"
        elif row_dict["status"] == 4:
            row_dict["status"] = "pause"
        else:
            row_dict["status"] = "finish"
        result = {
            "status": "success",
            "data": row_dict
        }
        return JsonResponse(result)
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "get Task_all_info error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        return JsonResponse({"status": "error", "error": str(e)})
    
@deny_user
def reset(request):
    uid = request.POST.get("uid")
    if models.auto_scan_tasks.objects.filter(id=uid).exists():
        models.auto_scan_tasks.objects.filter(id=uid).update(current_line=1)
        result = {"status": True}
        return JsonResponse(result)
    else:
        result = {"status": False,"error":"数据不存在"}
        return JsonResponse(result) 

def startTask(row_dict,uid, dispatch_token=None, owner=None, skip_engine_prepare=False):
    close_old_connections()
    try:
        task_obj = models.auto_scan_tasks.objects.filter(id=uid).first()
    finally:
        connection.close()
    if task_obj and not skip_engine_prepare and int(task_obj.Vulnerability_scanning or 0) != 2:
        restart_flag = row_dict.get('process') == "100%" or row_dict.get('process') is None
        is_ok, error = prepare_engine_target_before_start(task_obj, is_restart=restart_flag)
        if not is_ok:
            try:
                models.auto_scan_tasks.objects.filter(id=uid).update(
                    status=1,
                    queued=False,
                    dispatch_token="",
                    owner="",
                    failed=True,
                    last_error=error or "测绘引擎数据获取失败",
                    endTime=timezone.now(),
                )
            finally:
                connection.close()
            return None
        row_dict["target"] = str(task_obj.target or "")
        row_dict["current_line"] = int(task_obj.current_line or 1)
    row_dict["task_id"] = uid
    row_dict["zone_id"] = task_obj.zone_id if task_obj else row_dict.get("zone_id")
    row_dict["dispatch_token"] = dispatch_token
    row_dict["owner"] = owner
    try:
        row_dict["task_args"] = json.loads(row_dict.get("task_args") or "{}")
    except Exception:
        logging.warning("task_args JSON parse failed for auto_scan task %s", uid)
        row_dict["task_args"] = {}
    proxy_id = row_dict["proxy"]
    try:
        proxy_dict = models.ProxySetting.objects.filter(id=proxy_id).values("proxy_type", "proxy_address", "proxy_port").first()
        if proxy_dict:
            proxy_type = proxy_dict["proxy_type"]
            protocol_type_str = models.ProxySetting(proxy_type=proxy_type).get_proxy_type_display()
            proxy_dict["proxy_type"] = protocol_type_str
        else:
            proxy_dict={}
    finally:
        connection.close()
    row_dict["proxy"] = proxy_dict
    scanner_instance = auto_exp_task.Auto_exploit_Task_handler(row_dict)
    uid_key = str(uid)
    sett.KILL_AUTO_TASK_DIC[uid_key] = scanner_instance
    try:
        scanner_instance.start()
        scanner_instance.join()
    finally:
        sett.KILL_AUTO_TASK_DIC.pop(uid_key, None)
    if dispatch_token is None and scanner_instance.is_over:
        try:
            models.auto_scan_tasks.objects.filter(id=uid).update(status=1, process="100%", endTime=timezone.now(), pause_requested=False)
        finally:
            connection.close()
    return scanner_instance

def history_files(request):
    from app_cybersparker.views.expload.task_manage.batch_exp_task import list_exp_input_files
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
    from app_cybersparker.views.expload.task_manage.batch_exp_task import list_history_engine_results
    results = list_history_engine_results()
    return JsonResponse({"status": True, "data": {"results": results}})


@deny_user
def Task_operate(request,uid_list=None):
    uid = request.POST.get("uid")
    status = request.POST.get("status")
    row_dict = models.auto_scan_tasks.objects.filter(id=uid).values("task_name","target","Vulnerability_scanning","thread_num","vulnerability_thread_num","sleep_time","http_timeout","creat_time","status","startTime","endTime","remark","current_line","proxy","input_type").first()
    startTime = timezone.now()
    input_type_val = int(row_dict.get("input_type") or 1)

    if status in {"0", "1", "resume", "rerun"}:
        # ---- fscanx 导入：走线程，不走 Celery ----
        if input_type_val == 2:
            if status == "resume":
                return JsonResponse({"status": False, "error": "fscanx 导入不支持续跑"})
            if status == "1":
                return JsonResponse({"status": False, "error": "fscanx 导入不支持此操作，请用重跑"})
            try:
                models.auto_scan_tasks.objects.filter(id=uid).update(
                    status=2,
                    startTime=startTime,
                    endTime=None,
                    process="0%",
                    stop_requested=False,
                    failed=False,
                    last_error="",
                )
                connection.close()
                from threading import Thread
                from app_cybersparker.services.fscanx_parser import run_import
                t = Thread(target=run_import, args=(models.auto_scan_tasks.objects.get(id=uid),), daemon=True)
                t.start()
                return JsonResponse({"status": True, "tips": "fscanx 导入已开始"})
            except Exception as exc:
                try:
                    models.auto_scan_tasks.objects.filter(id=uid).update(
                        status=3, failed=True, last_error=str(exc), endTime=timezone.now(),
                    )
                finally:
                    connection.close()
                return JsonResponse({"status": False, "error": str(exc)})

        dispatch_token = uuid.uuid4().hex
        vuln_mode = int(row_dict.get("Vulnerability_scanning") or 0)
        force_refresh_engine = False
        if status == "0" and vuln_mode != 2:
            force_refresh_engine = int(row_dict.get("input_type") or 1) == 4
        if status == "rerun":
            next_current_line = 0 if vuln_mode == 2 else 1
            if int(row_dict.get("input_type") or 1) == 4:
                reuse_val = str(request.POST.get("reuse_engine_data", "true")).lower()
                force_refresh_engine = reuse_val not in ("true", "1", "yes")
                print(f"[DEBUG engine] Task_operate rerun: input_type=4, reuse_val={reuse_val!r}, force_refresh_engine={force_refresh_engine}")
        elif status == "1":
            next_current_line = 1
        elif vuln_mode == 2:
            next_current_line = int(row_dict.get("current_line") or 0)
        else:
            next_current_line = int(row_dict.get("current_line") or 1)
        try:
            should_reset_search_cursor = int(row_dict.get("input_type") or 1) == 6 and status != "resume"
            update_kwargs = dict(
                status=2,
                phase=1,
                startTime=startTime,
                endTime=None,
                current_line=next_current_line,
                pause_requested=False,
                stop_requested=False,
                queued=True,
                failed=False,
            )
            if should_reset_search_cursor:
                update_kwargs["last_id"] = 0
            if status == "resume":
                update_kwargs["process"] = row_dict.get("process") or "0%"
            else:
                update_kwargs["process"] = "0%"
            models.auto_scan_tasks.objects.filter(id=uid).update(**update_kwargs)
            initialize_task_runtime(models.auto_scan_tasks, uid, dispatch_token, None, queued=True)
            clear_stop_signal("auto_scan", uid)
            clear_pause_signal("auto_scan", uid)
            dispatch_task(run_auto_scan_task, int(uid), dispatch_token, force_refresh_engine=force_refresh_engine, queue="auto_scan")
        except Exception as exc:
            try:
                models.auto_scan_tasks.objects.filter(id=uid).update(
                    status=3,
                    queued=False,
                    failed=True,
                    last_error=str(exc),
                    endTime=timezone.now(),
                )
            finally:
                connection.close()
            return JsonResponse({"status":False,"error":str(exc)})

        tip_map = {
            "rerun": "重跑任务成功",
            "1": "重启任务成功",
            "resume": "续跑任务成功",
            "0": "启动任务成功",
        }
        tips = tip_map.get(status, "操作成功")
        return JsonResponse({"status":True,"tips":tips, "dispatch_token": dispatch_token})
    elif status == "pause":
        row = models.auto_scan_tasks.objects.filter(id=uid).values(
            "heartbeat_at", "status", "owner", "endTime", "queued", "pause_requested",
        ).first()
        if not row or row["status"] != 2 or row["endTime"] is not None:
            return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})

        from django.conf import settings
        heartbeat_sec = int(getattr(settings, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", 10))
        stale_at = timezone.now() - timezone.timedelta(seconds=heartbeat_sec * 3)
        is_alive = bool(row["owner"]) and row["heartbeat_at"] is not None and row["heartbeat_at"] >= stale_at

        if is_alive and not row["pause_requested"]:
            # executor 还在跑，发暂停信号等它优雅排空
            updated = models.auto_scan_tasks.objects.filter(id=uid, status=2).update(pause_requested=True)
            if not updated:
                return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})
            set_pause_signal("auto_scan", uid)
            return JsonResponse({"status": True, "tips": "暂停信号已发送"})

        # executor 已死或从未存在，直接落为暂停状态，不等信号回应。
        # 覆盖三种情况：
        # 1. owner 为空 → 任务排队后 Celery 没 pick up，或 owner 被异常清空
        # 2. 心跳过期 → executor 崩了或 Django/Celery 重启后僵尸回收漏了
        # 3. pause_requested 已设但心跳过期 → 上一轮暂停信号没人收
        updated = models.auto_scan_tasks.objects.filter(id=uid, status=2).update(
            status=4,
            queued=False,
            pause_requested=False,
            stop_requested=False,
            last_error="executor lost (server restarted)" if not is_alive else "executor not found",
            endTime=timezone.now(),
        )
        if not updated:
            return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})
        clear_pause_signal("auto_scan", uid)
        clear_stop_signal("auto_scan", uid)
        return JsonResponse({"status": True, "tips": "任务已暂停（executor 已丢失）"})
    else:
        return JsonResponse({"status":False,"error":"启动任务失败"})
