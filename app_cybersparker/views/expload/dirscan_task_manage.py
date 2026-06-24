import os
import random
import time
import uuid
from datetime import datetime
from django.shortcuts import render
from django.db import close_old_connections, connection
from django.utils import timezone
from app_cybersparker import models
from app_cybersparker.permissions import deny_user
from app_cybersparker.services.task_runtime_signal_service import clear_stop_signal, set_stop_signal
from app_cybersparker.utils.pagination import Pagination
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
import cybersparker.settings as sett

pwd = sett.THIS_DIR


def error_log(e_info, tips, time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open(error_log_path, "a+") as f:
            f.write(f"[expload {tips}] {time} : " + e_info + "\n")
    except:
        pass


class DirScanTaskForm(BootStrapModelForm):
    class Meta:
        model = models.DirScanTask
        fields = [
            "task_name", "description",
            "input_mode", "search_query", "source_tasks",
            "dicts",
            "pool_size", "concurrency", "max_body_size", "max_truncate_size",
            "proxy",
            "enable_vuln_scan", "vuln_thread_num",
            "sleep_time", "task_args", "http_timeout", "zone",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dicts"].required = False
        self.fields["proxy"].required = False
        self.fields["source_tasks"].required = False
        self.fields["zone"].required = False


def _resolve_input_sources(input_mode, source_tasks, search_query=None, parsed_query=None, frozen_max_id=None, zone_id=None):
    """解析输入源，返回 (protocol, host, port) 三元组列表。
    只查询指定 zone 的资产，且只取 http/https 协议（目录扫描不做非 Web 协议）。"""
    HTTP_PROTOCOLS = ("http", "https")
    if input_mode == 1:  # 全选所有任务
        qs = models.auto_scan_indentify_result.objects.filter(protocol__in=HTTP_PROTOCOLS)
        if zone_id is not None:
            qs = qs.filter(zone_id=zone_id)
        roots = qs.values_list("protocol", "host", "port").distinct()
    elif input_mode == 2:  # 从检索语句导入
        if not parsed_query:
            return None
        from app_cybersparker.services.asset_search_parser import to_query_structure
        q = to_query_structure(parsed_query)
        qs = models.auto_scan_indentify_result.objects.filter(q, protocol__in=HTTP_PROTOCOLS)
        if zone_id is not None:
            qs = qs.filter(zone_id=zone_id)
        if frozen_max_id and frozen_max_id > 0:
            qs = qs.filter(id__lte=frozen_max_id)
        roots = qs.values_list("protocol", "host", "port").distinct()
    elif source_tasks:  # input_mode == 0，手动选择任务
        qs = models.auto_scan_indentify_result.objects.filter(
            task_relations__task_id__in=source_tasks,
            protocol__in=HTTP_PROTOCOLS,
        )
        if zone_id is not None:
            qs = qs.filter(zone_id=zone_id)
        roots = qs.values_list("protocol", "host", "port").distinct()
    else:
        return None  # 没有有效输入源，拒绝创建
    return list(roots)


def _write_shuffle_file(task_id, asset_rows):
    """对资产行做外部洗牌并写入快照文件。"""
    shuffle_dir = os.path.join(pwd, "..", "shuffle_files")
    os.makedirs(shuffle_dir, exist_ok=True)
    filepath = os.path.join(shuffle_dir, f"dirscan_{task_id}.txt")

    # 小数据直接内存洗牌
    keyed = [(random.getrandbits(64), r) for r in asset_rows]
    keyed.sort(key=lambda x: x[0])

    with open(filepath, "w") as f:
        for _, row in keyed:
            f.write(f"{row[0]}\t{row[1]}\t{row[2]}\n")

    return filepath


def task_list(request):
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.DirScanTask.objects.filter(task_name__icontains=search_data)
    else:
        queryset = models.DirScanTask.objects.all().order_by("-id")
    form = DirScanTaskForm()
    # 可用自动扫描任务列表（仅已完成且有产出结果的）
    auto_tasks = list(
        models.auto_scan_tasks.objects
        .filter(status=1)
        .values("id", "task_name")
        .order_by("-id")[:200]
    )
    all_dicts = list(
        models.DirScanDict.objects.all().values("id", "name").order_by("name")
    )
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data,
        "auto_tasks": auto_tasks,
        "all_dicts": all_dicts,
    }
    return render(request, 'project/expload/dirscan_task.html', context)


@deny_user
def task_add(request):
    try:
        post_data = request.POST.copy()
        if 'zone_id' in post_data and 'zone' not in post_data:
            post_data['zone'] = post_data['zone_id']
        form = DirScanTaskForm(data=post_data)
        if not form.is_valid():
            return JsonResponse({"status": False, "error": form.errors})

        input_mode = int(form.cleaned_data.get("input_mode", 0))
        source_tasks = [int(v) for v in request.POST.getlist("source_tasks") if v]
        search_query = form.cleaned_data.get("search_query", "")

        from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure, _has_deep_search
        from django.db.models import Max

        parsed_query = None
        frozen_max_id = 0
        if input_mode == 2:
            if not search_query:
                return JsonResponse({"status": False, "tips": "检索语句不能为空"})
            try:
                tree = parse_condition(search_query)
            except Exception:
                return JsonResponse({"status": False, "tips": "检索语句语法错误，请检查搜索条件"})
            q = to_query_structure(tree)
            qs = models.auto_scan_indentify_result.objects.filter(q).filter(
                protocol__in=("http", "https"),
                zone_id=form.instance.zone_id,
            )
            count = qs.count()
            if count == 0:
                return JsonResponse({"status": False, "tips": "无匹配资产"})
            parsed_query = tree
            frozen_max_id = qs.aggregate(Max('id'))['id__max']

        roots = _resolve_input_sources(input_mode, source_tasks, search_query, parsed_query, frozen_max_id, zone_id=form.instance.zone_id)
        if roots is None:
            return JsonResponse({"status": False, "tips": "请选择输入源（全选或指定任务），两者不能同时为空"})

        if not roots:
            return JsonResponse({"status": False, "tips": "输入源未匹配到任何根资产"})

        # 收集所有字典的路径去重合并
        dicts = list(form.cleaned_data.get("dicts") or [])
        all_paths = []
        for d in dicts:
            all_paths.extend(d.paths or [])
        all_paths = list(set(all_paths))
        if not all_paths:
            return JsonResponse({"status": False, "tips": "请至少选择一个有路径的字典"})

        # 保存任务
        task = form.save(commit=False)
        task.source_tasks = source_tasks
        task.input_mode = input_mode
        task.parsed_query = parsed_query
        task.frozen_max_id = frozen_max_id
        task.save()
        form.save_m2m()

        # 写入 shuffle_file 快照
        filepath = _write_shuffle_file(task.id, roots)
        num_paths = len(all_paths)
        task.shuffle_file = filepath
        task.progress_total = len(roots) * num_paths
        task.save(update_fields=["shuffle_file", "progress_total"])

        return JsonResponse({"status": True})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dirscan_task_add error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "添加任务失败"})


@deny_user
def task_edit(request):
    try:
        uid = request.GET.get("uid")
        row_object = models.DirScanTask.objects.filter(id=uid).first()
        if not row_object:
            return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
        # 必须在 form.is_valid() 之前捕获数据库旧值！
        # Django ModelForm._post_clean() 会通过 construct_instance() 把 POST 数据写回 row_object，
        # 之后再读 row_object.xxx 拿到的是表单新值而非数据库旧值，新旧对比永远相等。
        old_search_query = row_object.search_query or ""
        old_parsed_query = row_object.parsed_query
        old_frozen_max_id = row_object.frozen_max_id
        post_data = request.POST.copy()
        if 'zone_id' in post_data and 'zone' not in post_data:
            post_data['zone'] = post_data['zone_id']
        form = DirScanTaskForm(data=post_data, instance=row_object)
        if form.is_valid():
            input_mode = int(form.cleaned_data.get("input_mode", 0))
            source_tasks = [int(v) for v in request.POST.getlist("source_tasks") if v]
            search_query = form.cleaned_data.get("search_query", "")

            from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure, _has_deep_search
            from django.db.models import Max

            parsed_query = old_parsed_query
            frozen_max_id = old_frozen_max_id
            # 如果检索语句变了，或者冻结状态缺失/过期，重新冻结
            need_refreeze = (
                search_query != old_search_query
                or not parsed_query
                or not frozen_max_id
            )
            if input_mode == 2 and need_refreeze:
                if not search_query:
                    return JsonResponse({"status": False, "tips": "检索语句不能为空"})
                try:
                    tree = parse_condition(search_query)
                except Exception:
                    return JsonResponse({"status": False, "tips": "检索语句语法错误，请检查搜索条件"})
                q = to_query_structure(tree)
                qs = models.auto_scan_indentify_result.objects.filter(q).filter(
                    protocol__in=("http", "https"),
                    zone_id=form.instance.zone_id,
                )
                count = qs.count()
                if count == 0:
                    return JsonResponse({"status": False, "tips": "无匹配资产"})
                parsed_query = tree
                frozen_max_id = qs.aggregate(Max('id'))['id__max']
                # 如果正在运行，先停止
                if row_object.status in (1, 2):
                    models.DirScanTask.objects.filter(id=uid).update(status=3, end_time=timezone.now())
                    row_object.refresh_from_db()

            roots = _resolve_input_sources(input_mode, source_tasks, search_query, parsed_query, frozen_max_id, zone_id=form.instance.zone_id)
            if roots is None:
                return JsonResponse({"status": False, "tips": "请选择输入源（全选或指定任务），两者不能同时为空"})

            if not roots:
                return JsonResponse({"status": False, "tips": "输入源未匹配到任何根资产"})

            dicts = list(form.cleaned_data.get("dicts") or [])
            all_paths = []
            for d in dicts:
                all_paths.extend(d.paths or [])
            all_paths = list(set(all_paths))
            if not all_paths:
                return JsonResponse({"status": False, "tips": "请至少选择一个有路径的字典"})

            task = form.save(commit=False)
            task.source_tasks = source_tasks
            task.input_mode = input_mode
            task.parsed_query = parsed_query
            task.frozen_max_id = frozen_max_id
            task.save()
            form.save_m2m()

            # 重新生成 shuffle_file
            if row_object.shuffle_file and os.path.exists(row_object.shuffle_file):
                os.remove(row_object.shuffle_file)
            filepath = _write_shuffle_file(task.id, roots)
            task.shuffle_file = filepath
            task.progress_total = len(roots) * len(all_paths)
            task.save(update_fields=["shuffle_file", "progress_total"])

            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        error_log(e_info, "dirscan_task_edit error", datetime.now().strftime("%H:%M"))
        return JsonResponse({"status": False, "tips": "编辑任务失败"})


@deny_user
def task_delete(request):
    uid = request.GET.get("uid")
    data = models.DirScanTask.objects.filter(id=uid).first()
    if not data:
        return JsonResponse({"status": False, "error": "删除失败，数据不存在。"})
    # 运行中 → 写停止信号并等待执行器退出
    if int(data.status or 0) == 2:
        set_stop_signal("dir_scan", uid)
        models.DirScanTask.objects.filter(id=uid).update(stop_requested=True)
        for _ in range(30):
            row = models.DirScanTask.objects.filter(id=uid).values("status").first()
            if not row or row["status"] != 2:
                break
            time.sleep(1)
    # 输入文件不删，删 shuffle_file
    if data.shuffle_file and os.path.exists(data.shuffle_file):
        try:
            os.remove(data.shuffle_file)
        except OSError:
            pass
    models.DirScanTask.objects.filter(id=uid).delete()
    try:
        clear_stop_signal("dir_scan", uid)
    except Exception:
        pass
    return JsonResponse({"status": True})


def task_detail(request):
    uid = request.GET.get("uid")
    row_object = models.DirScanTask.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({"status": False, 'tips': "数据不存在，请刷新后重试"})
    return JsonResponse({
        "status": True,
        'data': {
            "task_name": row_object.task_name,
            "description": row_object.description,
            "input_mode": row_object.input_mode,
            "search_query": row_object.search_query or "",
            "source_tasks": list(row_object.source_tasks or []),
            "dicts": [d.id for d in row_object.dicts.all()],
            "pool_size": row_object.pool_size,
            "concurrency": row_object.concurrency,
            "max_body_size": row_object.max_body_size,
            "max_truncate_size": row_object.max_truncate_size,
            "proxy": row_object.proxy_id,
            "enable_vuln_scan": row_object.enable_vuln_scan,
            "vuln_thread_num": row_object.vuln_thread_num,
            "sleep_time": row_object.sleep_time,
            "http_timeout": getattr(row_object, 'http_timeout', 10) or 10,
            "task_args": row_object.task_args or "",
            "zone_id": row_object.zone_id,
        }
    })


@deny_user
def task_operate(request):
    uid = request.POST.get("uid")
    action = str(request.POST.get("status") or "").strip()
    row = models.DirScanTask.objects.filter(id=uid).first()
    if not row:
        return JsonResponse({"status": False, "tips": "任务不存在"})

    if action in ("0", "start"):
        # 启动前清除残留信号
        from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal
        clear_pause_signal("dir_scan", int(uid))
        clear_stop_signal("dir_scan", int(uid))
        from app_cybersparker.services.dirscan_engine import cleanup_task_redis
        cleanup_task_redis(int(uid))
        dispatch_token = uuid.uuid4().hex
        try:
            models.DirScanTask.objects.filter(id=uid).update(
                status=1,
                phase=1,
                start_time=timezone.now(),
                end_time=None,
                progress_done=0,
                file_pos=0,
                dispatch_token=dispatch_token,
                queued=True,
                pause_requested=False,
                stop_requested=False,
            )
            close_old_connections()
            try:
                from app_cybersparker.services.celery_runtime_service import dispatch_task
                from app_cybersparker.tasks import run_dir_scan_task
                dispatch_task(run_dir_scan_task, int(uid), dispatch_token, queue="dir_scan")
            finally:
                connection.close()
            return JsonResponse({"status": True, "tips": "任务已启动"})
        except Exception as exc:
            models.DirScanTask.objects.filter(id=uid).update(
                status=3, queued=False, last_error=str(exc)
            )
            return JsonResponse({"status": False, "tips": f"启动失败: {exc}"})

    elif action == "pause":
        from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal, set_pause_signal
        row = models.DirScanTask.objects.filter(id=uid).values(
            "heartbeat_at", "status", "owner", "end_time", "queued", "pause_requested",
        ).first()
        if not row or row["status"] != 1 or row["end_time"] is not None:
            return JsonResponse({"status": False, "tips": "任务状态已变更，请刷新"})

        heartbeat_sec = int(getattr(sett, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", 10))
        stale_at = timezone.now() - timezone.timedelta(seconds=heartbeat_sec * 3)
        is_alive = bool(row["owner"]) and row["heartbeat_at"] is not None and row["heartbeat_at"] >= stale_at

        if is_alive and not row["pause_requested"]:
            models.DirScanTask.objects.filter(id=uid, status=1).update(pause_requested=True)
            set_pause_signal("dir_scan", int(uid))
            return JsonResponse({"status": True, "tips": "暂停信号已发送"})

        models.DirScanTask.objects.filter(id=uid, status=1).update(
            status=2,
            queued=False,
            pause_requested=False,
            stop_requested=False,
            end_time=timezone.now(),
        )
        clear_pause_signal("dir_scan", int(uid))
        clear_stop_signal("dir_scan", int(uid))
        return JsonResponse({"status": True, "tips": "任务已暂停（executor 已丢失）"})

    elif action in ("resume",):
        from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal
        clear_pause_signal("dir_scan", int(uid))
        clear_stop_signal("dir_scan", int(uid))
        if row.status not in (2, 3):
            return JsonResponse({"status": False, "tips": "只能从暂停或已停止状态恢复"})
        # 已停止的任务恢复前，确保断点文件还在
        if row.status == 3 and not (row.shuffle_file and os.path.exists(row.shuffle_file)):
            return JsonResponse({"status": False, "tips": "任务断点文件已丢失，请使用重跑"})
        dispatch_token = uuid.uuid4().hex
        try:
            models.DirScanTask.objects.filter(id=uid).update(
                status=1, dispatch_token=dispatch_token,
                end_time=None,
                pause_requested=False, stop_requested=False,
            )
            close_old_connections()
            try:
                from app_cybersparker.services.celery_runtime_service import dispatch_task
                from app_cybersparker.tasks import run_dir_scan_task
                dispatch_task(run_dir_scan_task, int(uid), dispatch_token, queue="dir_scan")
            finally:
                connection.close()
            return JsonResponse({"status": True, "tips": "任务已恢复"})
        except Exception as exc:
            models.DirScanTask.objects.filter(id=uid).update(
                status=3, queued=False, last_error=str(exc)
            )
            return JsonResponse({"status": False, "tips": f"恢复失败: {exc}"})

    elif action in ("2", "3", "stop"):
        from app_cybersparker.services.task_runtime_signal_service import set_stop_signal
        # 已暂停的任务直接停止，清理 Redis
        if row.status == 2:
            from app_cybersparker.services.dirscan_engine import cleanup_task_redis
            cleanup_task_redis(int(uid))
            models.DirScanTask.objects.filter(id=uid, status=2).update(
                status=3, end_time=timezone.now(),
                pause_requested=False, stop_requested=False,
            )
            return JsonResponse({"status": True, "tips": "任务已停止"})
        # 运行中的任务先发停止信号，让 worker 自己退出
        models.DirScanTask.objects.filter(id=uid, status=1).update(stop_requested=True)
        set_stop_signal("dir_scan", int(uid))
        return JsonResponse({"status": True, "tips": "停止请求已发送"})

    elif action in ("rerun",):
        if row.status in (1, 2):
            return JsonResponse({"status": False, "tips": "任务正在运行中，请先停止再重跑"})

        # 重新生成 shuffle_file
        roots = _resolve_input_sources(row.input_mode, list(row.source_tasks or []), row.search_query, row.parsed_query, row.frozen_max_id, zone_id=row.zone_id)
        if roots is None:
            return JsonResponse({"status": False, "tips": "输入源为空，请编辑任务配置"})
        if not roots:
            return JsonResponse({"status": False, "tips": "输入源未匹配到任何根资产"})

        all_paths = set()
        for d in row.dicts.all():
            for p in (d.paths or []):
                all_paths.add(p)
        if not all_paths:
            return JsonResponse({"status": False, "tips": "任务没有关联字典，请编辑任务配置"})

        # 删除旧快照文件
        if row.shuffle_file and os.path.exists(row.shuffle_file):
            try:
                os.remove(row.shuffle_file)
            except OSError:
                pass

        filepath = _write_shuffle_file(row.id, roots)
        models.DirScanTask.objects.filter(id=uid).update(
            shuffle_file=filepath,
            progress_total=len(roots) * len(all_paths),
        )

        # 重跑 = 重新启动（先清理旧 Redis key 再派发新任务）
        from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal
        clear_pause_signal("dir_scan", int(uid))
        clear_stop_signal("dir_scan", int(uid))
        from app_cybersparker.services.dirscan_engine import cleanup_task_redis
        cleanup_task_redis(int(uid))
        dispatch_token = uuid.uuid4().hex
        try:
            models.DirScanTask.objects.filter(id=uid).update(
                status=1, phase=1,
                start_time=timezone.now(), end_time=None,
                progress_done=0, file_pos=0,
                dispatch_token=dispatch_token, queued=True,
                pause_requested=False, stop_requested=False,
            )
            close_old_connections()
            try:
                from app_cybersparker.services.celery_runtime_service import dispatch_task
                from app_cybersparker.tasks import run_dir_scan_task
                dispatch_task(run_dir_scan_task, int(uid), dispatch_token, queue="dir_scan")
            finally:
                connection.close()
            return JsonResponse({"status": True, "tips": "任务已重新启动"})
        except Exception as exc:
            models.DirScanTask.objects.filter(id=uid).update(
                status=3, queued=False, last_error=str(exc)
            )
            return JsonResponse({"status": False, "tips": f"重跑失败: {exc}"})

    else:
        return JsonResponse({"status": False, "tips": f"未知操作: {action}"})
