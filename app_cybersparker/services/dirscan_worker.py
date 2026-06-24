import asyncio
import json
import logging
import os
import re
import time
from urllib.parse import urljoin, urlparse

import aiohttp

logger = logging.getLogger(__name__)
from django.db import close_old_connections, connection
from django.utils import timezone

from app_cybersparker import models
from app_cybersparker.services.dirscan_engine import (
    DirScanPool,
    body_hash_add,
    body_hash_exists,
    compute_body_hash,
    compute_ttl,
    load_paths,
    save_file_pos,
    save_progress,
)
from app_cybersparker.services.js_redirect import get_js_redirect_url
from app_cybersparker.views.expload.task_manage.auto_exp_task import _create_permissive_ssl_context
from app_cybersparker.views.expload.task_manage.fingerprint_indentify import Identifyner
from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
from app_cybersparker.services.request_runtime_config_service import _build_proxy_from_setting

CONTENT_TYPES = ("text/html", "text/plain", "application/json", "application/xml")
_title_re = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_title(html):
    m = _title_re.search(html or "")
    return m.group(1).strip()[:255] if m else ""


async def _http_get(session, protocol, host, port, path, proxy_url=None, max_body_size=524288, max_truncate_size=1048576, http_timeout=10):
    """发起 HTTP GET 请求，返回 (status_code, header_text, body_text, final_url, content_length)。"""
    url = f"{protocol}://{host}:{port}{path}"
    try:
        async with session.get(
            url,
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=http_timeout),
        ) as response:
            final_url = str(response.url)
            status_line = f"HTTP/{response.version.major}.{response.version.minor} {response.status} {response.reason}"
            header_text = status_line + "\n" + "\n".join(f"{k}: {v}" for k, v in response.headers.items())
            ct = response.headers.get("Content-Type", "")
            cl = response.headers.get("Content-Length")
            content_length = int(cl) if cl else None

            if not any(ct.startswith(t) for t in CONTENT_TYPES):
                return response.status, header_text, "", final_url, content_length

            if cl and int(cl) > max_body_size:
                return response.status, header_text, "", final_url, content_length

            chunks = []
            total = 0
            async for chunk in response.content.iter_chunked(8192):
                total += len(chunk)
                if total > max_truncate_size:
                    break
                chunks.append(chunk)
            body = b"".join(chunks).decode("utf-8", errors="replace")
            return response.status, header_text, body, final_url, content_length
    except Exception:
        return 0, "", "", url, None


def _sync_check_status(task_id):
    """同步：双通道检查暂停/停止信号。Redis 优先，DB 回退。返回 (signal_type, should_break)。"""
    from django.db import connection as db_conn
    from app_cybersparker.services.task_runtime_signal_service import has_pause_signal, has_stop_signal

    # 速率限制
    _sync_check_status._last_check = getattr(_sync_check_status, "_last_check", 0)
    _sync_check_status._last_result = getattr(_sync_check_status, "_last_result", (None, False))
    now = time.monotonic()
    if now - _sync_check_status._last_check < 1.0:
        return _sync_check_status._last_result

    _sync_check_status._last_check = now

    # Redis 优先
    if has_pause_signal("dir_scan", task_id):
        result = ("pause", True)
    elif has_stop_signal("dir_scan", task_id):
        result = ("stop", True)
    else:
        # DB 回退
        try:
            t = models.DirScanTask.objects.filter(id=task_id).values(
                "status", "pause_requested", "stop_requested",
            ).first()
        finally:
            db_conn.close()
        if not t:
            result = ("stop", True)
        elif t["status"] == 3:
            result = ("stop", True)
        elif t["stop_requested"]:
            result = ("stop", True)
        elif t["pause_requested"]:
            result = ("pause", True)
        else:
            result = (None, False)
    _sync_check_status._last_result = result
    return result


def _sync_bump_progress(task_id, done):
    """同步：递增进度。"""
    from django.db import connection as db_conn
    try:
        models.DirScanTask.objects.filter(id=task_id).update(progress_done=done)
    finally:
        db_conn.close()


def _sync_fingerprint_and_write(task_id, protocol, host, port, uri_path, status_code,
                                 header_text, body, final_url, content_length=None, zone_id=None):
    """同步：指纹识别 + 写入 directory_result（含 DB 查询）。zone_id 参与唯一键。"""
    from django.db import connection as db_conn
    try:
        title = ""
        products = []
        if status_code > 0 and body:
            try:
                title = _extract_title(body)
                products = Identifyner().handle(header_text, body[:4096], title) or []
                if products:
                    logger.info(f"[dirscan] task={task_id} fingerprint {host}:{port}{uri_path} title={title[:40]} products={products}")
            except Exception:
                pass
        _s = lambda v: v.replace("\x00", "") if isinstance(v, str) else v
        _target = _s(final_url)
        if len(_target) > 512:
            _target = _target[:512]
        _uri = _s(uri_path)
        if len(_uri) > 512:
            _uri = _uri[:512]
        defaults = {
            "task_id": task_id, "ip": "", "target": _target,
            "status_code": status_code, "header": _s(header_text),
            "title": title, "html": _s(body), "products": [_s(p) for p in products],
        }
        if content_length is not None:
            defaults["content_length"] = content_length
        # zone 参与 unique_together 查找键，且 defaults 中必须带 zone_id
        # 避免不同 zone 的同 protocol+host+port+uri_path 互相覆盖
        if zone_id is not None:
            defaults["zone_id"] = zone_id
        models.auto_scan_directory_result.objects.update_or_create(
            zone_id=zone_id, protocol=_s(protocol), host=_s(host), port=port, uri_path=_uri,
            defaults=defaults,
        )
    finally:
        db_conn.close()


def _sync_save_file_pos(task_id, pos, ttl):
    """同步：保存文件位置。"""
    save_file_pos(task_id, pos, ttl)


def _sync_update_heartbeat(task_id):
    """同步：更新心跳时间（用于僵尸任务检测）。"""
    from django.db import connection as db_conn
    try:
        models.DirScanTask.objects.filter(id=task_id).update(heartbeat_at=timezone.now())
    finally:
        db_conn.close()


def _sync_update_root_uri_path(task_id, protocol, host, port, uri_path):
    """同步：更新根资产的 uri_path（JS 跳转最终落地路径）。"""
    from django.db import connection as db_conn
    try:
        models.auto_scan_indentify_result.objects.filter(
            protocol=protocol, host=host, port=port, uri_path__in=["", "/"],
        ).update(uri_path=uri_path)
    finally:
        db_conn.close()


async def _fingerprint_and_write(task_id, host, path, status_code, header_text,
                                  body, final_url, ttl, wrote_ref, content_length=None, zone_id=None):
    """指纹识别 + 写入 directory_result（如需）。返回是否写入。"""
    body_bytes = body.encode("utf-8", errors="replace") if body else b""
    body_len = len(body_bytes)
    if body_len < 50 and status_code <= 0:
        return False
    # 空 body 但状态码有效 = 被 Content-Type/Content-Length 阻断的响应，跳过 hash 去重直接写库
    if body_len < 50:
        await asyncio.to_thread(
            _sync_fingerprint_and_write, task_id,
            host["protocol"], host["host"], host["port"], path,
            status_code, header_text, body, final_url, content_length, zone_id,
        )
        wrote_ref[0] += 1
        logger.info(f"[dirscan] task={task_id} WRITE_BLOCKED {host['host']}:{host['port']}{path} "
                    f"status={status_code} content_length={content_length} wrote_total={wrote_ref[0]}")
        return True
    h = compute_body_hash(body_bytes)
    if body_hash_exists(task_id, host["protocol"], host["host"], host["port"], h):
        return False
    body_hash_add(task_id, host["protocol"], host["host"], host["port"], h, ttl)
    await asyncio.to_thread(
        _sync_fingerprint_and_write, task_id,
        host["protocol"], host["host"], host["port"], path,
        status_code, header_text, body, final_url, content_length, zone_id,
    )
    wrote_ref[0] += 1
    logger.info(f"[dirscan] task={task_id} WRITE {host['host']}:{host['port']}{path} "
                f"status={status_code} body={body_len}B wrote_total={wrote_ref[0]}")
    return True


def _run_dir_scan_phase1(task_id, dispatch_token, owner):
    """Phase 1 Web 扫描主循环（同步入口，内部跑 asyncio 事件循环）。"""
    close_old_connections()

    # CAS 认领任务
    updated = models.DirScanTask.objects.filter(
        id=task_id, dispatch_token=dispatch_token, end_time__isnull=True,
    ).update(owner=owner, queued=False, heartbeat_at=timezone.now())
    if not updated:
        return {"status": "noop", "reason": "claim_failed", "task_id": task_id}

    try:
        task = models.DirScanTask.objects.get(id=task_id)
    finally:
        connection.close()

    try:
        task_args = json.loads(task.task_args or "{}")
    except Exception:
        logging.warning("task_args JSON parse failed for dirscan task %s", task_id)
        task_args = {}

    task.status = 1
    task.phase = 1
    task.start_time = timezone.now()
    task.save(update_fields=["status", "phase", "start_time"])

    paths = load_paths(task_id)
    if not paths:
        models.DirScanTask.objects.filter(id=task_id).update(status=4, end_time=timezone.now(), queued=False)
        return {"status": "completed", "reason": "no_paths", "task_id": task_id}

    num_assets = task.progress_total // len(paths) if len(paths) > 0 else 0
    ttl = compute_ttl(num_assets, len(paths))
    pool = DirScanPool(task_id=task_id, pool_size=task.pool_size, paths=paths, ttl=ttl)

    # 从 Redis 恢复暂停前未扫完的 host 进度
    recovered = pool.recover()
    if recovered > 0:
        logger.info(f"[dirscan] task={task_id} recovered {recovered} hosts from Redis for resume")

    logger.info(f"[dirscan] task={task_id} start phase=1 pool={task.pool_size} concurrency={task.concurrency} "
          f"assets={num_assets} paths={len(paths)} total={task.progress_total} proxy={bool(task.proxy)}")

    file_pos = task.file_pos
    file_done = False
    proxy_url = None
    if task.proxy:
        protocol = task.proxy.get_protocol_type()
        proxy_url = protocol + "://" + task.proxy.proxy_address + ":" + str(task.proxy.proxy_port)
    proxies_dict = _build_proxy_from_setting(task.proxy) if task.proxy else {}
    max_body = task.max_body_size
    max_trunc = task.max_truncate_size
    concurrency = task.concurrency
    sleep_time = task.sleep_time
    http_timeout = getattr(task, 'http_timeout', 10) or 10
    shuffle_file = task.shuffle_file
    progress_done = task.progress_done
    wrote_count = 0
    task_zone_id = task.zone_id

    async def _scan_loop():
        nonlocal file_pos, file_done, progress_done, wrote_count, proxy_url, sleep_time
        ssl_context = _create_permissive_ssl_context()
        if proxy_url and proxy_url.startswith("socks5://"):
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url(proxy_url, limit=concurrency, ssl=ssl_context, keepalive_timeout=2.0)
            proxy_url = None
        else:
            connector = aiohttp.TCPConnector(limit=concurrency, ssl=ssl_context, keepalive_timeout=2.0, enable_cleanup_closed=True)
        logger.info(f"[dirscan] task={task_id} loop started, shuffle_file={shuffle_file}")

        async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
            while True:
                # 检查暂停/停止
                sig, should_break = await asyncio.to_thread(_sync_check_status, task_id)
                if should_break:
                    if sig == "pause":
                        await asyncio.to_thread(_sync_save_file_pos, task_id, file_pos, ttl)
                    break

                # 补充池（fill 内部有 ORM 检查资产是否存在）
                if not file_done:
                    pool_size_before = len(pool.pool)
                    file_pos = await asyncio.to_thread(pool.fill, shuffle_file, file_pos)
                    if len(pool.pool) != pool_size_before:
                        logger.info(f"[dirscan] task={task_id} pool filled: {pool_size_before}→{len(pool.pool)}, file_pos={file_pos}")
                    if pool.file_done:
                        file_done = True
                        logger.info(f"[dirscan] task={task_id} shuffle_file exhausted at file_pos={file_pos}, pool={len(pool.pool)}")

                if not pool.has_work():
                    if file_done:
                        break
                    continue

                host, path = pool.take_one()
                if host is None:
                    continue

                # 非 HTTP(S) 协议的资产（如 ftp、ssh、mysql）不做 Web 扫描，
                # 直接跳过并计入全部剩余路径的进度，避免 aiohttp 报错或进度条走不到头。
                if host.get("protocol", "http") not in ("http", "https"):
                    remaining = pool.path_count - host["counter"]
                    host["counter"] = pool.path_count
                    progress_done += remaining
                    await asyncio.to_thread(_sync_bump_progress, task_id, progress_done)
                    pool.cleanup_host(host)
                    continue

                save_progress(task_id, host["protocol"], host["host"], host["port"],
                              host["offset"], host["counter"], ttl)

                first_status, first_header, first_body, first_url, first_content_length = await _http_get(
                    session, host["protocol"], host["host"], host["port"], path,
                    proxy_url=proxy_url, max_body_size=max_body, max_truncate_size=max_trunc, http_timeout=http_timeout,
                )

                # HTTP 响应后立即检查暂停/停止，缩短最长延迟
                sig, should_break = await asyncio.to_thread(_sync_check_status, task_id)
                if should_break:
                    if sig == "pause":
                        await asyncio.to_thread(_sync_save_file_pos, task_id, file_pos, ttl)
                    break

                host["counter"] += 1
                progress_done += 1
                await asyncio.to_thread(_sync_bump_progress, task_id, progress_done)

                # JS 跳转检测
                wrote_ref = [wrote_count]
                js_url = get_js_redirect_url(first_body) if first_body else None
                last_status, last_body, last_url = first_status, first_body, first_url
                final_uri_path = None
                hops = 0
                base_url = f"{host['protocol']}://{host['host']}:{host['port']}"

                if js_url:
                    # 指纹首次响应
                    await _fingerprint_and_write(
                        task_id, host, path, first_status, first_header,
                        first_body, first_url, ttl, wrote_ref, first_content_length, zone_id=task_zone_id,
                    )
                    # 跟踪 JS 跳转链（最多 5 跳）
                    current_path = path
                    while js_url and hops < 5:
                        hops += 1
                        resolved = urljoin(f"{base_url}{current_path}", js_url)
                        parsed = urlparse(resolved)
                        current_path = parsed.path or "/"
                        last_status, _, last_body, last_url, last_content_length = await _http_get(
                            session, host["protocol"], host["host"], host["port"],
                            current_path,
                            proxy_url=proxy_url, max_body_size=max_body,
                            max_truncate_size=max_trunc, http_timeout=http_timeout,
                        )
                        logger.info(f"[dirscan] task={task_id} JS redirect hop={hops} "
                                    f"{host['host']}:{host['port']}{current_path} status={last_status}")
                        js_url = get_js_redirect_url(last_body) if last_body else None

                    final_uri_path = current_path
                    # 指纹最终落地响应（仅当与首次不同时）
                    if last_url != first_url:
                        await _fingerprint_and_write(
                            task_id, host, current_path, last_status, "",
                            last_body, last_url, ttl, wrote_ref, last_content_length, zone_id=task_zone_id,
                        )
                    # 写回根资产 uri_path
                    await asyncio.to_thread(
                        _sync_update_root_uri_path, task_id,
                        host["protocol"], host["host"], host["port"], final_uri_path,
                    )
                else:
                    # 无 JS 跳转，仅指纹当前响应
                    await _fingerprint_and_write(
                        task_id, host, path, first_status, first_header,
                        first_body, first_url, ttl, wrote_ref, first_content_length, zone_id=task_zone_id,
                    )
                wrote_count = wrote_ref[0]

                # 每 20 条输出进度
                if progress_done % 20 == 0:
                    logger.info(f"[dirscan] task={task_id} progress={progress_done}/{task.progress_total} "
                          f"pool={len(pool.pool)} wrote={wrote_count} file_done={file_done} "
                          f"last={host['host']}:{host['port']}{path} status={last_status}")

                if not pool.return_one(host):
                    pool.cleanup_host(host)
                    save_progress(task_id, host["protocol"], host["host"], host["port"],
                                  host["offset"], host["counter"], ttl)

                if progress_done % 100 == 0:
                    await asyncio.to_thread(_sync_save_file_pos, task_id, file_pos, ttl)
                    await asyncio.to_thread(_sync_update_heartbeat, task_id)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

    asyncio.run(_scan_loop())

    # 保存最终 file_pos
    save_file_pos(task_id, file_pos, ttl)

    # 终态：检查暂停/停止标志
    final_done = models.DirScanTask.objects.filter(id=task_id).values_list(
        "progress_done", flat=True
    ).first() or 0
    flags = models.DirScanTask.objects.filter(id=task_id).values(
        "status", "pause_requested", "stop_requested",
    ).first()
    current_status = flags["status"] if flags else 3
    is_paused = flags["pause_requested"] if flags else False
    is_stopped = flags["stop_requested"] if flags else False

    if is_paused or current_status == 2:  # 暂停
        models.DirScanTask.objects.filter(id=task_id).update(
            status=2, pause_requested=False, stop_requested=False,
        )
        logger.info(f"[dirscan] task={task_id} PAUSED progress={final_done}/{task.progress_total} wrote={wrote_count}")
        return {"status": "paused", "task_id": task_id}
    if is_stopped or current_status == 3:  # 停止
        pool.cleanup_all()
        models.DirScanTask.objects.filter(id=task_id).update(
            status=3, pause_requested=False, stop_requested=False, end_time=timezone.now(),
        )
        logger.info(f"[dirscan] task={task_id} STOPPED progress={final_done}/{task.progress_total} wrote={wrote_count}")
        return {"status": "stopped", "task_id": task_id}

    # 扫描完成，进入漏洞扫描阶段或完成
    pool.cleanup_all()
    connection.close()
    logger.info(f"[dirscan] task={task_id} phase1 done progress={final_done}/{task.progress_total} wrote={wrote_count}")
    if task.enable_vuln_scan:
        logger.info(f"[dirscan] task={task_id} entering phase=2 vuln scan")
        models.DirScanTask.objects.filter(id=task_id).update(phase=2)
        _run_dir_scan_phase2(task_id, dispatch_token, owner, proxies_dict, task_args)
    else:
        logger.info(f"[dirscan] task={task_id} entering phase=3 writeback")
        _run_dir_scan_phase3(task_id)
        models.DirScanTask.objects.filter(id=task_id).update(status=4, end_time=timezone.now(), queued=False)
        logger.info(f"[dirscan] task={task_id} COMPLETED")
    return {"status": "completed", "task_id": task_id}


def _run_dir_scan_phase2(task_id, dispatch_token, owner, proxies_dict=None, task_args=None):
    """Phase 2 漏洞验证：匹配产品→加载POC→执行verify→保存结果。

    复用 auto scan 的 POC 加载/执行和结果事件流管道。
    生产者线程遍历 directory_result，消费者线程执行验证，写入线程发布结果。
    """
    from queue import Queue, Empty
    from threading import Thread, Event

    from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import (
        load_runtime_module_from_poc, call_runtime_method,
    )
    from app_cybersparker.services.result_event_service import (
        build_auto_exp_event_payload, publish_result_events,
        throttle_dispatch_result_writer, STREAM_AUTO_EXP,
    )

    total_results = models.auto_scan_directory_result.objects.filter(task_id=task_id).count()
    if total_results == 0:
        logger.info(f"[dirscan] task={task_id} phase2 skip - no dir results")
        return {"status": "completed", "task_id": task_id}

    task_zone_id = models.DirScanTask.objects.filter(id=task_id).values_list("zone_id", flat=True).first()
    if task_zone_id is None:
        task_zone_id = 1  # 兜底公网

    # 预加载产品→EXP 缓存
    fingerprint_exp_cache = {}
    try:
        relates = models.exp_relate_fingerprint.objects.select_related(
            "EXP_id", "fingerprint_id",
        ).exclude(EXP_id__severity="info").all()
        for rel in relates:
            product = rel.fingerprint_id.product
            exp_id = rel.EXP_id.id
            if exp_id not in fingerprint_exp_cache:
                fingerprint_exp_cache[exp_id] = {
                    "poc": rel.EXP_id.poc.name,
                    "products": set(),
                    "plugin_language": int(getattr(rel.EXP_id, "plugin_language", 1) or 1),
                }
            fingerprint_exp_cache[exp_id]["products"].add(product)
    finally:
        connection.close()
    logger.info(f"[dirscan] task={task_id} phase2 cache loaded: {len(fingerprint_exp_cache)} exp entries")

    def _match_exps(products):
        ids = set()
        plist_set = set(products)
        for exp_id, info in fingerprint_exp_cache.items():
            if info["products"] & plist_set:
                ids.add(exp_id)
        return ids

    vuln_thread_num = 1
    try:
        t = models.DirScanTask.objects.filter(id=task_id).values("vuln_thread_num").first()
        if t:
            vuln_thread_num = max(1, int(t["vuln_thread_num"] or 1))
    finally:
        connection.close()

    input_queue = Queue(maxsize=vuln_thread_num * 4)
    result_queue = Queue()
    exit_flag = Event()

    batch_size = 200
    cursor = 0
    processed = 0
    vuln_written = 0

    def producer():
        nonlocal cursor, processed
        while not exit_flag.is_set():
            sig, should_break = _sync_check_status(task_id)
            if should_break:
                exit_flag.set()
                break

            try:
                batch = list(
                    models.auto_scan_directory_result.objects
                    .filter(task_id=task_id, id__gt=cursor)
                    .order_by("id")[:batch_size]
                )
            finally:
                connection.close()

            if not batch:
                exit_flag.set()
                break

            for row in batch:
                if exit_flag.is_set():
                    break
                if not row.products:
                    continue
                exp_ids = _match_exps(row.products)
                if not exp_ids:
                    continue
                target = f"{row.protocol}://{row.host}:{row.port}"
                for exp_id in exp_ids:
                    input_queue.put((exp_id, target, row.products[0]))

            cursor = batch[-1].id
            processed += len(batch)
            if processed % 1000 == 0 or processed <= len(batch):
                logger.info(f"[dirscan] task={task_id} phase2 producer progress={processed}/{total_results}")

        for _ in range(vuln_thread_num):
            input_queue.put(None)

    def consumer(worker_id):
        close_old_connections()
        if proxies_dict is not None:
            set_task_proxy(dict(proxies_dict))
        while True:
            try:
                item = input_queue.get(timeout=1)
            except Empty:
                if exit_flag.is_set():
                    break
                continue
            if item is None:
                break
            exp_id, target, product = item

            try:
                info = fingerprint_exp_cache.get(exp_id)
                if not info:
                    continue
                exp_module = load_runtime_module_from_poc(info["poc"], exp_id=exp_id)
                plugin_language = info["plugin_language"]
                target_dict = {"target": target}
                if plugin_language != 2:
                    target_dict["task_args"] = task_args or {}
                result = call_runtime_method(exp_module, "verify", target_dict)
                if not result:
                    continue
                if plugin_language == 2:
                    out = {
                        "exp_id": exp_id, "target": target,
                        "product": product,
                        "result": result.get("result", "") if isinstance(result, dict) else str(result),
                    }
                else:
                    out = dict(result or {})
                    out["product"] = product
                    out["exp_id"] = exp_id
                result_queue.put(out)
            except Exception:
                import traceback
                traceback.print_exc()
                logger.exception(f"[dirscan] task={task_id} phase2 consumer POC error exp_id={exp_id} target={target}")

    def result_writer():
        nonlocal vuln_written
        batch = []
        while True:
            try:
                item = result_queue.get(timeout=2)
            except Empty:
                if exit_flag.is_set() and result_queue.empty():
                    break
                continue
            batch.append(item)
            if len(batch) >= 50:
                payloads = [
                    build_auto_exp_event_payload(
                        task_id, r["exp_id"], r["target"], r["product"], r.get("result", ""), task_type=2, zone_id=task_zone_id,
                    ) for r in batch
                ]
                publish_result_events(STREAM_AUTO_EXP, payloads)
                throttle_dispatch_result_writer(STREAM_AUTO_EXP)
                vuln_written += len(batch)
                logger.info(f"[dirscan] task={task_id} phase2 flushed {len(batch)} results (total={vuln_written})")
                batch.clear()

        if batch:
            payloads = [
                build_auto_exp_event_payload(
                    task_id, r["exp_id"], r["target"], r["product"], r.get("result", ""), task_type=2, zone_id=task_zone_id,
                ) for r in batch
            ]
            publish_result_events(STREAM_AUTO_EXP, payloads)
            throttle_dispatch_result_writer(STREAM_AUTO_EXP)
            vuln_written += len(batch)

    threads = []
    p = Thread(target=producer, daemon=True)
    p.start()
    threads.append(p)

    for i in range(vuln_thread_num):
        c = Thread(target=consumer, args=(i,), daemon=True)
        c.start()
        threads.append(c)

    w = Thread(target=result_writer, daemon=True)
    w.start()
    threads.append(w)

    for t in threads:
        t.join()

    sig, _ = _sync_check_status(task_id)
    if sig == "pause":
        models.DirScanTask.objects.filter(id=task_id).update(
            status=2, phase=2, pause_requested=False,
        )
        logger.info(f"[dirscan] task={task_id} phase2 PAUSED processed={processed} written={vuln_written}")
        return {"status": "paused", "task_id": task_id}
    if sig == "stop":
        models.DirScanTask.objects.filter(id=task_id).update(
            status=3, phase=2, stop_requested=False, end_time=timezone.now(),
        )
        logger.info(f"[dirscan] task={task_id} phase2 STOPPED processed={processed} written={vuln_written}")
        return {"status": "stopped", "task_id": task_id}

    logger.info(f"[dirscan] task={task_id} phase2 done processed={processed} vuln_written={vuln_written}")
    models.DirScanTask.objects.filter(id=task_id).update(phase=3)
    close_old_connections()
    _run_dir_scan_phase3(task_id)
    models.DirScanTask.objects.filter(id=task_id).update(status=4, end_time=timezone.now(), queued=False)
    logger.info(f"[dirscan] task={task_id} COMPLETED")
    return {"status": "completed", "task_id": task_id}
def _run_dir_scan_phase3(task_id):
    """Phase 3 回写清理：批量更新参与扫描的根资产的 dir_products。"""
    close_old_connections()

    # 检查暂停/停止信号
    sig, should_break = _sync_check_status(task_id)
    if should_break:
        logger.info(f"[dirscan] task={task_id} phase3 skipped due to {sig} signal")
        if sig == "stop":
            models.DirScanTask.objects.filter(id=task_id).update(
                status=3, stop_requested=False, end_time=timezone.now(),
            )
        return

    updated_roots = 0
    targets = set()
    try:
        task = models.DirScanTask.objects.get(id=task_id)
        # 从 shuffle_file 读取参与本次扫描的 root 列表
        if task.shuffle_file and os.path.exists(task.shuffle_file):
            with open(task.shuffle_file) as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        targets.add((parts[0], parts[1], int(parts[2])))

            if not targets:
                logger.info(f"[dirscan] task={task_id} phase3 no targets")
                return

            # 一次查询取出本任务所有目录扫描结果的 products，按 (protocol,host,port) 分组
            from collections import defaultdict
            dps_by_key = defaultdict(list)
            for row in models.auto_scan_directory_result.objects.filter(
                task_id=task_id
            ).values_list("protocol", "host", "port", "products"):
                dps_by_key[(row[0], row[1], row[2])].append(row[3])

            # 批量更新 dir_products
            for protocol, host, port in targets:
                try:
                    dps = dps_by_key.get((protocol, host, port), [])
                    merged = sorted(set(p for arr in dps for p in arr if p))
                    models.auto_scan_indentify_result.objects.filter(
                        protocol=protocol, host=host, port=port
                    ).update(dir_products=merged)
                    if merged:
                        updated_roots += 1
                except Exception:
                    pass
        logger.info(f"[dirscan] task={task_id} phase3 done targets={len(targets)} updated_roots={updated_roots}")
    finally:
        connection.close()
