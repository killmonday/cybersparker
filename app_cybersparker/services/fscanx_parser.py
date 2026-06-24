"""
fscanx 输出文件解析器。
解析 fscanx 扫描结果，提取资产数据写入 auto_scan_indentify_result，
提取服务详情（弱口令/未授权访问/FTP清单/SMB清单/OS信息/RDP信息/漏洞资产等）写入 fscanx_service_detail。
"""
import re
import socket
import traceback
from urllib.parse import urlparse
from datetime import timezone as tz_utc

# ── 预编译正则（避免循环内反复编译）──────────────────────────
_RE_PORT_OPEN = re.compile(r'\[\*\]\s+Port open\s+(\d+\.\d+\.\d+\.\d+):(\d+)\s*(\S*)')
_RE_MASSCAN_LINE = re.compile(r'^\d[^\s]+ open.*?$')
_RE_IP = re.compile(r'\d+\.\d+\.\d+\.\d+')
_RE_PORT = re.compile(r'(?<=:)\d+')
_RE_OPEN_PROTO = re.compile(r'open\s+(\S+)$')
_RE_PRODUCT = re.compile(r'\[\+\]\s+Product\s+(https?://[^\s]+)\s+(\d+)\s+\(([^)]*)\)\s*(.*)')
_RE_BRACKET = re.compile(r'\[([^\]]+)\]')
_RE_OS_INFO = re.compile(r'\[\*\]\s+OsInfo\s+(\d+\.\d+\.\d+\.\d+)\s*\t*\(([^)]+)\)')
_RE_RDP_INFO = re.compile(r'\[\+\]\s+get os info by rdpscan:\s+(\d+\.\d+\.\d+\.\d+):(\d+),\s*(.*)')
_RE_FTP_WEAK = re.compile(r'\[\+\]\s+ftp:(\d+\.\d+\.\d+\.\d+):(\d+):(\S+)\s+(\S+)')
_RE_SMB_WEAK = re.compile(r'\[\+\]\s+smb\s+(\d+\.\d+\.\d+\.\d+):(\d+)\s+(.+)')

_RE_REDIS = re.compile(r'\[\+\]\s+Redis\s+(\d+\.\d+\.\d+\.\d+):(\d+)\s*(.*)')
_RE_GENERIC_WEAK = re.compile(r'\[\+\]\s+(\w+):(\d+\.\d+\.\d+\.\d+):(\d+):(.+)')
_RE_IP_FROM_BRACKET = re.compile(r'\[IP:(\d+\.\d+\.\d+\.\d+)\]')
_RE_IS_IP = re.compile(r'^\d+\.\d+\.\d+\.\d+$')
_RE_TITLE = re.compile(r'<title[^>]*>(.*?)</title>')

# fscanx 证书信息解析：只从 Subject 部分提取（不包含 Issuer 的 O/OU）
_SUBJECT_KV = re.compile(
    r'(?:^|,\s*)'
    r'(CN|O|OU|L|ST|C)='
    r'(.+?)'
    r'(?=,\s*(?:CN|O|OU|L|ST|C)=|$)'
)

# ── 批量写入阈值 ──
DETAIL_BATCH_SIZE = 500

# ── DNS 解析超时（秒）──
DNS_TIMEOUT = 3.0


def normalize_uri_path(raw):
    """统一标准化 uri_path："/" → ""，其他不变。"""
    p = (raw or "").strip()
    return "" if p == "/" else p[:512]


def _parse_cert_info(cert_info):
    """从 fscanx 输出的 [Cert:...] 内容中提取证书字段（仅 Subject 部分）。
    返回 dict，key 为 cert_common_name / cert_org / cert_org_unit。"""
    result = {}
    if not cert_info:
        return result
    # Subject 结束于 Domain= 或 Issuser= 之前
    cut = len(cert_info)
    for marker in (",Domain=", ",Issuser="):
        pos = cert_info.find(marker)
        if pos >= 0:
            cut = min(cut, pos)
    subject_part = cert_info[:cut]
    for m in _SUBJECT_KV.finditer(subject_part):
        key, value = m.group(1), m.group(2).strip()
        if key == "CN":
            result["cert_common_name"] = value[:255]
        elif key == "O":
            result["cert_org"] = value[:255]
        elif key == "OU":
            result["cert_org_unit"] = value[:255]
    return result


def _extract_ip_from_brackets(brackets_text):
    """从 [IP:xxx] 中提取 IP。"""
    m = _RE_IP_FROM_BRACKET.search(brackets_text or "")
    return m.group(1) if m else ""


def _resolve_host_ip(hostname, known_ip=""):
    """域名的 IP：优先用已知 IP（fscanx 输出中已携带），否则尝试 DNS 解析。"""
    cleaned = hostname.strip()
    if not cleaned:
        return cleaned, ""
    # 本身就是 IP
    if _RE_IS_IP.match(cleaned):
        return cleaned, cleaned
    # 有已知 IP 直接用，不走 DNS
    if known_ip:
        return cleaned, known_ip
    # 回退 DNS 解析
    ip = ""
    try:
        addrs = socket.getaddrinfo(cleaned, None, socket.AF_INET, socket.SOCK_STREAM)
        ip = addrs[0][4][0] if addrs else ""
    except Exception:
        pass
    return cleaned, ip


def parse_and_store(fscanx_output, task, conflict_strategy):
    """
    解析 fscanx 输出并存储到数据库。
    返回 (asset_count, detail_count, errors)。
    """
    from django.db import connection as db_conn
    from django.utils import timezone as dj_tz
    from app_cybersparker import models

    lines = fscanx_output.split("\n")
    processed_assets = set()
    asset_count = 0
    detail_count = 0
    errors = []

    # 批量写入缓存：攒够一批再 bulk_create
    detail_batch = []

    def _flush():
        nonlocal detail_count
        if detail_batch:
            models.fscanx_service_detail.objects.bulk_create(detail_batch)
            detail_count += len(detail_batch)
            detail_batch.clear()
        db_conn.close()

    def _save_asset(protocol, host, port, uri_path, defaults):
        nonlocal asset_count
        zone_id = task.zone_id
        key = (zone_id, protocol, host, port, uri_path)
        if key in processed_assets:
            return
        processed_assets.add(key)

        existing = models.auto_scan_indentify_result.objects.filter(
            zone_id=zone_id, protocol=protocol, host=host, port=port, uri_path=uri_path,
        ).first()

        if existing:
            if conflict_strategy != 2:
                for f, v in defaults.items():
                    if f == "products":
                        existing.products = sorted(set(existing.products or []) | set(v or []))
                    else:
                        setattr(existing, f, v)
                existing.source_type = 2
                existing.save()
                asset_count += 1
        else:
            defaults["source_type"] = 2
            defaults["zone"] = task.zone
            defaults["protocol"] = protocol
            defaults["host"] = host
            defaults["port"] = port
            defaults["uri_path"] = uri_path
            existing = models.auto_scan_indentify_result.objects.create(**defaults)
            asset_count += 1

        models.AssetTaskRelation.objects.get_or_create(
            task_id=task.id, identify_result=existing,
        )

    def _save_detail(protocol, host, port, result_type, result_text):
        detail_batch.append(models.fscanx_service_detail(
            task=task,
            protocol=protocol,
            host=host[:255],
            port=port,
            result_type=result_type,
            result=result_text,
        ))
        if len(detail_batch) >= DETAIL_BATCH_SIZE:
            nonlocal detail_count
            models.fscanx_service_detail.objects.bulk_create(detail_batch)
            detail_count += len(detail_batch)
            detail_batch.clear()

    # ---- line parsers ----
    recent_ip = None

    def _parse_port_open(line):
        nonlocal recent_ip
        m = _RE_PORT_OPEN.search(line)
        if m:
            ip, port, protocol = m.group(1), int(m.group(2)), (m.group(3) or "tcp").lower()
            recent_ip = ip
            if protocol == "ssl":
                protocol = "https"
            defaults = {"target": f"{protocol}://{ip}:{port}", "products": [], "ip": ip}
            _save_asset(protocol, ip, port, "", defaults)
            return

        m2 = _RE_MASSCAN_LINE.findall(line)
        if m2:
            for match in m2:
                try:
                    ip_m = _RE_IP.findall(match)
                    port_m = _RE_PORT.findall(match)
                    proto_m = _RE_OPEN_PROTO.findall(match)
                    if ip_m and port_m:
                        ip = ip_m[0]
                        port = int(port_m[0])
                        protocol = (proto_m[0] if proto_m else "tcp").lower()
                        recent_ip = ip
                        defaults = {"target": f"{protocol}://{ip}:{port}", "products": [], "ip": ip}
                        _save_asset(protocol, ip, port, "", defaults)
                except Exception as e:
                    errors.append(f"解析 masscan 格式失败: {line[:80]} - {e}")

    def _parse_product(line):
        nonlocal recent_ip
        m = _RE_PRODUCT.search(line)
        if not m:
            return
        url, http_status, web_title, brackets = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        try:
            urlp = urlparse(url)
            host = urlp.hostname or ""
            port = urlp.port or (443 if urlp.scheme == "https" else 80)
            protocol = urlp.scheme
            uri_path = normalize_uri_path(urlp.path)
            recent_ip = host

            # 优先从 fscanx 输出的 [IP:xxx] 中提取 IP
            known_ip = _extract_ip_from_brackets(brackets)

            products = []
            cert_info = ""
            copyright_val = ""
            icp_val = ""
            for b in _RE_BRACKET.findall(brackets):
                b = b.strip()
                if b.startswith("Cert:"):
                    cert_info = b[5:].strip()
                elif b.startswith("copyright:") or b.startswith("Copyright:"):
                    copyright_val = b.split(":", 1)[1].strip()
                elif b.startswith("ICP:"):
                    icp_val = b[4:].strip()
                elif b and not b.isdigit() and not b.startswith("IP:") and not b.startswith("L:") and not b.startswith("From:"):
                    products.append(b)

            cert_fields = _parse_cert_info(cert_info)

            host_part, ip_part = _resolve_host_ip(host, known_ip)
            defaults = {
                "target": url,
                "ip": ip_part or host_part,
                "status_code": http_status,
                "title": web_title[:255] if web_title else "",
                "products": products,
                "country": "",
            }
            if cert_fields.get("cert_common_name"):
                defaults["cert_common_name"] = cert_fields["cert_common_name"]
            if cert_fields.get("cert_org"):
                defaults["cert_org"] = cert_fields["cert_org"]
            if cert_fields.get("cert_org_unit"):
                defaults["cert_org_unit"] = cert_fields["cert_org_unit"]
            if copyright_val:
                defaults["copyright"] = copyright_val[:512]
            if icp_val:
                defaults["icp"] = icp_val[:128]
            _save_asset(protocol, host_part[:255], port, uri_path, defaults)
        except Exception as e:
            errors.append(f"解析 Product 行失败: {line[:80]} - {e}")

    def _parse_os_info(line):
        nonlocal recent_ip
        m = _RE_OS_INFO.search(line)
        if m:
            ip, os_ver = m.group(1), m.group(2).strip()
            recent_ip = ip
            _save_detail("tcp", ip, 445, 4, f"操作系统: {os_ver}")

    def _parse_rdp_info(line):
        nonlocal recent_ip
        m = _RE_RDP_INFO.search(line)
        if m:
            ip, port, info = m.group(1), int(m.group(2)), m.group(3)
            recent_ip = ip
            _save_detail("rdp", ip, port, 5, info.strip())

    def _parse_ftp_weak(line, all_lines, idx):
        nonlocal recent_ip
        m = _RE_FTP_WEAK.search(line)
        if not m:
            return None
        ip, port, user, pwd = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        recent_ip = ip
        _save_detail("ftp", ip, port, 1, f"账号: {user}  密码: {pwd}")
        dir_lines = []
        for j in range(idx + 1, min(idx + 500, len(all_lines))):
            sub = all_lines[j]
            if sub.startswith("[->]") or sub.startswith("   [->]"):
                dir_lines.append(sub.strip())
            elif sub.startswith("[+]") or sub.startswith("[*]") or sub.startswith("==="):
                break
        if dir_lines:
            _save_detail("ftp", ip, port, 2, "\n".join(dir_lines))
        return ip

    def _parse_smb_weak(line, all_lines, idx):
        nonlocal recent_ip
        m = _RE_SMB_WEAK.search(line)
        if not m:
            return None
        ip, port, desc = m.group(1), int(m.group(2)), m.group(3)
        recent_ip = ip
        _save_detail("smb", ip, port, 1, desc.strip())
        share_lines = []
        for j in range(idx + 1, min(idx + 500, len(all_lines))):
            sub = all_lines[j]
            if sub.startswith("[->]") or sub.startswith("   [->]"):
                share_lines.append(sub.strip())
            elif sub.startswith("[+]") or sub.startswith("[*]") or sub.startswith("==="):
                break
        if share_lines:
            _save_detail("smb", ip, port, 3, "\n".join(share_lines))
        return ip

    def _parse_redis(line):
        """解析 Redis 弱口令/未授权访问。fscanx 输出格式: [+] Redis IP:PORT <password> [file:<dir>/<file>]"""
        nonlocal recent_ip
        m = _RE_REDIS.match(line)
        if not m:
            return
        ip, port, detail = m.group(1), int(m.group(2)), m.group(3).strip()
        recent_ip = ip
        detail_lower = detail.lower()
        if not detail or detail_lower.startswith("unauthorized") or detail_lower in ("no auth", "无授权", "未授权"):
            _save_detail("redis", ip, port, 10, detail or "未授权访问")
        else:
            _save_detail("redis", ip, port, 1, detail[:65535])

    def _parse_other_weak(line):
        nonlocal recent_ip
        m = _RE_GENERIC_WEAK.match(line)
        if not m:
            return
        proto, ip, port, cred = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        recent_ip = ip
        _save_detail(proto.lower(), ip, port, 1, cred.strip())

    def _parse_infoscan(line):
        nonlocal recent_ip
        if "InfoScan" not in line:
            return
        url_m = _RE_IP.findall(line)  # 找 URL 中的 IP
        if not url_m:
            return
        # 从 InfoScan 行提取完整 URL
        url_match = re.search(r'(https?://[^\s]+)', line)
        url = url_match.group(1) if url_match else f"http://{url_m[0]}"
        try:
            urlp = urlparse(url)
            host = urlp.hostname or ""
            port = urlp.port or (443 if url.startswith("https:") else 80)
            protocol = urlp.scheme or "http"
            recent_ip = host
            fingerprint = line.split(url)[-1].strip() if url in line else ""
            bracket_fps = _RE_BRACKET.findall(fingerprint)
            if bracket_fps:
                fingerprint = ", ".join(bracket_fps)
            _save_detail(protocol, host[:255], port, 6, fingerprint[:65535])
        except Exception as e:
            errors.append(f"解析 InfoScan 行失败: {line[:80]} - {e}")

    def _parse_netinfo(line, all_lines, start_idx):
        """解析 NetInfo 块: [*] NetInfo / [*]target_ip / [->]hostname / [->]ip ..."""
        nonlocal recent_ip
        idx = start_idx + 1
        target_ip = ""
        details = []
        while idx < len(all_lines):
            nl = all_lines[idx].strip()
            if not nl:
                idx += 1; continue
            if nl.startswith("[*]") and "NetInfo" not in nl:
                ip_m = _RE_IP.search(nl)
                if ip_m:
                    target_ip = ip_m.group(0)
                    recent_ip = target_ip
            elif nl.startswith("[->]"):
                detail = nl[4:].strip()
                if detail:
                    details.append(detail)
            else:
                break
            idx += 1
        if target_ip:
            for d in details:
                _save_detail("netbios", target_ip, 0, 7, d[:65535])
        return idx - 1

    def _parse_netbios(line):
        """解析 NetBios 主机名: [*] NetBios 192.168.1.32    WORKGROUP\\HOSTNAME"""
        nonlocal recent_ip
        m = re.match(r'\[\*\]\s*Net[Bb]ios\s+(\S+)\s+(.+)', line)
        if m:
            ip, info = m.group(1), m.group(2).strip()
            recent_ip = ip
            _save_detail("netbios", ip, 0, 8, info[:65535])

    def _parse_ms17010(line):
        """解析 MS17-010 漏洞: [+] MS17-010 192.168.1.32       (Windows 7 ...)"""
        nonlocal recent_ip
        m = re.match(r'\[\+\]\s*MS17-?010\s+(\S+)\s*(.*)', line)
        if m:
            ip, info = m.group(1), m.group(2).strip().strip('()')
            recent_ip = ip
            _save_detail("smb", ip, 445, 9, info[:65535])

    # ---- main parse loop ----
    idx = 0
    heartbeat_counter = 0
    while idx < len(lines):
        line = lines[idx]
        try:
            line_stripped = line.strip()
            if not line_stripped:
                idx += 1
                heartbeat_counter += 1
                continue

            if line_stripped.startswith("[*] Port open"):
                _parse_port_open(line_stripped)
            elif line_stripped.startswith("[+] Product"):
                _parse_product(line_stripped)
            elif line_stripped.startswith("[*] OsInfo"):
                _parse_os_info(line_stripped)
            elif line_stripped.startswith("[+] get os info by rdpscan"):
                _parse_rdp_info(line_stripped)
            elif line_stripped.startswith("[+] ftp:"):
                _parse_ftp_weak(line_stripped, lines, idx)
            elif line_stripped.startswith("[+] smb "):
                _parse_smb_weak(line_stripped, lines, idx)
            elif line_stripped.startswith("[+] Redis "):
                _parse_redis(line_stripped)
            elif line_stripped.startswith("[+]") and _RE_GENERIC_WEAK.match(line_stripped):
                _parse_other_weak(line_stripped)
            elif "InfoScan" in line_stripped:
                _parse_infoscan(line_stripped)
            elif line_stripped.startswith("[*] NetInfo"):
                idx = _parse_netinfo(line_stripped, lines, idx)
            elif line_stripped.startswith("[*] NetBios"):
                _parse_netbios(line_stripped)
            elif line_stripped.startswith("[+] MS17-010"):
                _parse_ms17010(line_stripped)
            elif _RE_IS_IP.match(line_stripped.split(":")[0] if ":" in line_stripped else ""):
                _parse_port_open(line_stripped)
        except Exception as e:
            errors.append(f"解析第 {idx} 行失败: {line[:80]} - {e}")
            traceback.print_exc()
        idx += 1
        heartbeat_counter += 1

        # 心跳 + 停止检查：每 500 行（降频减少 DB 争用）
        if heartbeat_counter >= 500:
            heartbeat_counter = 0
            try:
                freshest = models.auto_scan_tasks.objects.filter(id=task.id).only("stop_requested", "heartbeat_at").first()
                if freshest:
                    if freshest.stop_requested:
                        errors.append("任务已停止")
                        break
                    models.auto_scan_tasks.objects.filter(id=task.id).update(heartbeat_at=dj_tz.now())
                _flush()
            except Exception:
                pass

    _flush()  # 最后一批
    return asset_count, detail_count, errors


def run_import(task):
    """
    独立线程入口。返回 (success, message)。
    """
    from datetime import timezone
    from django.db import connection as db_conn
    from django.utils import timezone as dj_tz
    from app_cybersparker import models

    try:
        db_conn.close()
    except Exception:
        pass

    try:
        task.status = 2  # running
        task.process = "0%"
        task.startTime = dj_tz.now()
        task.failed = False
        task.last_error = ""
        task.heartbeat_at = dj_tz.now()
        task.save()
        db_conn.close()
    except Exception as e:
        return False, f"更新任务状态失败: {e}"

    try:
        filepath = task.fscanx_file.path
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        db_conn.close()
    except Exception as e:
        task.status = 3
        task.failed = True
        task.last_error = f"读取文件失败: {e}"
        task.endTime = dj_tz.now()
        task.save()
        db_conn.close()
        return False, task.last_error

    try:
        asset_total, detail_total, all_errors = parse_and_store(
            content, task, task.conflict_strategy,
        )
    except Exception as e:
        traceback.print_exc()
        task.status = 3
        task.failed = True
        task.last_error = f"解析异常: {e}"
        task.endTime = dj_tz.now()
        task.save()
        db_conn.close()
        return False, task.last_error

    db_conn.close()

    try:
        task.status = 1  # finish
        task.process = "100%"
        task.endTime = dj_tz.now()
        task.failed = False
        if all_errors:
            task.last_error = f"部分行解析失败 ({len(all_errors)} 处): " + "; ".join(all_errors[:5])
        task.save()
        db_conn.close()
    except Exception:
        pass

    return True, f"导入完成: {asset_total} 条资产, {detail_total} 条服务详情"
