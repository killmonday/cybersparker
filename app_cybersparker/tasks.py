from celery.exceptions import SoftTimeLimitExceeded
from django.db import close_old_connections, connection

from app_cybersparker import models
from app_cybersparker.services.resource_lease_service import (
    ResourceUnavailableError,
    acquire_resource_leases,
    build_auto_scan_resource_requirements,
    build_batch_scan_resource_requirements,
    get_resource_retry_delay_seconds,
    mark_waiting_for_resource,
    release_resource_leases,
)
from app_cybersparker.services.result_event_service import process_result_streams
from app_cybersparker.services.task_runtime_signal_service import clear_pause_signal, clear_stop_signal, has_pause_signal, has_stop_signal
from app_cybersparker.services.task_state_cas_service import claim_task_execution, compare_and_set_terminal_state
from cybersparker.celery import app


def _run_auto_scan_task(task_id, dispatch_token, owner, force_refresh_engine=False):
    close_old_connections()
    try:
        runtime_row = models.auto_scan_tasks.objects.filter(id=task_id).values("dispatch_token", "stop_requested", "owner", "endTime").first()
    finally:
        connection.close()

    if not runtime_row:
        return {"status": "missing", "task_id": task_id}
    if runtime_row["dispatch_token"] != dispatch_token:
        return {"status": "noop", "reason": "stale_token", "task_id": task_id}
    if runtime_row["endTime"] is not None:
        return {"status": "noop", "reason": "terminal", "task_id": task_id}
    if runtime_row["stop_requested"] and not runtime_row["owner"]:
        return {"status": "stopped", "task_id": task_id}
    if not claim_task_execution(models.auto_scan_tasks, task_id, dispatch_token, owner):
        return {"status": "noop", "reason": "already_claimed", "task_id": task_id}

    from app_cybersparker.views.expload.task_manage import auto_scan_task

    try:
        task_obj = models.auto_scan_tasks.objects.filter(id=task_id).first()
    finally:
        connection.close()

    if not task_obj:
        compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error="task not found")
        return {"status": "failed", "task_id": task_id}

    if int(task_obj.Vulnerability_scanning or 0) == 2:
        # 模式 2 提前校验：必须有资产且有产品
        from app_cybersparker.models import AssetTaskRelation, auto_scan_indentify_result
        asset_count = AssetTaskRelation.objects.filter(task_id=task_id).count()
        if asset_count == 0:
            compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error="该任务还没有资产，请先运行 Web 扫描")
            return {"status": "failed", "task_id": task_id}
        has_product = auto_scan_indentify_result.objects.filter(
            id__in=AssetTaskRelation.objects.filter(task_id=task_id).values("identify_result_id"),
        ).exclude(products=[]).exists()
        if not has_product:
            compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error="该任务的资产均未识别到产品")
            return {"status": "failed", "task_id": task_id}
        is_ok, error = True, None
    else:
        is_restart = (task_obj.process or "0%") == "100%" or task_obj.process is None
        is_ok, error = auto_scan_task.prepare_engine_target_before_start(task_obj, is_restart=is_restart, force_refresh=force_refresh_engine)
    if not is_ok:
        compare_and_set_terminal_state(
            models.auto_scan_tasks,
            task_id,
            dispatch_token,
            owner,
            "failed",
            last_error=error or "prepare engine target failed",
        )
        return {"status": "failed", "task_id": task_id, "reason": "prepare_engine_target_failed"}

    try:
        row_dict = models.auto_scan_tasks.objects.filter(id=task_id).values(
            "task_name",
            "target",
            "Vulnerability_scanning",
            "thread_num",
            "sleep_time",
            "http_timeout",
            "creat_time",
            "status",
            "process",
            "startTime",
            "endTime",
            "remark",
            "current_line",
            "proxy",
            "input_type",
            "search_query",
            "parsed_query",
            "frozen_max_id",
            "last_id",
            "dispatch_token",
            "owner",
            "task_args",
        ).first()
    finally:
        connection.close()

    if not row_dict:
        compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error="task not found")
        return {"status": "failed", "task_id": task_id}

    resource_leases = []
    try:
        try:
            resource_leases = acquire_resource_leases(
                build_auto_scan_resource_requirements(
                    row_dict["thread_num"],
                    row_dict.get("vulnerability_thread_num"),
                    row_dict.get("Vulnerability_scanning"),
                ),
                owner,
            )
        except ResourceUnavailableError as exc:
            mark_waiting_for_resource(models.auto_scan_tasks, task_id, exc.resource_name)
            return {"status": "waiting_resource", "resource": exc.resource_name, "task_id": task_id}

        row_dict["resource_leases"] = resource_leases
        scanner_instance = auto_scan_task.startTask(row_dict, task_id, dispatch_token=dispatch_token, owner=owner, skip_engine_prepare=True)
        if getattr(scanner_instance, "pause_requested", False) and not getattr(scanner_instance, "is_over", True):
            return {"status": "paused", "task_id": task_id}
        terminal_state = "stopped" if getattr(scanner_instance, "stop_requested", False) else "success"
        compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, terminal_state)
        return {"status": terminal_state, "task_id": task_id}
    except SoftTimeLimitExceeded:
        from cybersparker import settings as sett
        scanner = sett.KILL_AUTO_TASK_DIC.pop(str(task_id), None) or sett.KILL_AUTO_TASK_DIC.pop(task_id, None)
        if scanner is not None:
            try:
                scanner.kill_task()
            except Exception:
                pass
        compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error="task timed out")
        return {"status": "timeout", "task_id": task_id}
    except Exception as exc:
        compare_and_set_terminal_state(models.auto_scan_tasks, task_id, dispatch_token, owner, "failed", last_error=str(exc))
        raise
    finally:
        release_resource_leases(resource_leases)
        clear_stop_signal("auto_scan", task_id)
        clear_pause_signal("auto_scan", task_id)
        connection.close()


@app.task(name="app_cybersparker.tasks.run_auto_scan_task", bind=True, time_limit=None, soft_time_limit=None)
def run_auto_scan_task(self, task_id, dispatch_token, owner=None, force_refresh_engine=False):
    owner_name = owner or getattr(self.request, "hostname", None) or f"task-{self.request.id}"
    result = _run_auto_scan_task(task_id, dispatch_token, owner_name, force_refresh_engine=force_refresh_engine)
    if result.get("status") == "waiting_resource":
        raise self.retry(countdown=get_resource_retry_delay_seconds())
    return result


def _should_stop_batch_task(task_id, dispatch_token):
    close_old_connections()
    try:
        task_query = models.batch_EXPTask.objects.filter(id=task_id)
        if dispatch_token:
            task_query = task_query.filter(dispatch_token=dispatch_token)
        row = task_query.values("stop_requested").first()
    finally:
        connection.close()

    if row and row.get("stop_requested"):
        return True
    return has_stop_signal("batch_scan", task_id)


def _run_batch_scan_task(task_id, dispatch_token, owner, force_refresh_engine=False):
    close_old_connections()
    try:
        runtime_row = models.batch_EXPTask.objects.filter(id=task_id).values("dispatch_token", "stop_requested", "pause_requested", "owner", "endTime").first()
    finally:
        connection.close()

    if not runtime_row:
        return {"status": "missing", "task_id": task_id}
    if runtime_row["dispatch_token"] != dispatch_token:
        return {"status": "noop", "reason": "stale_token", "task_id": task_id}
    if runtime_row["endTime"] is not None:
        return {"status": "noop", "reason": "terminal", "task_id": task_id}
    if runtime_row["stop_requested"] and not runtime_row["owner"]:
        return {"status": "stopped", "task_id": task_id}
    if runtime_row.get("pause_requested") and not runtime_row["owner"]:
        return {"status": "paused", "task_id": task_id}
    if not claim_task_execution(models.batch_EXPTask, task_id, dispatch_token, owner):
        return {"status": "noop", "reason": "already_claimed", "task_id": task_id}

    from app_cybersparker.views.expload.task_manage import batch_exp_task

    try:
        row_dict = models.batch_EXPTask.objects.filter(id=task_id).values(
            "task_name",
            "EXP",
            "run_mode",
            "thread_num",
            "sleep_time",
            "target",
            "creat_time",
            "status",
            "process",
            "startTime",
            "endTime",
            "remark",
            "input_type",
            "search_query",
            "parsed_query",
            "frozen_max_id",
            "last_id",
            "dispatch_token",
            "owner",
            "task_type",
            "cmd_input",
            "exp_select_mode",
            "severity_filter",
            "tag_filter",
            "filter_logic",
            "task_args",
        ).first()
    finally:
        connection.close()

    if not row_dict:
        compare_and_set_terminal_state(models.batch_EXPTask, task_id, dispatch_token, owner, "failed", last_error="task not found")
        return {"status": "failed", "task_id": task_id}

    resource_leases = []
    try:
        try:
            resource_leases = acquire_resource_leases(
                build_batch_scan_resource_requirements(row_dict["run_mode"], row_dict["thread_num"]),
                owner,
            )
        except ResourceUnavailableError as exc:
            mark_waiting_for_resource(models.batch_EXPTask, task_id, exc.resource_name)
            return {"status": "waiting_resource", "resource": exc.resource_name, "task_id": task_id}

        row_dict["resource_leases"] = resource_leases
        runner = batch_exp_task.startTask(
            row_dict,
            task_id,
            dispatch_token=dispatch_token,
            owner=owner,
            force_refresh_engine=force_refresh_engine,
        )
        if runner is None:
            compare_and_set_terminal_state(models.batch_EXPTask, task_id, dispatch_token, owner, "failed", last_error="prepare target failed")
            return {"status": "failed", "task_id": task_id}

        process = getattr(runner, "process", None)
        if process is not None:
            while process.is_alive():
                if _should_stop_batch_task(task_id, dispatch_token):
                    runner.kill_task()
                    break
                process.join(timeout=1)
        else:
            while hasattr(runner, "is_alive") and runner.is_alive():
                if _should_stop_batch_task(task_id, dispatch_token):
                    runner.kill_task()
                    break
                runner.join(timeout=1)

        if getattr(runner, "pause_requested", False) and not getattr(runner, "is_over", True):
            terminal_state = "paused"
        elif getattr(runner, "stop_requested", False):
            terminal_state = "stopped"
        else:
            terminal_state = "success"
        compare_and_set_terminal_state(models.batch_EXPTask, task_id, dispatch_token, owner, terminal_state)
        return {"status": terminal_state, "task_id": task_id}
    except SoftTimeLimitExceeded:
        from cybersparker import settings as sett
        runner_handle = sett.BATH_TASK_DIC.pop(str(task_id), None) or sett.BATH_TASK_DIC.pop(task_id, None)
        if runner_handle is not None:
            try:
                runner_handle.kill_task()
            except Exception:
                pass
        compare_and_set_terminal_state(models.batch_EXPTask, task_id, dispatch_token, owner, "failed", last_error="task timed out")
        return {"status": "timeout", "task_id": task_id}
    except Exception as exc:
        compare_and_set_terminal_state(models.batch_EXPTask, task_id, dispatch_token, owner, "failed", last_error=str(exc))
        raise
    finally:
        release_resource_leases(resource_leases)
        clear_stop_signal("batch_scan", task_id)
        clear_pause_signal("batch_scan", task_id)
        connection.close()


@app.task(name="app_cybersparker.tasks.run_batch_scan_task", bind=True, time_limit=None, soft_time_limit=None)
def run_batch_scan_task(self, task_id, dispatch_token, owner=None, force_refresh_engine=False):
    owner_name = owner or getattr(self.request, "hostname", None) or f"task-{self.request.id}"
    result = _run_batch_scan_task(task_id, dispatch_token, owner_name, force_refresh_engine=force_refresh_engine)
    if result.get("status") == "waiting_resource":
        raise self.retry(countdown=get_resource_retry_delay_seconds())
    return result


@app.task(name="app_cybersparker.tasks.auto_scan_probe")
def auto_scan_probe(task_id):
    return {"queue": "auto_scan", "task_id": task_id}


@app.task(name="app_cybersparker.tasks.batch_scan_probe")
def batch_scan_probe(task_id):
    return {"queue": "batch_scan", "task_id": task_id}


@app.task(name="app_cybersparker.tasks.batch_scan_gevent_probe")
def batch_scan_gevent_probe(task_id):
    return {"queue": "batch_scan_gevent", "task_id": task_id}


@app.task(name="app_cybersparker.tasks.run_result_writer_task", bind=True)
def run_result_writer_task(self, stream_name=None, owner=None):
    close_old_connections()
    owner_name = owner or getattr(self.request, "hostname", None) or f"writer-{self.request.id}"
    resource_leases = []
    try:
        try:
            resource_leases = acquire_resource_leases([{"resource": "db_writers", "amount": 1}], owner_name)
        except ResourceUnavailableError:
            raise self.retry(countdown=get_resource_retry_delay_seconds())
        stream_names = [stream_name] if stream_name else None
        summaries = []
        total_processed = 0
        while True:
            summaries = process_result_streams(stream_names=stream_names, consumer_name=owner_name)
            processed_now = sum(item.get("processed", 0) for item in summaries)
            total_processed += processed_now
            if processed_now == 0:
                break
        return {
            "streams": summaries,
            "processed_total": total_processed,
        }
    finally:
        release_resource_leases(resource_leases)
        if not getattr(self.request, "is_eager", False):
            connection.close()


@app.task(name="app_cybersparker.tasks.result_writer_probe")
def result_writer_probe(task_id):
    return {"queue": "result_writer", "task_id": task_id}


@app.task(name="app_cybersparker.tasks.maintenance_echo")
def maintenance_echo(value):
    return value


@app.task(name="app_cybersparker.tasks.run_dir_scan_task", bind=True, time_limit=None, soft_time_limit=None)
def run_dir_scan_task(self, task_id, dispatch_token, owner=None):
    from app_cybersparker.services.dirscan_worker import _run_dir_scan_phase1

    owner_name = owner or getattr(self.request, "hostname", None) or f"task-{self.request.id}"
    return _run_dir_scan_phase1(task_id, dispatch_token, owner_name)


@app.task(name="app_cybersparker.tasks.run_export_task", bind=True)
def run_export_task(self, export_task_id):
    import csv
    import io
    import os
    import time

    from django.conf import settings
    from django.db import connection as dj_connection
    from django.db.models import Q

    from app_cybersparker.views.expload.task_manage.auto_scan_result import (
        parse_condition,
        to_query_structure,
    )

    try:
        export_task = models.ExportTask.objects.get(id=export_task_id)
    except models.ExportTask.DoesNotExist:
        return {"status": "failed", "error": "ExportTask not found"}

    try:
        # -- build queryset --
        if export_task.task_type == "task" and export_task.task_id:
            base = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=export_task.task_id)
        else:
            base = models.auto_scan_indentify_result.objects.all()

        search_string = export_task.search_string
        if search_string:
            condition_tree = parse_condition(search_string)
            query_condition = to_query_structure(condition_tree)
            base = base.filter(query_condition)

        if export_task.zone_id == -1:
            base = base.exclude(zone__code='public')
        elif export_task.zone_id:
            base = base.filter(zone_id=export_task.zone_id)

        base = base.order_by("-id")

        if export_task.export_limit and export_task.export_limit > 0:
            base = base[:export_task.export_limit]

        fields = export_task.fields or []
        need_vuln = any(f in ("vuln", "cve") for f in fields)
        need_vuln_result = export_task.include_vuln_result

        # -- CSV columns --
        FIELD_LABELS = {
            "title": "标题", "product": "产品", "ipc": "IP段", "country": "地区",
            "province": "省份", "city": "城市", "isp": "运营商", "port": "端口",
            "protocol": "协议", "status_code": "状态码", "uri_path": "URI路径",
            "url": "URL", "host": "主机名", "ip": "IP地址", "favicon_md5": "favicon MD5",
            "cert_org": "证书组织", "cert_common_name": "证书主体",
            "cert_serial": "证书序列号", "vuln": "漏洞名称", "cve": "CVE编号",
        }
        headers = [FIELD_LABELS.get(f, f) for f in fields]
        if need_vuln and need_vuln_result:
            headers.append("漏洞验证结果")

        # -- batch fetch vuln data if needed --
        vuln_by_key = {}
        item_task_map = {}
        if need_vuln or need_vuln_result:
            items = list(base)
            if export_task.task_type == "task" and export_task.task_id:
                for item in items:
                    item_task_map[item.id] = [export_task.task_id]
            elif items:
                relation_rows = models.AssetTaskRelation.objects.filter(
                    identify_result_id__in=[item.id for item in items]
                ).values_list("identify_result_id", "task_id")
                for identify_result_id, task_id in relation_rows:
                    item_task_map.setdefault(identify_result_id, []).append(task_id)

            asset_ids = [item.id for item in items if item.id]
            if asset_ids:
                vuln_rows = list(
                    models.auto_scan_exp_result.objects
                    .filter(identify_result_id__in=asset_ids, task_type__in=[1, 2, 3])
                    .select_related("EXP_id")
                    .order_by("-id")
                )
                for row in vuln_rows:
                    vuln_by_key.setdefault(row.identify_result_id, []).append(row)
            rows_iter = items
        else:
            rows_iter = base

        # -- build CSV --
        csv_data = io.StringIO()
        writer = csv.writer(csv_data, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(headers)
        row_count = 0

        def _get_field_value(item, field):
            if field == "product":
                return ", ".join(item.products or [])
            if field == "ipc":
                parts = (item.ip or "").split(".")
                if len(parts) >= 3:
                    return ".".join(parts[:3]) + ".0/24"
                return item.ip or ""
            if field == "country":
                return item.country or ""
            if field == "uri_path":
                return item.uri_path or ""
            if field == "url":
                return f"{item.protocol or 'http'}://{item.host or ''}:{item.port or 0}{item.uri_path or ''}"
            if field == "host":
                return item.host or ""
            if field in ("vuln", "cve", "vuln_result"):
                return ""  # filled per-vuln below
            val = getattr(item, field, "")
            if val is None:
                return ""
            if field == "creatime" and hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d %H:%M:%S")
            return str(val)

        for item in rows_iter:
            if need_vuln or need_vuln_result:
                vulns = vuln_by_key.get(item.id, [])
                if vulns:
                    for v in vulns:
                        exp = v.EXP_id
                        row = [_get_field_value(item, f) for f in fields]
                        # patch vuln/cve columns
                        for idx, f in enumerate(fields):
                            if f == "vuln":
                                row[idx] = exp.title if exp else ""
                            elif f == "cve":
                                row[idx] = exp.CVE if exp and exp.CVE else ""
                        if need_vuln and need_vuln_result:
                            row.append(v.result or "")
                        writer.writerow(row)
                        row_count += 1
                else:
                    row = [_get_field_value(item, f) for f in fields]
                    if need_vuln and need_vuln_result:
                        row.append("")
                    writer.writerow(row)
                    row_count += 1
            else:
                row = [_get_field_value(item, f) for f in fields]
                writer.writerow(row)
                row_count += 1

        # -- save CSV file --
        exports_dir = os.path.join(settings.STATIC_ROOT, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        filename = f"export_{export_task_id}_{int(time.time())}.csv"
        filepath = os.path.join(exports_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write('﻿')
            f.write(csv_data.getvalue())
        csv_data.close()

        csv_url = f"/static/exports/{filename}"

        # -- update task --
        export_task.status = "completed"
        export_task.csv_file = csv_url
        export_task.total_rows = row_count
        export_task.save(update_fields=["status", "csv_file", "total_rows"])

        return {"status": "completed", "export_task_id": export_task_id, "rows": row_count}

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        try:
            export_task.status = "failed"
            export_task.error_message = err[:2048]
            export_task.save(update_fields=["status", "error_message"])
        except Exception:
            pass
        return {"status": "failed", "export_task_id": export_task_id, "error": str(e)}
    finally:
        if not getattr(self.request, "is_eager", False):
            dj_connection.close()


@app.task(name="app_cybersparker.tasks.cleanup_expired_engine_assets", queue="maintenance")
def cleanup_expired_engine_assets():
    """删除 EXP_input/engine_assets/ 下 mtime 超过 60 天的文件"""
    import os
    import time
    from django.conf import settings as s

    asset_dir = os.path.join(os.path.dirname(s.THIS_DIR), "EXP_input", "engine_assets")
    if not os.path.isdir(asset_dir):
        return {"status": "skipped", "reason": "directory not found"}

    cutoff = time.time() - 60 * 24 * 3600
    deleted = 0
    for fname in os.listdir(asset_dir):
        fpath = os.path.join(asset_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            pass

    return {"status": "ok", "deleted": deleted}


# ======================== PoC 生成 ========================

import json as _poc_json
import logging as _poc_logging

from django.conf import settings as _django_settings

INJECTION_GUARD_PREFIX = getattr(_django_settings, 'AI_POC_INJECTION_GUARD_PREFIX', '')
INJECTION_GUARD_SUFFIX = getattr(_django_settings, 'AI_POC_INJECTION_GUARD_SUFFIX', '')

_poc_logger = _poc_logging.getLogger(__name__)


@app.task(bind=True, time_limit=180, soft_time_limit=150)
def run_poc_generation(self, task_id):
    """异步执行 PoC 生成"""
    task = models.PoCGenerationTask.objects.filter(id=task_id).first()
    if not task:
        return {"success": False, "error": "task not found"}

    if task.status != "generating":
        return {"success": False, "error": f"task status is {task.status}, not generating"}

    try:
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        if task.api_proxy:
            api_proto_map = {1: "http", 4: "socks5"}
            api_proto = api_proto_map.get(task.api_proxy.proxy_type, "http")
            api_proxy_str = f"{api_proto}://{task.api_proxy.proxy_address}:{task.api_proxy.proxy_port}"
            set_task_proxy({"http": api_proxy_str, "https": api_proxy_str})

        messages = [
            {"role": "system", "content": _django_settings.AI_POC_SYSTEM_PROMPT},
            {"role": "user", "content": _build_poc_prompt(task)},
        ]

        model_config = task.thinking_model
        from openai import OpenAI
        client = OpenAI(base_url=model_config.api_url, api_key=model_config.api_key, timeout=120.0)

        response = client.chat.completions.create(
            model=model_config.model_id,
            messages=messages,
            temperature=0.3,
        )

        raw_text = response.choices[0].message.content or ""

        try:
            text = raw_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            data = _poc_json.loads(text)
            task.generated_poc_content = data.get("poc_content", "")
            task.generated_metadata = _poc_json.dumps({
                "title": data.get("title", ""),
                "cve": data.get("cve", ""),
                "type": data.get("type", 12),
                "severity": data.get("severity", "info"),
                "tags": data.get("tags", ""),
                "extentions": data.get("extentions", "1"),
                "ctime": data.get("ctime", ""),
            }, ensure_ascii=False)
            task.generated_extra_info = data.get("message", "")
            task.status = "generated"
        except (_poc_json.JSONDecodeError, KeyError):
            task.generated_poc_content = ""
            task.generated_metadata = _poc_json.dumps({})
            task.generated_extra_info = raw_text
            task.status = "generated"

        task.save()
        return {"success": True, "task_id": task_id}

    except Exception as e:
        _poc_logger.error(f"PoC generation failed for task {task_id}: {e}")
        task.status = "failed"
        task.generated_extra_info = str(e)
        task.save()
        return {"success": False, "error": str(e)}


def _build_poc_prompt(task):
    parts = []
    if task.task_description_prompt:
        parts.append(task.task_description_prompt)
    if task.plugin_spec_prompt:
        parts.append(task.plugin_spec_prompt)
    if task.reference_material_prompt:
        parts.append(INJECTION_GUARD_PREFIX + task.reference_material_prompt + INJECTION_GUARD_SUFFIX)
    if task.custom_prompt:
        parts.append('用户额外的要求：' + task.custom_prompt)
    parts.append('按上方定义的规则生成PoC。')
    return "\n\n---\n\n".join(parts)
