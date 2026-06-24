# coding=utf-8
'''
using version python3.8+
'''
from django.utils import timezone
import socket
import sys
import os
import time
import threading
import traceback
import requests
from queue import Empty, Queue
from threading import Thread

requests.packages.urllib3.disable_warnings()
sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cybersparker.settings')

from django.apps import apps
if not apps.ready:
    import django
    django.setup()

from app_cybersparker import models
from django.db.models import Q


def _build_severity_q(filter_cfg):
    """将 severity_filter JSON 转为 Django Q 对象。兼容数组（前端 React）和对象（旧 Django 模板）两种格式。"""
    if not filter_cfg:
        return None
    if isinstance(filter_cfg, list):
        values = [v for v in filter_cfg if v]
        if not values:
            return None
        return Q(severity__in=values)
    mode = filter_cfg.get("mode", "include")
    values = [v for v in filter_cfg.get("values", []) if v]
    if not values:
        return None
    q = Q(severity__in=values)
    return ~q if mode == "exclude" else q


def _build_tag_q(filter_cfg):
    """将 tag_filter JSON 转为 Django Q 对象。兼容数组和对象格式。values 中含 "*" 表示全选，不限制标签。"""
    if not filter_cfg:
        return None
    if isinstance(filter_cfg, list):
        raw_values = filter_cfg
        mode = "include"
    else:
        mode = filter_cfg.get("mode", "include")
        raw_values = filter_cfg.get("values", [])
    if "*" in raw_values:
        return None
    tag_ids = [v for v in raw_values if v != "empty"]
    has_empty = "empty" in raw_values
    if not tag_ids and not has_empty:
        return None
    q = Q()
    if tag_ids:
        q |= Q(tags__id__in=tag_ids)
    if has_empty:
        q |= Q(tags__isnull=True)
    return ~q if mode == "exclude" else q


def resolve_exp_filter(severity_filter, tag_filter, filter_logic="AND"):
    """按筛选条件构建 EXP queryset。两个都为空时默认排除 severity=info。"""
    qs = models.EXP.objects.filter(use=1)
    severity_q = _build_severity_q(severity_filter)
    tag_q = _build_tag_q(tag_filter)

    if not severity_q and not tag_q:
        return qs.exclude(severity="info")

    if filter_logic == "AND":
        if severity_q and tag_q:
            return qs.filter(severity_q & tag_q)
        return qs.filter(severity_q or tag_q)
    else:
        q = Q()
        if severity_q:
            q |= severity_q
        if tag_q:
            q |= tag_q
        return qs.filter(q)
from app_cybersparker.services.celery_runtime_service import dispatch_task
from app_cybersparker.services.resource_lease_service import get_resource_heartbeat_interval_seconds, heartbeat_resource_leases
from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, STREAM_AUTO_EXP, build_batch_result_event_payload, build_auto_exp_event_payload, publish_result_events, throttle_dispatch_result_writer
from app_cybersparker.lib.request_runtime.patch import patch_all_once
from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
from app_cybersparker.services.request_runtime_config_service import _build_proxy_from_setting
from app_cybersparker.services.task_runtime_signal_service import has_pause_signal, has_stop_signal
from app_cybersparker.tasks import run_result_writer_task
from django.conf import settings
from django.db import DatabaseError, OperationalError, close_old_connections, connection
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import load_runtime_module_from_poc, call_runtime_method

own_retry = 4
while own_retry >= 0:
    try:
        __import__('asyncio')
    except:
        print('please using python3.8+, shit')
        exit(0)
    try:
        __import__('geoip2.database')
    except:
        os.system('pip3 install geoip2')
        own_retry -= 1
        continue
    break


class Task_handler(threading.Thread):
    _gevent_patch_lock = threading.Lock()
    _gevent_patched = False

    def __init__(self, data, start_index=1):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.data = data
        self.input_file = data.get('target_file', '')
        self.input_type = int(data.get('input_type', 1))
        self.search_query_data = data.get('parsed_query')
        self.search_query_frozen_max_id = int(data.get('frozen_max_id') or 0)
        self.search_query_last_id = int(data.get('last_id') or 0)
        self.resource_leases = data.get('resource_leases', [])
        self.last_resource_heartbeat_at = 0
        self.resource_heartbeat_interval = get_resource_heartbeat_interval_seconds()
        self.thread_num = max(
            1,
            min(int(data['thread_num']), settings.MAX_EXPLOIT_THREAD_NUM),
        )
        self._thread_budget = self._read_budget_from_leases("threads")
        self._coroutine_budget = self._read_budget_from_leases("coroutines")
        self.sleep_time = data['sleep_time']
        self.uid = data['uid']
        self.dispatch_token = data.get('dispatch_token')
        self.owner = data.get('owner')
        self.input_queue_size_max = max(self.thread_num * 2, 10)
        self.read_index = int(start_index)
        self.progress = data.get('progress')
        try:
            run_mode = int(data.get("run_mode", 1))
        except Exception:
            run_mode = 1
        self.run_mode = 2 if run_mode == 2 else 1
        self.task_type = int(data.get("task_type", 1))
        self.cmd_input = data.get("cmd_input") or ""
        self.task_args = data.get("task_args", {})
        self.zone_id = data.get("zone_id")
        if self.zone_id in (None, "", 0, "0"):
            from app_cybersparker.models import AssetZone
            try:
                # 公网区域 id 固定为 1。确保系统区域存在（测试环境可能被 truncate）。
                from app_cybersparker.models import AssetZone
                try:
                    AssetZone.objects.get_or_create(
                        id=1,
                        defaults={"code": "public", "name": "公网", "is_system": True},
                    )
                except Exception:
                    pass
                self.zone_id = 1
            except AssetZone.DoesNotExist:
                self.zone_id = None
        self.http_timeout = max(1, int(data.get("http_timeout") or 10))
        # 注入到 request runtime，插件内 requests.get/post 会读这个超时
        from app_cybersparker.lib.request_runtime import conf
        conf.timeout = self.http_timeout
        self.current_index = 0
        self.exp_thread_num = 0
        self.queue_input = Queue(maxsize=self.input_queue_size_max)
        self.queue_output = Queue(maxsize=self.input_queue_size_max)
        self.is_over = True

        self.network_ok = True
        self.exit_flag = False
        self.stop_requested = False
        self.pause_requested = False
        self.current_line = ''
        self.success_count = 0
        self.current_progress = {'progress': '', 'per': '0'}
        self.gevent_pool = None
        self.gevent_greenlets = []
        self.progress_lock = threading.Lock()
        self.last_progress_bucket = None
        self.last_progress_process = None
        self.last_progress_flush_at = 0
        self._last_stop_db_check_at = 0
        self._last_pause_check_at = 0

        self.seconds = time.time()
        self.time_str = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(self.seconds))

        self.t_portscan = None

        expID_list = []
        if int(self.data.get("exp_select_mode") or 1) == 2:
            exp_qs = resolve_exp_filter(
                self.data.get("severity_filter"),
                self.data.get("tag_filter"),
                self.data.get("filter_logic", "AND"),
            )
            expID_list = list(exp_qs.values_list("id", flat=True))
        else:
            str_exp_id = self.data["exp"]
            str_exp_id = str(str_exp_id).strip()
            expID_list.extend(str_exp_id.split(","))
        self.expID_list = expID_list

        try:
            self.exp_cache = self._build_exp_cache()
        finally:
            connection.close()

        self.consumer_number = 0
        self.completed_count = 0
        self.total_line_count = 1

    def _read_budget_from_leases(self, resource_name):
        for lease in self.resource_leases:
            if lease.get("resource") == resource_name:
                return max(1, int(lease.get("amount", 1)))
        return self.thread_num

    def _build_exp_cache(self):
        cache = []
        try:
            if "all" in self.expID_list:
                exp_queryset = models.EXP.objects.all().values("id", "CVE", "title", "poc", "plugin_language")
                for exp_dict in exp_queryset:
                    try:
                        exp_module = load_runtime_module_from_poc(exp_dict["poc"], exp_id=exp_dict["id"])
                        cache.append({
                            "module": exp_module,
                            "plugin": "[" + exp_dict["CVE"] + "]" + exp_dict["title"],
                            "plugin_language": int(exp_dict.get("plugin_language") or 1),
                        })
                    except Exception:
                        continue
                return cache

            for exp_id in self.expID_list:
                if not exp_id:
                    continue
                exp_dict = models.EXP.objects.filter(id=exp_id).values("id", "CVE", "title", "poc", "plugin_language").first()
                if not exp_dict:
                    continue
                try:
                    exp_module = load_runtime_module_from_poc(exp_dict["poc"], exp_id=exp_dict["id"])
                    cache.append({
                        "module": exp_module,
                        "plugin": "[" + exp_dict["CVE"] + "]" + exp_dict["title"],
                        "plugin_language": int(exp_dict.get("plugin_language") or 1),
                    })
                except Exception:
                    traceback.print_exc()
                    continue

            return cache
        finally:
            connection.close()

    def _finalize_run(self, start):
        if self.pause_requested and not self.stop_requested and not self.is_over:
            return
        end = time.time()
        print('[+]task done,', "is normal terminate? :", self.is_over)
        print('\n[+]all_time：%s\n' % (end - start))
        if self.is_over:
            try:
                self.get_progress(force=True)
            except Exception:
                traceback.print_exc()
            if self.dispatch_token is None:
                try:
                    models.batch_EXPTask.objects.filter(id=self.uid).update(
                        endTime=timezone.now(), status=1, process="100%",
                        pause_requested=False, stop_requested=False,
                    )
                finally:
                    connection.close()

    def _ensure_gevent_patch(self):
        print("[debug] enter _ensure_gevent_patch ...")
        if Task_handler._gevent_patched:
            return
        with Task_handler._gevent_patch_lock:
            if Task_handler._gevent_patched:
                return
            from gevent import monkey
            monkey.patch_all(thread=False, subprocess=False, ssl=True)

            # 修复 gevent patch ssl 后 urllib3 的 create_urllib3_context 递归问题。
            # gevent 对 ssl 做 monkey patch 时，urllib3.util.ssl_ 模块已经 import 了原生 ssl，
            # 导致 SSLContext.minimum_version setter 进入无限递归。
            # 把 urllib3 ssl_ 模块里的 SSLContext 引用指向 gevent patch 后的版本即可修复。
            import urllib3.util.ssl_
            import ssl as _stdlib_ssl
            urllib3.util.ssl_.SSLContext = _stdlib_ssl.SSLContext

            print('[debug] gevent monkey patch all applied.')
            Task_handler._gevent_patched = True

    def _run_thread_mode(self):
        exp_number = len(self.expID_list)
        producer_thread = Thread(target=self.producer, args=(exp_number,), name='producer', daemon=True)
        producer_thread.start()

        saveResult_thread = Thread(target=self.save_TaskResult, args=(), daemon=True)
        saveResult_thread.start()

        thread_worker_count = max(1, min(self.thread_num, self._thread_budget))
        for _ in range(thread_worker_count):
            self.exp_thread_num += 1
            consumer_thread = Thread(target=self.consumer_exp, args=(), daemon=True)
            consumer_thread.start()

        while producer_thread.is_alive() is True and not self.exit_flag:
            try:
                time.sleep(3)
                self.get_progress()
            except Exception:
                traceback.print_exc()
            if self.check_stop_bridge() or self.exit_flag is True:
                break
            self.check_pause_signal()
            time.sleep(2)

        if not self.exit_flag:
            self.queue_input.join()

        while self.exp_thread_num != 0 and not self.exit_flag:
            try:
                time.sleep(3)
                self.get_progress()
            except Exception:
                traceback.print_exc()
            if self.check_stop_bridge() or self.exit_flag is True:
                break

        if not self.exit_flag:
            self.queue_output.join()
        self.exit_flag = True

    def _run_gevent_mode(self):
        '''使用协程模式执行exp任务'''
        self._ensure_gevent_patch()
        import gevent
        from gevent.pool import Pool
        from gevent.queue import JoinableQueue

        self.queue_input = JoinableQueue(maxsize=self.input_queue_size_max)
        self.queue_output = JoinableQueue(maxsize=self.input_queue_size_max)

        exp_number = len(self.expID_list)
        gevent_worker_count = max(1, min(self.thread_num, self._coroutine_budget))
        pool_size = gevent_worker_count + 2
        print(f"[+] run in gevent mode, exp_number: {exp_number}, workers: {gevent_worker_count}")
        self.gevent_pool = Pool(pool_size)
        producer_greenlet = self.gevent_pool.spawn(self.producer, exp_number)
        save_greenlet = self.gevent_pool.spawn(self.save_TaskResult)
        self.gevent_greenlets = [producer_greenlet, save_greenlet]

        for _ in range(gevent_worker_count):
            self.exp_thread_num += 1
            greenlet = self.gevent_pool.spawn(self.consumer_exp)
            self.gevent_greenlets.append(greenlet)

        while not producer_greenlet.ready() and not self.exit_flag:
            try:
                gevent.sleep(3)
                self.get_progress()
            except Exception:
                pass
            if self.check_stop_bridge() or self.exit_flag:
                break
            self.check_pause_signal()
            gevent.sleep(2)

        while not self.queue_input.empty() and not self.exit_flag:
            if self.check_stop_bridge():
                break
            gevent.sleep(0.2)

        while self.exp_thread_num != 0 and not self.exit_flag:
            try:
                gevent.sleep(3)
                self.get_progress()
            except Exception:
                pass
            if self.check_stop_bridge():
                break

        while not self.queue_output.empty() and not self.exit_flag:
            if self.check_stop_bridge():
                break
            gevent.sleep(0.2)

        self.exit_flag = True
        try:
            save_greenlet.join(timeout=10)
        except Exception:
            pass
        if self.gevent_pool is not None:
            self.gevent_pool.kill(block=False)

    def run(self):
        close_old_connections()
        patch_all_once()
        proxy_id = self.data.get("proxy")
        if proxy_id:
            proxy_obj = models.ProxySetting.objects.filter(id=proxy_id).first()
            self._task_proxy = _build_proxy_from_setting(proxy_obj) if proxy_obj else {}
        else:
            self._task_proxy = {}
        set_task_proxy(self._task_proxy)
        start = time.time()
        print('[+] exp thread start ok. waiting...\n')
        try:
            if self.run_mode == 2:
                self._run_gevent_mode()
            else:
                self._run_thread_mode()
        finally:
            if self.pause_requested and not self.stop_requested and not self.is_over:
                try:
                    models.batch_EXPTask.objects.filter(id=self.uid).update(
                        status=4,
                        pause_requested=False,
                        stop_requested=False,
                        queued=False,
                        endTime=timezone.now(),
                    )
                finally:
                    connection.close()
        self._finalize_run(start)

    def save_TaskResult(self):
        close_old_connections()
        cache = []
        auto_payloads = []
        batch_size = 100
        flush_timeout = 60  # 秒：缓存有数据时，超过此时间未提交则强制刷新
        last_flush_time = time.time()
        while True:
            try:
                result = self.queue_output.get(True, 10)
            except Empty:
                # 队列空闲时检查超时：缓存有数据且距上次提交超过 flush_timeout 则刷新
                if cache and time.time() - last_flush_time >= flush_timeout:
                    publish_result_events(STREAM_BATCH_EXP, cache)
                    publish_result_events(STREAM_AUTO_EXP, auto_payloads)
                    throttle_dispatch_result_writer(STREAM_BATCH_EXP)
                    throttle_dispatch_result_writer(STREAM_AUTO_EXP)
                    cache.clear()
                    auto_payloads.clear()
                    last_flush_time = time.time()
                if self.exit_flag and self.queue_output.empty():
                    if cache:
                        publish_result_events(STREAM_BATCH_EXP, cache)
                        publish_result_events(STREAM_AUTO_EXP, auto_payloads)
                        throttle_dispatch_result_writer(STREAM_BATCH_EXP)
                        throttle_dispatch_result_writer(STREAM_AUTO_EXP)
                    break
                continue
            try:
                if isinstance(result, dict) and result.get("target") and result.get("result"):
                    print(f"[batch-result] queue_output hit task={self.uid} target={result.get('target')} plugin={result.get('plugin')} result_preview={str(result.get('result'))[:120]}")
                    cache.append(
                        build_batch_result_event_payload(
                            self.uid,
                            result["target"],
                            result["plugin"],
                            result["result"],
                        )
                    )
                    auto_payloads.append(
                        build_auto_exp_event_payload(
                            self.uid, None, result["target"], "",
                            result["result"],
                            plugin_name=result.get("plugin", ""),
                            task_type=3,
                            zone_id=self.zone_id,
                        )
                    )
                    if len(cache) >= batch_size:
                        publish_result_events(STREAM_BATCH_EXP, cache)
                        publish_result_events(STREAM_AUTO_EXP, auto_payloads)
                        throttle_dispatch_result_writer(STREAM_BATCH_EXP)
                        throttle_dispatch_result_writer(STREAM_AUTO_EXP)
                        cache.clear()
                        auto_payloads.clear()
                        last_flush_time = time.time()
            finally:
                self.queue_output.task_done()

    def kill_task(self):
        self.exit_flag = True
        self.stop_requested = True
        self.is_over = False
        if self.gevent_pool is not None:
            try:
                self.gevent_pool.kill(block=False)
            except Exception:
                pass

    def heartbeat_resource_leases_if_needed(self):
        now = time.time()
        if now - self.last_resource_heartbeat_at < self.resource_heartbeat_interval:
            return
        if self.resource_leases:
            heartbeat_resource_leases(self.resource_leases)
        close_old_connections()
        try:
            task_query = models.batch_EXPTask.objects.filter(id=self.uid, endTime__isnull=True)
            if self.dispatch_token:
                task_query = task_query.filter(dispatch_token=self.dispatch_token)
            if self.owner:
                task_query = task_query.filter(owner=self.owner)
            task_query.update(heartbeat_at=timezone.now())
        except (OperationalError, DatabaseError):
            connection.close()
        finally:
            connection.close()
        self.last_resource_heartbeat_at = now

    def check_stop_bridge(self):
        self.heartbeat_resource_leases_if_needed()

        if has_stop_signal("batch_scan", self.uid):
            self.kill_task()
            return True

        now = time.time()
        if now - self._last_stop_db_check_at < 1.0:
            return False
        self._last_stop_db_check_at = now

        close_old_connections()
        try:
            task_query = models.batch_EXPTask.objects.filter(id=self.uid)
            if self.dispatch_token:
                task_query = task_query.filter(dispatch_token=self.dispatch_token)
            row = task_query.values("stop_requested").first()
        except (OperationalError, DatabaseError):
            connection.close()
            return False
        finally:
            connection.close()

        if not row:
            self.kill_task()
            return True
        if row.get("stop_requested"):
            self.kill_task()
            return True
        return False

    def check_pause_signal(self):
        now = time.time()
        if now - self._last_pause_check_at < 1.0:
            return False
        self._last_pause_check_at = now

        if has_pause_signal("batch_scan", self.uid):
            self.pause_requested = True
            return True

        close_old_connections()
        try:
            task_query = models.batch_EXPTask.objects.filter(id=self.uid)
            if self.dispatch_token:
                task_query = task_query.filter(dispatch_token=self.dispatch_token)
            row = task_query.values("pause_requested").first()
        except (OperationalError, DatabaseError):
            connection.close()
            return False
        finally:
            connection.close()

        if not row:
            self.kill_task()
            return True
        if row.get("pause_requested"):
            self.pause_requested = True
            return True
        return False

    def producer(self, exp_number):
        if self.input_type == 6:
            from app_cybersparker.services.asset_search_parser import to_query_structure
            close_old_connections()
            try:
                q = to_query_structure(self.search_query_data)
                frozen_qs = models.auto_scan_indentify_result.objects.filter(
                    q,
                    id__lte=self.search_query_frozen_max_id,
                )
                total_count = frozen_qs.count()
                completed_count = 0
                if self.search_query_last_id:
                    completed_count = frozen_qs.filter(id__lte=self.search_query_last_id).count()
                self.total_line_count = max(total_count, 1)
                self.current_index = completed_count
                self.consumer_number = completed_count
                self.completed_count = completed_count
            except Exception:
                self.total_line_count = 1
                self.current_index = 0
                self.consumer_number = 0
                self.completed_count = 0
            finally:
                connection.close()
            self._producer_from_search_query()
            print("[+] producer done!")
            return

        total_line_count = self.iter_count(self.input_file)
        total_line_count = max(total_line_count, 1)
        self.total_line_count = total_line_count
        print("[+] check target input file, line:", self.total_line_count)
        if self.progress and self.progress != "100%":
            completed_index = int(round(float(self.progress.strip('%')) * total_line_count / 100))
            completed_index = min(max(completed_index, 0), total_line_count)
            self.read_index = completed_index + 1
            self.consumer_number = completed_index
            self.completed_count = completed_index
        else:
            self.read_index = 1
            self.consumer_number = 0
            self.completed_count = 0
        print("[+] self.consumer_number:", self.consumer_number)
        print("[+] self.progress:", self.progress)
        print("[+] read_index:", self.read_index)
        self.current_index = 0
        with open(self.input_file, 'r') as fp:
            for _ in range(0, self.read_index - 1):
                fp.readline()
                self.current_index += 1
            while self.exit_flag == False and not self.pause_requested:
                if self.check_stop_bridge():
                    break
                if self.check_pause_signal():
                    break
                if self.queue_input.full() is False:
                    line = fp.readline()
                    self.current_index += 1
                    if line:
                        _line = line.strip()
                        if len(_line) > 0:
                            self.queue_input.put(_line)
                            global current_line
                            current_line = line
                    else:
                        print("[+] producer done!")
                        break
                else:
                    if self.run_mode == 2:
                        import gevent
                        gevent.sleep(2)
                    else:
                        time.sleep(2)

    def _producer_from_search_query(self):
        """input_type=6 的 producer：keyset 分页遍历匹配资产。"""
        from app_cybersparker.services.search_query_targets import iter_search_query_targets
        from django.db import close_old_connections, connection

        batch_count = 0
        last_id_to_save = self.search_query_last_id
        for row_id, target_url in iter_search_query_targets(
            self.search_query_data,
            self.search_query_frozen_max_id,
            last_id=self.search_query_last_id,
            batch_size=1000,
            zone_id=self.zone_id,
        ):
            if self.exit_flag or self.pause_requested:
                break
            if self.check_stop_bridge():
                break
            if self.check_pause_signal():
                break
            if self.queue_input.full() is False:
                self.queue_input.put(target_url)
                self.current_index += 1
                last_id_to_save = row_id
                self.search_query_last_id = row_id
                batch_count += 1
                if batch_count >= 1000:
                    close_old_connections()
                    try:
                        models.batch_EXPTask.objects.filter(id=self.uid).update(last_id=last_id_to_save)
                    finally:
                        connection.close()
                    batch_count = 0
            else:
                if self.run_mode == 2:
                    import gevent
                    gevent.sleep(2)
                else:
                    time.sleep(2)

        self.search_query_last_id = last_id_to_save
        close_old_connections()
        try:
            models.batch_EXPTask.objects.filter(id=self.uid).update(last_id=last_id_to_save)
        finally:
            connection.close()

    def get_progress(self, force=False):
        close_old_connections()
        with self.progress_lock:
            if self.total_line_count <= 0:
                self.total_line_count = 1
            completed_count = self.completed_count
            total_line_count = self.total_line_count
            current_process = (completed_count / total_line_count) * 100
            if self.dispatch_token is not None and current_process >= 100:
                # Celery path: let compare_and_set_terminal_state set 100% atomically with status
                current_process = 99
            if current_process >= 100:
                process = "100%"
                progress_bucket = 100
            else:
                progress_bucket = int(current_process)
                process = str(current_process)[:5] + '%'

            if progress_bucket == 100 and self.last_progress_bucket == 100:
                return process
            now = time.time()
            process_changed = process != self.last_progress_process
            should_flush = force or progress_bucket != self.last_progress_bucket or (process_changed and now - self.last_progress_flush_at >= 3)
            if not should_flush:
                return process
            print('[progress] completed=%d queued=%d consumed=%d total=%d pct=%s' % (
                completed_count, self.current_index, self.consumer_number, total_line_count, process))
            try:
                if progress_bucket >= 100:
                    if self.dispatch_token is None:
                        models.batch_EXPTask.objects.filter(id=self.uid).update(
                            endTime=timezone.now(), status=1, process="100%",
                            pause_requested=False, stop_requested=False,
                        )
                    else:
                        models.batch_EXPTask.objects.filter(id=self.uid).update(process="100%")
                else:
                    models.batch_EXPTask.objects.filter(id=self.uid).update(process=process)
            finally:
                connection.close()
            self.last_progress_bucket = progress_bucket
            self.last_progress_process = process
            self.last_progress_flush_at = now
            return process

    def consumer_exp(self, ):
        close_old_connections()
        set_task_proxy(getattr(self, '_task_proxy', {}))
        while self.exit_flag == False:
            if self.check_stop_bridge():
                break
            while self.network_ok == False:
                print("[-] check network is error now, sleep 10s ...")
                if self.run_mode == 2:
                    import gevent
                    gevent.sleep(10)
                else:
                    time.sleep(10)
            try:
                line = self.queue_input.get(True, 10)
            except:
                break
            self.consumer_number += 1

            result = None
            interrupted = False
            for exp_item in self.exp_cache:
                if self.exit_flag or self.check_stop_bridge():
                    interrupted = True
                    break
                try:
                    exp_module = exp_item["module"]
                    is_python = exp_item.get("plugin_language") != 2
                    target_dict = {"target": line}
                    if is_python:
                        target_dict["task_args"] = self.task_args
                    if self.task_type == 2:
                        result = call_runtime_method(exp_module, "attact", target_dict, cmd=self.cmd_input)
                    else:
                        result = call_runtime_method(exp_module, "verify", target_dict)
                    print(f"exp_item: {exp_item['plugin']}")

                    if hasattr(result, "get") and type(result).__name__ == "RuntimeMethodResult" and not result.get("matched", False):
                        print(f"[batch-result] plugin skipped/no-hit task={self.uid} target={line} plugin={exp_item['plugin']}")
                        if not self.pause_requested:
                            if self.run_mode == 2:
                                import gevent
                                gevent.sleep(self.sleep_time)
                            else:
                                time.sleep(self.sleep_time)
                        continue

                    if isinstance(result, dict):
                        result["plugin"] = exp_item["plugin"]
                        if result.get("target") and result.get("result"):
                            print(f"[batch-result] plugin matched task={self.uid} target={result.get('target')} plugin={exp_item['plugin']} result_preview={str(result.get('result'))[:120]}")
                        else:
                            print(f"[batch-result] plugin returned no-hit task={self.uid} target={line} plugin={exp_item['plugin']} matched={result.get('matched')}")
                        self.queue_output.put(result)
                        if not self.pause_requested:
                            if self.run_mode == 2:
                                import gevent
                                gevent.sleep(self.sleep_time)
                            else:
                                time.sleep(self.sleep_time)
                except Exception as e:
                    result = {'exception.txt': str(e) + '\n'}
                    self.queue_output.put(result)
            if interrupted:
                continue
            with self.progress_lock:
                self.completed_count += 1
            try:
                self.get_progress()
            except Exception:
                traceback.print_exc()
            try:
                self.queue_input.task_done()
            except:
                pass
        self.exp_thread_num -= 1
        if self.exit_flag:
            print("[+] self.exit_flag is set!")

    def port_probe_with_conn(self, ip, port_number, delay):
        TCP_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        TCP_sock.settimeout(delay)
        open_status = False
        try:
            result = TCP_sock.connect_ex((ip, int(port_number)))
            if result == 0:
                open_status = True
            TCP_sock.close()
        except socket.error as e:
            e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
            print(e_info)
        return open_status

    def t_check_network(self):
        check_ip = socket.gethostbyname('example.com')
        while self.exit_flag is False:
            try:
                if self.port_probe_with_conn(check_ip, 80, 5):
                    self.network_ok = True
                    self.t_portscan.network_ok = True
                    time.sleep(20)
                else:
                    print('\n\033[32;0m[debug] network error!!! check your network\n')
                    self.network_ok = False
                    self.t_portscan.network_ok = False
                    time.sleep(7)
            except Exception as e:
                e_info = f"exception with network, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
                print(e_info)

    def iter_count(self, file_name):
        try:
            from itertools import (takewhile, repeat)
            buffer = 1024 * 1024
            with open(file_name, 'rb') as f:
                buf_gen = takewhile(lambda x: x, (f.read(buffer).decode('utf-8') for _ in repeat(None)))
                count = sum(buf.count('\n') for buf in buf_gen)
                last_data = f.read(buffer)
                if last_data:
                    count += 1
                else:
                    f.seek(-1, 1)
                last_character = f.read(1)
                if last_character != b'\n':
                    count += 1
                return count
        except:
            traceback.print_exc()


def run_task_in_subprocess(data):
    task_handler = Task_handler(data)
    task_handler.run_mode = 2
    task_handler.run()
