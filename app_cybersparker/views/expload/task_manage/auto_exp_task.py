# coding=utf-8
'''
using version python3.8+
'''
import asyncio
import base64
import hashlib
import mmh3
import html as _html
import random
import re as _re
from queue import Empty, Full, Queue
import socket
import ssl
import sys
import os
import tempfile
import time
import threading
import traceback
from urllib.parse import urljoin, urlparse
import aiohttp
import app_cybersparker.views.expload.task_manage.fingerprint_indentify as identifyner
from app_cybersparker import models
from app_cybersparker.services.celery_runtime_service import dispatch_task
from app_cybersparker.services.resource_lease_service import (
    ResourceUnavailableError,
    acquire_resource_lease,
    get_resource_heartbeat_interval_seconds,
    get_resource_limit,
    get_resource_retry_delay_seconds,
    heartbeat_resource_leases,
    mark_waiting_for_resource,
    release_resource_lease,
)
from app_cybersparker.services.result_event_service import (
    STREAM_AUTO_EXP,
    STREAM_IDENTIFY,
    build_auto_exp_event_payload,
    build_identify_event_payloads,
    publish_result_events,
    throttle_dispatch_result_writer,
)
from app_cybersparker.services.task_runtime_signal_service import has_pause_signal, has_stop_signal
from django.db import DatabaseError, OperationalError, close_old_connections, connection
from django.utils import timezone
import cybersparker.settings as app_settings
from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import load_runtime_module_from_poc, call_runtime_method
from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

geoip2_database = None

_NON_HTTP_DEFAULT_PORTS = {
    "ssh": 22, "ftp": 21, "rdp": 3389, "smb": 445,
    "telnet": 23, "mysql": 3306, "mssql": 1433,
    "redis": 6379, "mongodb": 27017, "postgresql": 5432,
    "postgres": 5432, "oracle": 1521,
}

own_retry = 4
while own_retry >= 0:
    try:
        __import__('asyncio')
    except Exception:
        print('please using python3.8+, shit')
        exit(0)
    try:
        from geoip2 import database as geoip2_database
    except Exception:
        os.system('pip3 install geoip2')
        own_retry -= 1
        continue
    break

# own add

FAVICON_DIR = os.path.join(app_settings.STATIC_ROOT, 'favicons')
os.makedirs(FAVICON_DIR, exist_ok=True)

_MEDIA_TO_EXT = {
    'image/x-icon': 'ico', 'image/vnd.microsoft.icon': 'ico',
    'image/png': 'png', 'image/svg+xml': 'svg',
    'image/gif': 'gif', 'image/jpeg': 'jpg', 'image/webp': 'webp',
}


_CHARSET_META_RE = _re.compile(
    br'<meta[^>]+charset\s*=\s*["\']?([a-zA-Z0-9_-]+)',
    _re.IGNORECASE,
)


def _detect_charset_from_html(html_bytes):
    """从 HTML 字节流中提取 <meta charset> 声明，覆盖 HTTP 头缺失 charset 的情况。"""
    if not html_bytes:
        return None
    head = html_bytes[:2048]
    m = _CHARSET_META_RE.search(head)
    if m:
        return m.group(1).decode("ascii", errors="replace")
    return None


def _save_favicon_file(content_bytes, media_type):
    """Save favicon binary to static/favicons/<md5>.<ext>, return URL path."""
    md5 = hashlib.md5(content_bytes).hexdigest()
    mt = (media_type or '').split(';')[0].strip().lower()
    ext = _MEDIA_TO_EXT.get(mt, 'ico')
    filename = f"{md5}.{ext}"
    filepath = os.path.join(FAVICON_DIR, filename)
    if not os.path.exists(filepath):
        with open(filepath, 'wb') as f:
            f.write(content_bytes)
    return f"/static/favicons/{filename}"


def _create_permissive_ssl_context():
    """创建完全宽松的 SSL context，用于 web 探测——不验证证书、不检查密钥强度。

    Web 探测只关心拿到页面内容，不在乎 TLS 安全性。
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # 允许旧式重新协商（OpenSSL 3.x 默认禁止）
    ctx.options |= 0x4 | 0x40000  # OP_LEGACY_SERVER_CONNECT | OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION
    # SECLEVEL=0: 关闭 DH/RSA/CA 等密钥强度检查（解决 DH_KEY_TOO_SMALL 等错误）
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
    except Exception:
        pass
    return ctx


class Auto_exploit_Task_handler(threading.Thread):
    def __init__(self,data):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        proxy_data = data["proxy"]
        if proxy_data:
            self.proxy_address = proxy_data["proxy_address"]
            self.proxy_port = proxy_data["proxy_port"]
            proxy_scheme = proxy_data.get("proxy_type", "http")
            proxy_url = f"{proxy_scheme}://{self.proxy_address}:{self.proxy_port}"
            self.proxies = {"http": proxy_url, "https": proxy_url}
            self.proxy_is_socks5 = (proxy_scheme == "socks5")
        else:
            self.proxies = {}
            self.proxy_is_socks5 = False

        self.data = data
        self.input_file = data['target']
        self.input_type = int(data.get('input_type', 1))
        self.search_query_data = data.get('parsed_query')
        self.search_query_frozen_max_id = int(data.get('frozen_max_id') or 0)
        self.search_query_last_id = int(data.get('last_id') or 0)
        self.read_index = int(data["current_line"])
        self.resource_leases = data.get("resource_leases", [])
        self.last_resource_heartbeat_at = 0
        self._last_pause_check_at = 0
        self._last_stop_db_check_at = 0
        self.resource_heartbeat_interval = get_resource_heartbeat_interval_seconds()
        self.thread_num = max(
            1,
            min(int(data['thread_num']), app_settings.MAX_EXPLOIT_THREAD_NUM),
        )
        vuln_thread_raw = data.get("vulnerability_thread_num")
        if vuln_thread_raw in (None, ""):
            vuln_thread_raw = 40
        self.vulnerability_thread_num = max(
            1,
            min(int(vuln_thread_raw), app_settings.MAX_EXPLOIT_THREAD_NUM),
        )
        self._thread_budget = self._read_thread_budget_from_leases()
        self.network_concurrency = max(
            1,
            min(self.thread_num, get_resource_limit("http_inflight")),
        )
        self.http_resource_retry_delay = get_resource_retry_delay_seconds()
        self.http_timeout_seconds = max(1, int(data.get("http_timeout") or 30))
        self.http_client_timeout = aiohttp.ClientTimeout(
            total=self.http_timeout_seconds,
            sock_connect=min(10, self.http_timeout_seconds),
            sock_read=min(10, self.http_timeout_seconds),
        )
        from app_cybersparker.lib.request_runtime.conf import conf
        conf.timeout = self.http_timeout_seconds
        self.sleep_time = data['sleep_time']
        self.task_id = data['task_id']
        raw_zone = data.get("zone_id")
        if raw_zone in (None, "", "0", 0):
            # 缺 zone_id 时默认公网（旧任务数据兼容；新任务创建时已强制选 zone）
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
        else:
            self.zone_id = int(raw_zone)
        self.dispatch_token = data.get("dispatch_token")
        self.owner = data.get("owner")
        self.Vulnerability_scanning = int(data["Vulnerability_scanning"] or 0)
        self.task_args = data.get("task_args", {})

        self.current_index = 0
        self.is_over = True

        self.network_ok = True
        self.exit_flag = False
        self.stop_requested = False
        self.pause_requested = False
        self.producer_done = False
        self.http_waiting_marked = False
        self.request_scheduler_thread = None


        # ------------------创建队列start
        self.queue_input = Queue(maxsize=max(100, self.network_concurrency * 4))
        self.queue_fingerpoint_input = Queue(maxsize=max(100, self.network_concurrency * 2))
        # queue_EXP_input / queue_EXP_result 在 run() 中按实际线程数创建
        # ------------------创建队列end
        self.identifyner = identifyner.Identifyner()
        try:
            self.fingerprint_exp_cache = (
                self._build_fingerprint_exp_cache()
                if self.Vulnerability_scanning in (1, 2)
                else {}
            )
        finally:
            connection.close()

    def _read_thread_budget_from_leases(self):
        for lease in self.resource_leases:
            if lease.get("resource") == "threads":
                return max(1, int(lease.get("amount", 1)))
        return self.thread_num

    def kill_task(self):
        self.exit_flag = True
        self.stop_requested = True
        self.is_over = False
        current_line = int(self.current_index) + 1
        update_kwargs = {"current_line": current_line}
        if self.dispatch_token is None:
            update_kwargs["endTime"] = timezone.now()
        close_old_connections()
        try:
            models.auto_scan_tasks.objects.filter(id=self.task_id).update(**update_kwargs)
        finally:
            connection.close()

    def heartbeat_resource_leases_if_needed(self):
        now = time.time()
        if now - self.last_resource_heartbeat_at < self.resource_heartbeat_interval:
            return
        if self.resource_leases:
            heartbeat_resource_leases(self.resource_leases)
        close_old_connections()
        try:
            task_query = models.auto_scan_tasks.objects.filter(id=self.task_id, endTime__isnull=True)
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

        # Redis 是主通知通道——无 DB 连接，即时响应
        if has_stop_signal("auto_scan", self.task_id):
            self.kill_task()
            return True

        # DB 兜底——每秒最多查一次
        now = time.time()
        if now - self._last_stop_db_check_at < 1.0:
            return False
        self._last_stop_db_check_at = now

        close_old_connections()
        try:
            task_query = models.auto_scan_tasks.objects.filter(id=self.task_id)
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
        """检查暂停信号。优先查 Redis（即时通知），Redis 不可用时降级查 DB。每秒最多一次。"""
        now = time.time()
        if now - self._last_pause_check_at < 1.0:
            return False
        self._last_pause_check_at = now

        if has_pause_signal("auto_scan", self.task_id):
            self.pause_requested = True
            self.is_over = False
            return True

        close_old_connections()
        try:
            row = models.auto_scan_tasks.objects.filter(id=self.task_id).values("pause_requested").first()
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
            self.is_over = False
            return True
        return False

    def _debug_queue_state(self, stage):
        try:
            print(
                "[pause-drain-debug]",
                stage,
                {
                    "task_id": self.task_id,
                    "pause_requested": self.pause_requested,
                    "exit_flag": self.exit_flag,
                    "queue_input": getattr(self.queue_input, "unfinished_tasks", None),
                    "queue_fingerpoint_input": getattr(self.queue_fingerpoint_input, "unfinished_tasks", None),
                    "queue_EXP_input": getattr(self.queue_EXP_input, "unfinished_tasks", None),
                    "queue_EXP_result": getattr(self.queue_EXP_result, "unfinished_tasks", None),
                    "producer_done": self.producer_done,
                    "network_ok": self.network_ok,
                },
            )
        except Exception:
            traceback.print_exc()

    def run(self):
        close_old_connections()
        set_task_proxy(dict(self.proxies))
        start = time.time()
        print('[+] auto scan task start, waiting...\n')

        try:
            models.auto_scan_tasks.objects.filter(id=self.task_id).update(phase=1)
        finally:
            connection.close()

        # ---- 线程预算 + 队列创建（所有模式共用） ----
        fingerpoint_worker_count = min(3, max(1, min(self.thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM, self._thread_budget)))
        exp_worker_count = 0
        if self.Vulnerability_scanning in (1, 2):
            exp_worker_budget = max(1, self._thread_budget - fingerpoint_worker_count)
            exp_worker_count = max(1, min(self.vulnerability_thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM, exp_worker_budget))
        if self.Vulnerability_scanning == 2:
            fingerpoint_worker_count = 0
            exp_worker_count = max(1, min(self.vulnerability_thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM))
        _exp_qsize = max(10, exp_worker_count * 2)
        if self.Vulnerability_scanning == 2:
            _exp_qsize = max(100, exp_worker_count * 2)
        self.queue_EXP_input = Queue(maxsize=_exp_qsize)
        self.queue_EXP_result = Queue(maxsize=_exp_qsize)

        # save_exp_result + exp_consumer 线程（模式 1 和 2 都需要的漏洞扫描管道）
        save_exp_result_thread = threading.Thread(target=self.save_exp_result, args=(), name='save_exp_result', daemon=True)
        save_exp_result_thread.start()
        for _ in range(exp_worker_count):
            exp_consumer_thread = threading.Thread(target=self.exp_consumer, args=(), daemon=True)
            exp_consumer_thread.start()

        # ---- 模式 2：仅漏洞扫描 ----
        if self.Vulnerability_scanning == 2:
            self._run_vuln_only_mode()
            if self.exit_flag or self.pause_requested:
                return
            endtime = timezone.now()
            try:
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    endTime=endtime, status=1, process="100%", phase=3,
                    pause_requested=False, stop_requested=False,
                )
            finally:
                connection.close()
            return

        # ---- 模式 0/1：web 扫描线程 ----
        for _ in range(fingerpoint_worker_count):
            fingerprint_consumer_thread = threading.Thread(target=self.fingerpoint_consumer_thread, args=(), daemon=True)
            fingerprint_consumer_thread.start()

        network_check_thread = threading.Thread(target=self.t_check_network, args=(), name='network_check', daemon=True)
        network_check_thread.start()

        producer_thread = threading.Thread(target=self.producer, args=(), name='producer', daemon=True)
        producer_thread.start()

        self.request_scheduler_thread = threading.Thread(target=self.request_consumer, args=(), name='request_scheduler', daemon=True)
        self.request_scheduler_thread.start()

        if not self.exit_flag and self.Vulnerability_scanning in (1, 2):
            try:
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(phase=2)
            finally:
                connection.close()

        while producer_thread.is_alive() and not self.exit_flag:
            self.check_stop_bridge()
            time.sleep(2)

        if not self.exit_flag:
            if self.pause_requested:
                self._debug_queue_state("before queue_input.join")
            try:
                self.queue_input.join()
            except Exception:
                pass
            if self.pause_requested:
                self._debug_queue_state("after queue_input.join")

        if self.request_scheduler_thread and self.request_scheduler_thread.is_alive() and not self.exit_flag:
            if self.pause_requested:
                self._debug_queue_state("before request_scheduler_thread.join")
            self.request_scheduler_thread.join()
            if self.pause_requested:
                self._debug_queue_state("after request_scheduler_thread.join")

        if not self.exit_flag:
            if self.pause_requested:
                self._debug_queue_state("before queue_fingerpoint_input.join")
            try:
                self.queue_fingerpoint_input.join()
            except Exception:
                pass
            if self.pause_requested:
                self._debug_queue_state("after queue_fingerpoint_input.join")

        if not self.exit_flag and self.Vulnerability_scanning in (1, 2):
            if self.pause_requested:
                self._debug_queue_state("before exp queue joins")
            try:
                self.queue_EXP_input.join()
                self.queue_EXP_result.join()
            except Exception:
                pass
            if self.pause_requested:
                self._debug_queue_state("after exp queue joins")

        self.exit_flag = True
        time.sleep(2)

        if self.pause_requested and not self.is_over:
            print('[+] auto scan task paused, queues drained\n')
            try:
                endtime = timezone.now()
                saved_line = int(self.current_index) + 1
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    status=4, phase=3, pause_requested=False, endTime=endtime,
                    current_line=saved_line,
                )
                print(f"[+] auto scan task status set to pause, current_line={saved_line}.")
            except Exception:
                traceback.print_exc()
            finally:
                connection.close()
        elif self.is_over and self.dispatch_token is None:
            end = time.time()
            print('[+] auto scan task over, elapsed: %s\n' % (end - start))
            try:
                endtime = timezone.now()
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    endTime=endtime, status=1, process="100%", phase=3,
                    pause_requested=False, stop_requested=False,
                )
                print("[+] auto scan task finished, status set to finish.")
            except Exception:
                traceback.print_exc()
            finally:
                connection.close()
        
    def random_requests_headers(self,):
        user_agent = ['Mozilla/5.0 (Windows; U; Win98; en-US; rv:1.8.1) Gecko/20061010 Firefox/2.0',
        'Mozilla/5.0 (Windows; U; Windows NT 5.0; en-US) AppleWebKit/532.0 (KHTML, like Gecko) Chrome/3.0.195.6 Safari/532.0',
        'Mozilla/5.0 (Windows; U; Windows NT 5.1 ; x64; en-US; rv:1.9.1b2pre) Gecko/20081026 Firefox/3.1b2pre',
        'Opera/10.60 (Windows NT 5.1; U; en-US) Presto/2.6.30 Version/10.60','Opera/8.01 (J2ME/MIDP; Opera Mini/2.0.4062; en; U; ssr)',
        'Mozilla/5.0 (Windows; U; Windows NT 5.1; ; rv:1.9.0.14) Gecko/2009082707 Firefox/3.0.14',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.106 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36',
        'Mozilla/5.0 (Windows; U; Windows NT 6.0; fr; rv:1.9.2.4) Gecko/20100523 Firefox/3.6.4 ( .NET CLR 3.5.30729)',
        'Mozilla/5.0 (Windows; U; Windows NT 6.0; fr-FR) AppleWebKit/528.16 (KHTML, like Gecko) Version/4.0 Safari/528.16',
        'Mozilla/5.0 (Windows; U; Windows NT 6.0; fr-FR) AppleWebKit/533.18.1 (KHTML, like Gecko) Version/5.0.2 Safari/533.18.5']
        UA = random.choice(user_agent)
        headers = {
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'User-Agent':UA,
        'Connection':'keep-alive','Cache-Control':'max-age=0',
        'Accept-Encoding':'gzip, deflate, sdch','Accept-Language':'en-US,en;q=0.8',
        "Referer": "https://www.google.com",
        }
        return headers

    def _extract_html_attr(self, tag, attr):
        match = _re.search(rf'{attr}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', tag, _re.IGNORECASE)
        if not match:
            return ""
        return (match.group(1) or match.group(2) or match.group(3) or "").strip()

    def _favicon_media_type(self, url, content_type):
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        if media_type.startswith("image/"):
            return media_type
        lower_url = (url or "").lower()
        if lower_url.endswith(".png"):
            return "image/png"
        if lower_url.endswith(".svg"):
            return "image/svg+xml"
        if lower_url.endswith(".gif"):
            return "image/gif"
        if lower_url.endswith(".jpg") or lower_url.endswith(".jpeg"):
            return "image/jpeg"
        return "image/x-icon"

    def _looks_like_favicon(self, url, content_type, content_bytes):
        content_type = (content_type or "").lower()
        if "image/" in content_type or "icon" in content_type:
            return True
        if not content_bytes:
            return False
        if content_bytes.startswith(b"\x00\x00\x01\x00"):
            return True
        if content_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if content_bytes[:3] == b"GIF":
            return True
        if content_bytes.startswith(b"\xff\xd8\xff"):
            return True
        if b"<svg" in content_bytes[:512].lower():
            return True
        lower_url = (url or "").lower()
        return lower_url.endswith((".ico", ".png", ".svg", ".gif", ".jpg", ".jpeg"))

    def _build_favicon_candidates(self, url, content):
        candidates = []
        for match in _re.finditer(r"<link\b[^>]*>", content or "", _re.IGNORECASE):
            tag = match.group(0)
            rel = self._extract_html_attr(tag, "rel").lower()
            if "icon" not in rel:
                continue
            href = self._extract_html_attr(tag, "href")
            if not href or href.startswith("data:") or href.startswith("javascript:"):
                continue
            resolved = urljoin(url, href)
            parsed = urlparse(resolved)
            if parsed.scheme not in ("http", "https"):
                continue
            candidates.append(resolved)
        parsed_url = urlparse(url)
        root_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        candidates.extend([
            urljoin(root_url, "/favicon.ico"),
            urljoin(root_url, "/favicon.png"),
            urljoin(root_url, "/apple-touch-icon.png"),
        ])
        deduped = []
        seen = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.append(candidate)
            deduped.append(candidate)
        return deduped[:5]

    async def _fetch_favicon(self, session, url, content):
        for candidate in self._build_favicon_candidates(url, content):
            request_kwargs = {
                "timeout": aiohttp.ClientTimeout(total=min(5, self.http_timeout_seconds or 5)),
                "ssl": False,
                "headers": self.random_requests_headers(),
            }
            if not self.proxy_is_socks5:
                proxy = self.proxies.get(urlparse(candidate).scheme)
                if proxy:
                    request_kwargs["proxy"] = proxy
            try:
                async with session.get(candidate, **request_kwargs) as response:
                    if response.status >= 400:
                        continue
                    content_bytes = await response.read()
                    if not content_bytes or len(content_bytes) > 524288:
                        continue
                    content_type = response.headers.get("Content-Type", "")
                    if not self._looks_like_favicon(candidate, content_type, content_bytes):
                        continue
                    media_type = self._favicon_media_type(candidate, content_type)
                    favicon_path = _save_favicon_file(content_bytes, media_type)
                    return {
                        "favicon": favicon_path,
                        "favicon_md5": hashlib.md5(content_bytes).hexdigest(),
                        "favicon_mmh3": str(mmh3.hash(base64.b64encode(content_bytes))),
                    }
            except Exception:
                continue
        return {"favicon": None, "favicon_md5": None, "favicon_mmh3": None}

    def _extract_cert_subject_value(self, peercert, key):
        for group in peercert.get("subject", ()):
            for item in group:
                if len(item) == 2 and item[0] == key:
                    return item[1]
        return ""

    def _normalize_cert_info(self, peercert):
        if not peercert:
            return {}
        cert_serial = peercert.get("serialNumber") or peercert.get("serial_number") or ""
        return {
            "cert_org": (self._extract_cert_subject_value(peercert, "organizationName") or "")[:255] or None,
            "cert_org_unit": (self._extract_cert_subject_value(peercert, "organizationalUnitName") or "")[:255] or None,
            "cert_common_name": (self._extract_cert_subject_value(peercert, "commonName") or "") or None,
            "cert_serial": str(cert_serial)[:128] or None,
        }

    def _decode_cert_binary(self, cert_binary):
        if not cert_binary:
            return {}
        pem = ssl.DER_cert_to_PEM_cert(cert_binary)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as fp:
            fp.write(pem)
            pem_path = fp.name
        try:
            return ssl._ssl._test_decode_cert(pem_path)
        finally:
            try:
                os.unlink(pem_path)
            except Exception:
                pass

    def _get_response_ssl_object(self, response):
        connection_obj = getattr(response, "connection", None)
        transport = getattr(connection_obj, "transport", None)
        if transport is not None:
            ssl_object = transport.get_extra_info("ssl_object")
            if ssl_object is not None:
                return ssl_object
        protocol = getattr(response, "_protocol", None)
        transport = getattr(protocol, "transport", None)
        if transport is not None:
            return transport.get_extra_info("ssl_object")
        return None

    async def _fetch_certificate_info(self, url, response):
        if urlparse(url).scheme != "https":
            return {}
        ssl_object = self._get_response_ssl_object(response)
        if ssl_object is not None:
            try:
                cert_binary = ssl_object.getpeercert(binary_form=True)
                cert_info = self._normalize_cert_info(self._decode_cert_binary(cert_binary))
                if any(cert_info.values()):
                    return cert_info
            except Exception:
                pass
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return {}
        writer = None
        conn_task = None
        try:
            ssl_context = _create_permissive_ssl_context()
            conn_task = asyncio.ensure_future(
                asyncio.open_connection(
                    host,
                    parsed.port or 443,
                    ssl=ssl_context,
                    server_hostname=host,
                )
            )
            _, writer = await asyncio.wait_for(
                conn_task,
                timeout=min(5, self.http_timeout_seconds or 5),
            )
            ssl_object = writer.get_extra_info("ssl_object")
            if ssl_object is None:
                return {}
            cert_binary = ssl_object.getpeercert(binary_form=True)
            return self._normalize_cert_info(self._decode_cert_binary(cert_binary))
        except Exception:
            return {}
        finally:
            if conn_task is not None and not conn_task.done():
                conn_task.cancel()
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    def _build_fingerprint_context(self, extra):
        extra = extra or {}
        cert_parts = []
        for value in [
            extra.get("cert_org"),
            extra.get("cert_org_unit"),
            extra.get("cert_common_name"),
        ]:
            if value and value not in cert_parts:
                cert_parts.append(value)
        return {
            "favicon": extra.get("favicon_md5") or extra.get("favicon"),
            "favicon_md5": extra.get("favicon_md5"),
            "favicon_mmh3": extra.get("favicon_mmh3"),
            "cert": " ".join(cert_parts),
            "cert_org": extra.get("cert_org"),
            "cert_org_unit": extra.get("cert_org_unit"),
            "cert_common_name": extra.get("cert_common_name"),
            "cert_serial": extra.get("cert_serial"),
            "uri_path": extra.get("final_uri_path") or extra.get("uri_path"),
        }

    def _build_fingerprint_exp_cache(self):
        """一次性预加载指纹→EXP映射，避免每目标重复查询。排除 severity=info（版本探测等非漏洞模板）。"""
        cache = {}
        relates = models.exp_relate_fingerprint.objects.select_related(
            'EXP_id', 'fingerprint_id'
        ).all()
        for relate in relates:
            if relate.EXP_id.severity == "info":
                continue
            product = relate.fingerprint_id.product
            exp_id = relate.EXP_id.id
            if exp_id not in cache:
                cache[exp_id] = {
                    'poc': relate.EXP_id.poc.name,
                    'products': set(),
                    'plugin_language': int(getattr(relate.EXP_id, 'plugin_language', 1) or 1),
                }
            cache[exp_id]['products'].add(product)
        return cache

    def get_exp_ids_for_products(self, product_list):
        """使用预建缓存查找，无DB查询。一个 EXP 可能关联多个不同产品名的指纹，用集合交集匹配。"""
        exp_ids_info = {}
        plist_set = set(product_list)
        for exp_id, info in self.fingerprint_exp_cache.items():
            matched = info['products'] & plist_set
            if matched:
                if exp_id not in exp_ids_info:
                    info_copy = dict(info)
                    info_copy['matched_product'] = next(iter(matched))
                    exp_ids_info[exp_id] = info_copy
        return exp_ids_info                    
    
    def _run_vuln_only_mode(self):
        """模式 2：仅漏洞扫描。读已有资产→product→POC→入队→等结果。全程线程，不走 asyncio。"""
        from app_cybersparker.models import AssetTaskRelation
        from app_cybersparker.models import auto_scan_indentify_result

        # 1. 查询该任务关联资产 ID
        close_old_connections()
        try:
            relation_ids = list(
                AssetTaskRelation.objects
                .filter(task_id=self.task_id)
                .values_list("identify_result_id", flat=True)
                .order_by("identify_result_id")
            )
        finally:
            connection.close()

        if not relation_ids:
            raise ValueError("该任务还没有资产，请先运行 Web 扫描")

        # 2. 批量取资产的 target + products
        close_old_connections()
        try:
            asset_rows = list(
                auto_scan_indentify_result.objects
                .filter(id__in=relation_ids)
                .values("id", "target", "products")
            )
        finally:
            connection.close()

        # 3. 构建 id→asset 映射 + 去重 target→products
        asset_map = {a["id"]: a for a in asset_rows}
        seen_pairs = set()
        valid_pairs = []
        for asset_id in relation_ids:
            asset = asset_map.get(asset_id)
            if not asset or not asset["target"] or not asset["products"]:
                continue
            key = (asset["target"], frozenset(asset["products"]))
            if key not in seen_pairs:
                seen_pairs.add(key)
                valid_pairs.append((asset["target"], list(asset["products"])))

        total = len(valid_pairs)
        if total == 0:
            raise ValueError("该任务的资产均未识别到产品")

        # 4. 更新 phase
        try:
            models.auto_scan_tasks.objects.filter(id=self.task_id).update(phase=2)
        finally:
            connection.close()

        # 5. 入队 exp_consumer
        start_offset = max(0, int(self.read_index or 0))
        for idx, (target, products) in enumerate(valid_pairs):
            if self.exit_flag:
                break
            if self.check_stop_bridge():
                return

            if idx < start_offset:
                continue

            if self.check_pause_signal():
                self.queue_EXP_input.put({target: products})
                self.producer_done = True
                self.queue_EXP_input.join()
                self.queue_EXP_result.join()
                self.read_index = start_offset + idx + 1
                try:
                    models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                        status=4, phase=3, pause_requested=False,
                        endTime=timezone.now(), current_line=self.read_index,
                    )
                finally:
                    connection.close()
                self.pause_requested = True
                return

            self.queue_EXP_input.put({target: products})

            if (idx + 1) % 10 == 0 or idx == total - 1:
                pct = min(99, round((idx + 1) / total * 100))
                self.read_index = idx + 1
                try:
                    models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                        process=f"{pct}%", current_line=self.read_index,
                    )
                finally:
                    connection.close()

        # 6. 等待队列排空
        self.producer_done = True
        if not self.exit_flag:
            self.queue_EXP_input.join()
            self.queue_EXP_result.join()

    def producer(self):
        if self.input_type == 6:
            return self._producer_from_search_query()
        close_old_connections()
        try:
            total_line_count = self.iter_count(self.input_file)
            self.total_line_count = total_line_count
            self.current_index = 0
            last_progress_bucket = -1
            with open(self.input_file, 'r') as fp:
                for x in range(0, self.read_index-1):
                    fp.readline()
                    self.current_index += 1
                while not self.exit_flag and not self.pause_requested:
                    if self.check_stop_bridge():
                        break
                    if self.check_pause_signal():
                        break
                    if self.queue_input.full() or self.queue_fingerpoint_input.full():
                        time.sleep(self.sleep_time or 0.1)
                        continue
                    line = fp.readline()
                    self.current_index += 1
                    if line:
                        _line = line.strip()
                        if len(_line) > 0:
                            self.queue_input.put(_line)
                            global current_line
                            current_line = line
                    else:
                        break
                    try:
                        if total_line_count == 0:
                            total_line_count = 1
                        process = (self.current_index / total_line_count) * 100
                        if process > 100:
                            process = 100
                        if process >= 100:
                            process = 99
                        progress_bucket = int(process)
                        if progress_bucket != last_progress_bucket:
                            last_progress_bucket = progress_bucket
                            current_process = str(process)[:5] + '%'
                            saved_line = self.current_index + 1
                            try:
                                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                                    process=current_process,
                                    current_line=saved_line,
                                )
                            finally:
                                connection.close()
                    except Exception as e:
                        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
                        print(e_info, "inputfile: ", self.input_file)

            # Terminal process="100%" is set atomically with status=1
            # by compare_and_set_terminal_state (Celery) or the finish block below (legacy).
        except Exception:
            traceback.print_exc()
        finally:
            self.producer_done = True

    def _producer_from_search_query(self):
        """input_type=6 的 producer：keyset 分页遍历匹配资产。"""
        from app_cybersparker.services.asset_search_parser import to_query_structure
        from app_cybersparker.services.search_query_targets import iter_search_query_targets

        try:
            q = to_query_structure(self.search_query_data)
            frozen_qs = models.auto_scan_indentify_result.objects.filter(
                q,
                id__lte=self.search_query_frozen_max_id,
            )
            total_line_count = frozen_qs.count()
            completed_count = 0
            if self.search_query_last_id:
                completed_count = frozen_qs.filter(id__lte=self.search_query_last_id).count()
        except Exception:
            total_line_count = 1
            completed_count = 0
        self.total_line_count = max(total_line_count, 1)
        self.current_index = completed_count

        batch_count = 0
        last_progress_bucket = -1
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
            while self.queue_input.full() or self.queue_fingerpoint_input.full():
                time.sleep(self.sleep_time or 0.1)
                if self.exit_flag:
                    break
            self.queue_input.put(target_url)
            self.current_index += 1
            last_id_to_save = row_id
            batch_count += 1
            try:
                process = (self.current_index / self.total_line_count) * 100
                if process > 100:
                    process = 100
                if process >= 100:
                    process = 99
                progress_bucket = int(process)
                if progress_bucket != last_progress_bucket:
                    last_progress_bucket = progress_bucket
                    current_process = str(process)[:5] + '%'
                    saved_line = self.current_index + 1
                    try:
                        models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                            process=current_process,
                            current_line=saved_line,
                        )
                    finally:
                        connection.close()
            except Exception:
                traceback.print_exc()
            if batch_count >= 1000:
                try:
                    models.auto_scan_tasks.objects.filter(id=self.task_id).update(last_id=last_id_to_save)
                finally:
                    connection.close()
                batch_count = 0

        try:
            models.auto_scan_tasks.objects.filter(id=self.task_id).update(last_id=last_id_to_save)
        finally:
            connection.close()

        self.producer_done = True

    async def request_scan(self, session, url):
        lease = None
        while not self.exit_flag:
            if await asyncio.to_thread(self.check_stop_bridge):
                return None, None, None, None, None, RuntimeError("task stopped")
            try:
                lease = acquire_resource_lease(
                    "http_inflight",
                    self.owner or f"auto_scan:{self.task_id}",
                )
                if self.http_waiting_marked:
                    await asyncio.to_thread(self._clear_http_waiting_state)
                break
            except ResourceUnavailableError as exc:
                if not self.http_waiting_marked:
                    await asyncio.to_thread(self._mark_http_waiting_state, exc.resource_name)
                await asyncio.sleep(self.http_resource_retry_delay)
        if lease is None:
            return None, None, None, None, None, RuntimeError("task stopped")

        # 裸域名（无 scheme）自动尝试 http 和 https
        # 用 "://" 判断而非 urlparse().scheme，因为 urlparse 会把裸域名 "host:port" 的 host 错解析为 scheme
        if "://" in url:
            url_candidates = [(url, urlparse(url))]
        else:
            url_candidates = [(f"http://{url}", urlparse(f"http://{url}")),
                              (f"https://{url}", urlparse(f"https://{url}"))]

        # 非 HTTP/HTTPS 协议：不发起 HTTP 请求，直接返回最小数据集，由下游 save_indentify_to_db 落库
        # 只有明确带 :// 的 URL 才做协议判断，裸域名不会误入此分支
        parsed = urlparse(url)
        if "://" in url and parsed.scheme not in ("http", "https"):
            extra = {"candidate_url": url, "final_uri_path": ""}
            try:
                if lease:
                    release_resource_lease(lease["resource"], lease["lease_id"])
            except Exception:
                traceback.print_exc()
            return None, None, None, None, extra, None

        try:
            last_error = None
            for attempt_idx, (candidate_url, url_parsed) in enumerate(url_candidates):
                try:
                    request_kwargs = {
                        "timeout": self.http_client_timeout,
                        "headers": self.random_requests_headers(),
                    }
                    if not self.proxy_is_socks5:
                        proxy = self.proxies.get(url_parsed.scheme)
                        if proxy:
                            request_kwargs["proxy"] = proxy
                    async with session.get(candidate_url, **request_kwargs) as response:
                        content_bytes = await response.read()
                        encoding = (
                            response.charset
                            or _detect_charset_from_html(content_bytes)
                            or response.get_encoding()
                            or "utf-8"
                        )
                        try:
                            content = content_bytes.decode(encoding)
                        except (UnicodeDecodeError, LookupError, TypeError, ValueError):
                            content = content_bytes.decode("utf-8", errors="replace")
                        header = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
                        title = ""
                        status_code = response.status
                        try:
                            m = _re.search(r"<title[^>]*>(.*?)</title>", content, _re.IGNORECASE | _re.DOTALL)
                            if m:
                                title = _html.unescape(m.group(1).strip())
                        except Exception:
                            pass
                        favicon_info = await self._fetch_favicon(session, candidate_url, content)
                        cert_info = await self._fetch_certificate_info(candidate_url, response)
                        resolved_ip = ""
                        try:
                            hostname = url_parsed.hostname or ""
                            # 如果 hostname 本身就是 IP，直接用
                            try:
                                socket.inet_pton(socket.AF_INET, hostname)
                                resolved_ip = hostname
                            except (socket.error, OSError):
                                try:
                                    socket.inet_pton(socket.AF_INET6, hostname)
                                    resolved_ip = hostname
                                except (socket.error, OSError):
                                    pass
                            # 代理模式下 peername 是代理服务器的 IP，不能用来当目标 IP。
                            # 自己 DNS 解析目标 hostname。
                            if not resolved_ip:
                                proxy_in_use = (
                                    self.proxies.get(url_parsed.scheme)
                                    or self.proxy_is_socks5
                                )
                                if proxy_in_use:
                                    addrs = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            socket.getaddrinfo,
                                            hostname,
                                            url_parsed.port or 80,
                                            0,
                                            socket.SOCK_STREAM,
                                        ),
                                        timeout=5.0,
                                    )
                                    for family, _, _, _, sockaddr in addrs:
                                        if family == socket.AF_INET:
                                            resolved_ip = sockaddr[0]
                                            break
                                    if not resolved_ip and addrs:
                                        resolved_ip = addrs[0][4][0]
                                else:
                                    proto = response._protocol
                                    if proto is not None and proto.transport is not None:
                                        peername = proto.transport.get_extra_info("peername")
                                        if peername:
                                            resolved_ip = peername[0]
                        except Exception:
                            pass
                        # JS 跳转检测：只对首次响应做跳转识别，最终落地页做第二次产品识别
                        final_uri_path = ""
                        redirect_url = None
                        redirect_content = None
                        redirect_header = None
                        redirect_title = None
                        redirect_status_code = None
                        try:
                            from app_cybersparker.services.js_redirect import get_js_redirect_url
                            js_redirect = get_js_redirect_url(content)
                            if js_redirect and not js_redirect.startswith("javascript:") and not js_redirect.startswith("#"):
                                if js_redirect.startswith("http"):
                                    redirect_url = js_redirect
                                elif js_redirect.startswith("/"):
                                    redirect_url = f"{url_parsed.scheme}://{url_parsed.hostname}:{url_parsed.port}{js_redirect}"
                                else:
                                    redirect_url = f"{url_parsed.scheme}://{url_parsed.hostname}:{url_parsed.port}/{js_redirect}"
                                # 发起跳转请求
                                async with session.get(redirect_url, **request_kwargs) as resp2:
                                    redirect_status_code = resp2.status
                                    redirect_header = "\n".join(f"{k}: {v}" for k, v in resp2.headers.items())
                                    redirect_content_bytes = await resp2.read()
                                    try:
                                        redirect_encoding = (
                                            resp2.charset
                                            or _detect_charset_from_html(redirect_content_bytes)
                                            or resp2.get_encoding()
                                            or "utf-8"
                                        )
                                        redirect_content = redirect_content_bytes.decode(redirect_encoding)
                                    except Exception:
                                        redirect_content = redirect_content_bytes.decode("utf-8", errors="replace")
                                    parsed_final = urlparse(str(resp2.url))
                                    final_uri_path = (parsed_final.path or "")[:512]
                                    m2 = _re.search(r"<title[^>]*>(.*?)</title>", redirect_content, _re.IGNORECASE | _re.DOTALL)
                                    redirect_title = _html.unescape(m2.group(1).strip()) if m2 else ""
                        except Exception:
                            pass

                        extra = {
                            "favicon": favicon_info.get("favicon"),
                            "favicon_md5": favicon_info.get("favicon_md5"),
                            "cert_org": cert_info.get("cert_org"),
                            "cert_org_unit": cert_info.get("cert_org_unit"),
                            "cert_common_name": cert_info.get("cert_common_name"),
                            "cert_serial": cert_info.get("cert_serial"),
                            "resolved_ip": resolved_ip,
                            "redirect_url": redirect_url,
                            "redirect_content": redirect_content,
                            "redirect_header": redirect_header,
                            "redirect_title": redirect_title,
                            "redirect_status_code": redirect_status_code,
                            "final_uri_path": final_uri_path,
                            "candidate_url": candidate_url,
                        }
                    return header, content, title, status_code, extra, None
                except Exception as e:
                    last_error = e
                    if attempt_idx < len(url_candidates) - 1:
                        continue
            # 所有候选 URL 都失败
            return None, None, None, None, None, last_error
        finally:
            try:
                if lease:
                    release_resource_lease(lease["resource"], lease["lease_id"])
            except Exception:
                traceback.print_exc()

    def _mark_http_waiting_state(self, resource_name):
        close_old_connections()
        try:
            mark_waiting_for_resource(models.auto_scan_tasks, self.task_id, resource_name)
        finally:
            connection.close()
        self.http_waiting_marked = True

    def _clear_http_waiting_state(self):
        close_old_connections()
        try:
            models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                queued=False,
                failed=False,
                last_error=None,
                owner=self.owner,
                heartbeat_at=timezone.now(),
                status=2,
            )
        finally:
            connection.close()
        self.http_waiting_marked = False

    def request_consumer(self,):
        asyncio.run(self._request_consumer_async())

    async def _request_consumer_async(self):
        ssl_context = _create_permissive_ssl_context()
        if self.proxy_is_socks5:
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url(
                self.proxies["http"], limit=self.network_concurrency, ssl=ssl_context,
                keepalive_timeout=2.0,
            )
        else:
            connector = aiohttp.TCPConnector(
                limit=self.network_concurrency, ssl=ssl_context,
                keepalive_timeout=2.0, enable_cleanup_closed=True,
            )
        timeout = self.http_client_timeout
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=False,
        ) as session:
            pending = {}
            while self.exit_flag is False:
                if await asyncio.to_thread(self.check_stop_bridge):
                    break
                if self.network_ok is False:
                    await asyncio.sleep(10)
                    continue

                while not self.exit_flag and len(pending) < self.network_concurrency:
                    if self.queue_fingerpoint_input.full():
                        break
                    try:
                        url = self.queue_input.get_nowait()
                    except Empty:
                        break
                    print("request_consumer get line:", url)
                    task = asyncio.create_task(self.request_scan(session, url))
                    pending[task] = url

                if not pending:
                    if self.producer_done and self.queue_input.empty():
                        break
                    await asyncio.sleep(self.sleep_time or 0.05)
                    continue

                done, _ = await asyncio.wait(
                    list(pending.keys()),
                    timeout=0.2,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    continue

                for task in done:
                    url = pending.pop(task, None)
                    if url is None:
                        continue
                    try:
                        header, content, title, status_code, extra, error = await task
                        if error is not None:
                            print("An error occurred during the request:", error)
                        else:
                            data = {
                                url: {
                                    "header": header,
                                    "content": content,
                                    "html": content,
                                    "title": title,
                                    "status_code": status_code,
                                    "favicon": (extra or {}).get("favicon"),
                                    "favicon_md5": (extra or {}).get("favicon_md5"),
                                    "cert_org": (extra or {}).get("cert_org"),
                                    "cert_org_unit": (extra or {}).get("cert_org_unit"),
                                    "cert_common_name": (extra or {}).get("cert_common_name"),
                                    "cert_serial": (extra or {}).get("cert_serial"),
                                    "resolved_ip": (extra or {}).get("resolved_ip"),
                                    "candidate_url": (extra or {}).get("candidate_url"),
                                    "redirect_url": (extra or {}).get("redirect_url"),
                                    "redirect_content": (extra or {}).get("redirect_content"),
                                    "redirect_header": (extra or {}).get("redirect_header"),
                                    "redirect_title": (extra or {}).get("redirect_title"),
                                    "redirect_status_code": (extra or {}).get("redirect_status_code"),
                                    "final_uri_path": (extra or {}).get("final_uri_path"),
                                    "error": None,
                                }
                            }
                            while not self.exit_flag:
                                try:
                                    self.queue_fingerpoint_input.put_nowait(data)
                                    break
                                except Full:
                                    await asyncio.sleep(self.sleep_time or 0.05)
                    except Exception:
                        traceback.print_exc()
                    finally:
                        self.queue_input.task_done()
                        if self.sleep_time:
                            await asyncio.sleep(self.sleep_time)

            remaining_tasks = list(pending.keys())
            for task in remaining_tasks:
                if not task.done():
                    task.cancel()
                self.queue_input.task_done()
            if remaining_tasks:
                await asyncio.gather(*remaining_tasks, return_exceptions=True)

    def get_ip_from(self, ip):
        from app_cybersparker.lib.qqwry import query_ip_geo

        result = query_ip_geo(ip)
        if not result.get("country"):
            return "None", "None", "None", "", "", ""
        return (
            result.get("country", "") or "None",
            result.get("area_name_zh", "") or "None",
            result.get("area_name_zh", "") or "None",
            result.get("province", "") or "",
            result.get("city", "") or "",
            result.get("isp", "") or "",
        )

    def save_indentify_to_db(self, fingers_list, url, header, title, content, status_code, extra=None):
        extra = extra or {}
        # 优先用 request_scan 实际请求的候选 URL（含正确 scheme），
        # 裸域名输入时 url 无 scheme，candidate_url 才有 http:// 或 https://
        effective_url = extra.get("candidate_url") or url
        parsed_url = urlparse(effective_url)
        protocol = parsed_url.scheme
        hostname = parsed_url.hostname or ""
        # 若有 JS 跳转，使用最终落地页的 path 作为 uri_path
        final_uri_path = extra.get("final_uri_path") or ""
        uri_path = final_uri_path if final_uri_path else (parsed_url.path or "")[:512]
        port = parsed_url.port
        if not port:
            if protocol == 'http':
                port = 80
            elif protocol == 'https':
                port = 443
            elif protocol in _NON_HTTP_DEFAULT_PORTS:
                port = _NON_HTTP_DEFAULT_PORTS[protocol]
            else:
                port = 1

        resolved_ip = extra.get("resolved_ip", "") or ""
        _is_hostname_domain = not all(c.isdigit() or c == '.' for c in hostname)
        if _is_hostname_domain:
            if not resolved_ip:
                # peername / DNS 都没拿到 IP，兜底再解析一次
                try:
                    old_timeout = socket.getdefaulttimeout()
                    socket.setdefaulttimeout(5.0)
                    try:
                        addrs = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
                    finally:
                        socket.setdefaulttimeout(old_timeout)
                    resolved_ip = addrs[0][4][0] if addrs else ""
                except Exception:
                    resolved_ip = ""
            ip_address = resolved_ip if resolved_ip else hostname
        else:
            ip_address = hostname
        # 存储的 host 是原始主机名（域名或IP），入库前截断
        store_host = (hostname or "")[:255]
        # 地理位置查 IP（域名查不到纯真库）
        geo_lookup_ip = resolved_ip if (_is_hostname_domain and resolved_ip) else hostname
        country, _, _, province, city, isp = self.get_ip_from(geo_lookup_ip)
        country = (country or "")[:64]
        products = fingers_list if fingers_list else []
        payloads = build_identify_event_payloads(
            self.task_id,
            effective_url,
            header,
            title,
            content,
            status_code,
            ip_address,
            store_host,
            port,
            protocol,
            country,
            products,
            uri_path=uri_path,
            favicon=extra.get("favicon"),
            favicon_md5=extra.get("favicon_md5"),
            cert_org=extra.get("cert_org"),
            cert_org_unit=extra.get("cert_org_unit"),
            cert_common_name=extra.get("cert_common_name"),
            cert_serial=extra.get("cert_serial"),
            province=province,
            city=city,
            isp=isp,
            zone_id=self.zone_id,
        )
        publish_result_events(STREAM_IDENTIFY, payloads)
        throttle_dispatch_result_writer(STREAM_IDENTIFY)

    def fingerpoint_consumer_thread(self,):
        close_old_connections()
        try:
            while self.exit_flag == False:
                if self.check_stop_bridge():
                    break
                while self.network_ok == False:
                    time.sleep(10)
                try:
                    line_dict = self.queue_fingerpoint_input.get(True, 10)
                except Empty:
                    request_stage_done = self.producer_done and self.queue_input.unfinished_tasks == 0
                    if request_stage_done and self.queue_fingerpoint_input.unfinished_tasks == 0:
                        break
                    continue
                try:
                    if line_dict:
                        data = {}
                        for url, info in line_dict.items():
                            header = info.get("header")
                            content = info.get("content") or info.get("html")
                            title = info.get("title")
                            status_code = int(info.get("status_code") or 0)
                            extra = {
                                "candidate_url": info.get("candidate_url"),
                                "favicon": info.get("favicon"),
                                "favicon_md5": info.get("favicon_md5"),
                                "cert_org": info.get("cert_org"),
                                "cert_org_unit": info.get("cert_org_unit"),
                                "cert_common_name": info.get("cert_common_name"),
                                "cert_serial": info.get("cert_serial"),
                                "resolved_ip": info.get("resolved_ip"),
                                "final_uri_path": info.get("final_uri_path"),
                            }
                            fingerprint_context = self._build_fingerprint_context(extra)
                            # 非 HTTP 协议（header/content 均为空）跳过指纹匹配，避免否定规则误命中
                            if header is None and content is None:
                                fingers_list = []
                            else:
                                fingers_list = self.identifyner.handle(header, content, title, fingerprint_context)
                            if self.Vulnerability_scanning == 1:
                                data[url] = fingers_list
                                self.queue_EXP_input.put(data)
                            self.save_indentify_to_db(fingers_list, url, header, title, content, status_code, extra)
                            # 跳转落地页指纹识别：只对最终响应做识别
                            redirect_content = info.get("redirect_content")
                            if redirect_content:
                                redirect_header = info.get("redirect_header") or ""
                                redirect_title = info.get("redirect_title") or ""
                                redirect_status = int(info.get("redirect_status_code") or 0)
                                redirect_url = info.get("redirect_url") or url
                                redirect_fingers = self.identifyner.handle(redirect_header, redirect_content, redirect_title, fingerprint_context)
                                if self.Vulnerability_scanning == 1:
                                    data_redirect = {redirect_url: redirect_fingers}
                                    self.queue_EXP_input.put(data_redirect)
                                self.save_indentify_to_db(redirect_fingers, redirect_url, redirect_header, redirect_title, redirect_content, redirect_status, extra)
                finally:
                    self.queue_fingerpoint_input.task_done()
        finally:
            close_old_connections()

    def exp_consumer(self,):
        set_task_proxy(dict(self.proxies))
        while self.exit_flag == False:
            if self.check_stop_bridge():
                break
            while self.network_ok == False:
                time.sleep(10)
            try:
                line_dict = self.queue_EXP_input.get(True,10)
            except Empty:
                exp_stage_done = (
                    self.producer_done
                    and self.queue_input.unfinished_tasks == 0
                    and self.queue_fingerpoint_input.unfinished_tasks == 0
                    and self.queue_EXP_input.unfinished_tasks == 0
                )
                if exp_stage_done:
                    break
                continue
            try:
                for url, fingers_list in line_dict.items():
                    poc_info_dict = self.get_exp_ids_for_products(fingers_list)
                    if not poc_info_dict:
                        continue
                    for exp_id, info in poc_info_dict.items():
                        poc = info['poc']
                        product = info.get('matched_product') or next(iter(info.get('products', [])), '')
                        plugin_language = int(info.get('plugin_language') or 1)
                        try:
                            exp = load_runtime_module_from_poc(poc, exp_id=exp_id)
                            target_dict = {"target": url}
                            if plugin_language != 2:
                                target_dict["task_args"] = self.task_args
                            result = call_runtime_method(exp, "verify", target_dict)
                            if not result:
                                continue
                            if plugin_language == 2:
                                queued_result = {
                                    "exp_id": exp_id,
                                    "target": url,
                                    "product": product,
                                    "result": result.get("result", "") if isinstance(result, dict) else str(result),
                                }
                            else:
                                queued_result = dict(result or {})
                                queued_result["product"] = product
                                queued_result["exp_id"] = exp_id
                            self.queue_EXP_result.put(queued_result)
                        except Exception:
                            traceback.print_exc()
                        if not self.pause_requested:
                            time.sleep(self.sleep_time)
            finally:
                self.queue_EXP_input.task_done()

    def save_exp_result_to_db(self,exp_id,target,product,result):
        payload = build_auto_exp_event_payload(self.task_id, exp_id, target, product, result, zone_id=self.zone_id)
        publish_result_events(STREAM_AUTO_EXP, [payload])
        throttle_dispatch_result_writer(STREAM_AUTO_EXP)

    def _normalize_exp_result(self, result_info):
        if not isinstance(result_info, dict):
            raise TypeError("unexpected exp result type")

        exp_id = int(result_info["exp_id"])
        product = str(result_info.get("product") or "")

        if "target" in result_info and "result" in result_info:
            return exp_id, str(result_info["target"]), product, str(result_info["result"])

        target = (
            result_info.get("host")
            or result_info.get("url")
            or result_info.get("matched-at")
            or result_info.get("matched_at")
            or result_info.get("target")
        )
        detail = (
            result_info.get("detail")
            or result_info.get("output")
            or result_info.get("template-id")
            or result_info.get("template_id")
            or result_info.get("info")
            or result_info.get("extracted-results")
            or result_info.get("extracted_results")
            or result_info
        )
        matched = bool(result_info.get("matched", False))

        if not target:
            detail_text = str(detail)
            for token in ("http://", "https://"):
                idx = detail_text.find(token)
                if idx != -1:
                    tail = detail_text[idx:]
                    target = tail.split()[0].strip("'\",)")
                    break
        if not target:
            raise KeyError("target")

        result = "matched" if matched else str(detail)
        return exp_id, str(target), product, result

    def save_exp_result(self,):
        close_old_connections()
        try:
            while self.exit_flag == False:
                if self.check_stop_bridge():
                    break
                while self.network_ok == False:
                    time.sleep(10)
                try:
                    result_info = self.queue_EXP_result.get(True, 10)
                except Empty:
                    result_stage_done = (
                        self.producer_done
                        and self.queue_input.unfinished_tasks == 0
                        and self.queue_fingerpoint_input.unfinished_tasks == 0
                        and self.queue_EXP_input.unfinished_tasks == 0
                        and self.queue_EXP_result.unfinished_tasks == 0
                    )
                    if result_stage_done:
                        break
                    continue
                try:
                    if result_info is None:
                        continue
                    exp_id, target, product, result = self._normalize_exp_result(result_info)
                    print(exp_id, target, product, result)
                    self.save_exp_result_to_db(exp_id, target, product, result)
                except Exception:
                    try:
                        print(
                            "[exp-result-debug] normalize failed",
                            {
                                "type": type(result_info).__name__,
                                "keys": list(result_info.keys()) if isinstance(result_info, dict) else None,
                                "value": str(result_info)[:2000],
                            },
                        )
                    except Exception:
                        pass
                    traceback.print_exc()
                    continue
                finally:
                    self.queue_EXP_result.task_done()
        finally:
            close_old_connections()

    def port_probe_with_conn(self, ip, port_number, delay):
        TCP_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        TCP_sock.settimeout(delay)
        open_status = False
        try:
            result = TCP_sock.connect_ex((ip, int(port_number)))
            if result == 0:  # If the TCP handshake is successful, the port is OPEN. Otherwise it is CLOSE
                open_status = True
            TCP_sock.close()
        except socket.error as e:
            e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
            print(e_info)
        return open_status

    def t_check_network(self):
        check_ip = socket.gethostbyname('example.com')
        # check_ip = socket.gethostbyname('163.com')
        while self.exit_flag is False:
            try:
                if self.port_probe_with_conn(check_ip, 80, 5):
                    self.network_ok = True
                    time.sleep(30)
                else:
                    print('\n\033[32;0m[debug] network error!!! check your network\n')
                    self.network_ok = False
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
                if last_character != '\n':
                    count += 1
                return count
        except :
            traceback.print_exc()