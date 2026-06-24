from django.db.models import Q
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.permissions import deny_user
from django.http import JsonResponse

from datetime import datetime
import re
import traceback
import httpx
import asyncio
import hashlib
import base64
import mmh3
import ssl
import os
import tempfile
from urllib.parse import urlparse, urljoin

import cybersparker.settings as sett
from bs4 import BeautifulSoup as BS

# ======================== JSON API wrappers ========================
import json as _json


@deny_user
def api_fingerprint_list(request):
    """GET: return fingerprint list for debug page dropdown.
    Query params: search (filters product/condition via icontains, max 50 results)
    Without search: returns latest 200 fingerprints."""
    search = request.GET.get("search", "").strip()
    qs = models.fingerPrint.objects.all()
    if search:
        qs = qs.filter(
            Q(product__icontains=search) | Q(condition__icontains=search)
        )
    total = qs.count()
    rows = qs.values("id", "product", "condition").order_by("-id")[:200 if not search else 50]
    return JsonResponse({"status": True, "data": _builtin_list(rows), "total": total})


@deny_user
def api_fingerprint_mate(request):
    """POST JSON: {url, regex, proxy, match_all_fingerprints}"""
    try:
        body = _json.loads(request.body.decode("utf-8"))
        from django.http import QueryDict
        qd = QueryDict(mutable=True)
        qd["url"] = str(body.get("url", ""))
        qd["regex"] = str(body.get("regex", ""))
        qd["proxy"] = str(body.get("proxy", ""))
        if body.get("match_all_fingerprints"):
            qd["match_all_fingerprints"] = "1"
        qd._mutable = False
        request._post = qd
        return mate(request)
    except Exception as e:
        return JsonResponse({"status": False, "error": str(e)})


#
pwd = sett.THIS_DIR

FAVICON_DIR = os.path.join(sett.STATIC_ROOT, 'favicons')
os.makedirs(FAVICON_DIR, exist_ok=True)

_MEDIA_TO_EXT = {
    'image/x-icon': 'ico', 'image/vnd.microsoft.icon': 'ico',
    'image/png': 'png', 'image/svg+xml': 'svg',
    'image/gif': 'gif', 'image/jpeg': 'jpg', 'image/webp': 'webp',
}


def _save_favicon_file(content_bytes, media_type):
    md5 = hashlib.md5(content_bytes).hexdigest()
    mt = (media_type or '').split(';')[0].strip().lower()
    ext = _MEDIA_TO_EXT.get(mt, 'ico')
    filename = f"{md5}.{ext}"
    filepath = os.path.join(FAVICON_DIR, filename)
    if not os.path.exists(filepath):
        with open(filepath, 'wb') as f:
            f.write(content_bytes)
    return f"/static/favicons/{filename}"


def error_log(e_info,tips):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open (error_log_path,"a+") as f:
            f.write(f"[expload {tips}] {now_time} : " +  e_info + "\n")
            f.close()
    except:
        pass

_builtin_list = list

@deny_user
def list(request):
    proxy_query= models.ProxySetting.objects.all().values("id", "proxy_type", "proxy_address", "proxy_port").order_by("-id")
    all_proxy_list = []
    for proxy_dict in proxy_query:
        proxy_id = proxy_dict["id"]
        proxy_type = proxy_dict["proxy_type"]
        protocol_type_str = models.ProxySetting(proxy_type=proxy_type).get_proxy_type_display()
        proxy_dict["proxy_type"] = protocol_type_str
        proxy = {"id":proxy_id,"proxy": f"{str(protocol_type_str)}://{str(proxy_dict['proxy_address'])}:{str(proxy_dict['proxy_port'])}"}
        all_proxy_list.append(proxy)

    fingerprint_list = models.fingerPrint.objects.all().values("id", "product", "condition").order_by("-id")

    return render(request, 'project/expload/fingerprint_debug.html',{"data": all_proxy_list, "fingerprints": fingerprint_list})

def requests_headers() -> dict[str, str]:
    return {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    }


from app_cybersparker.services.fingerprint_matcher import (
    check_rule as _shared_check_rule,
    match_condition,
    regular_rtitle,
    regular_rheader,
    regular_rbody,
)

regular_error = False
matched_text = ""

def _debug_regulations_mate(model, key, search_data):
    global regular_error, matched_text
    try:
        regex_pattern = re.compile(str(re.findall(model, key)[0]))
        match = regex_pattern.search(search_data)
        regular_error = False
        if match:
            matched_text = str(match.group())
            return True
        return False
    except re.error as e:
        print(f"[fingerPrint_debug] 正则错误 | 规则片段: {key} | 错误: {e}")
        regular_error = True
        return False


def _check_rule_with_info(key, header, body, title, context=None):
    """对 ~= 规则跟踪 matched_text，其余委托给共享模块"""
    if 'title~="' in str(key):
        return _debug_regulations_mate(regular_rtitle, key, title)
    if 'body~="' in str(key):
        return _debug_regulations_mate(regular_rbody, key, body)
    if 'header~="' in str(key):
        return _debug_regulations_mate(regular_rheader, key, str(header))
    return _shared_check_rule(key, header, body, title, context=context)


# ---- favicon helpers ----

def _extract_html_attr(tag, attr):
    m = re.search(rf'{attr}\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
    return m.group(1) if m else ""

def _build_favicon_candidates(url, content):
    candidates = []
    for match in re.finditer(r'<link\b[^>]*>', content or "", re.IGNORECASE):
        tag = match.group(0)
        rel = _extract_html_attr(tag, "rel").lower()
        if "icon" not in rel:
            continue
        href = _extract_html_attr(tag, "href")
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
    for c in candidates:
        if c in seen:
            continue
        seen.append(c)
        deduped.append(c)
    return deduped[:5]

def _looks_like_favicon(url, content_type, content_bytes):
    if not content_bytes or len(content_bytes) > 524288:
        return False
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
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

def _favicon_media_type(url, content_type):
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return ct.split(";")[0].strip()
    lower_url = (url or "").lower()
    if lower_url.endswith(".ico"):
        return "image/x-icon"
    if lower_url.endswith(".png"):
        return "image/png"
    if lower_url.endswith(".svg"):
        return "image/svg+xml"
    if lower_url.endswith(".gif"):
        return "image/gif"
    return "image/x-icon"


# ---- certificate helpers ----

def _extract_cert_subject_value(peercert, key):
    for group in peercert.get("subject", ()):
        for item in group:
            if len(item) == 2 and item[0] == key:
                return item[1]
    return ""

def _normalize_cert_info(peercert):
    if not peercert:
        return {}
    cert_serial = peercert.get("serialNumber") or peercert.get("serial_number") or ""
    return {
        "cert_org": (_extract_cert_subject_value(peercert, "organizationName") or "")[:255] or None,
        "cert_org_unit": (_extract_cert_subject_value(peercert, "organizationalUnitName") or "")[:255] or None,
        "cert_common_name": (_extract_cert_subject_value(peercert, "commonName") or "") or None,
        "cert_serial": str(cert_serial)[:128] or None,
    }

def _decode_cert_binary(cert_binary):
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


# ---- async collection functions ----

async def _fetch_favicon_async(client, url, content):
    for candidate in _build_favicon_candidates(url, content):
        try:
            response = await client.get(candidate, timeout=5)
            if response.status_code >= 400:
                continue
            content_bytes = response.content
            if not content_bytes:
                continue
            content_type = response.headers.get("Content-Type", "")
            if not _looks_like_favicon(candidate, content_type, content_bytes):
                continue
            media_type = _favicon_media_type(candidate, content_type)
            favicon_path = _save_favicon_file(content_bytes, media_type)
            return {
                "favicon": favicon_path,
                "favicon_md5": hashlib.md5(content_bytes).hexdigest(),
                "favicon_mmh3": str(mmh3.hash(base64.b64encode(content_bytes))),
            }
        except Exception:
            continue
    return {"favicon": None, "favicon_md5": None, "favicon_mmh3": None}

async def _fetch_certificate_async(url, response):
    if urlparse(url).scheme != "https":
        return {}
    try:
        ssl_obj = response.extensions.get("ssl_object")
        if ssl_obj:
            cert_binary = ssl_obj.getpeercert(binary_form=True)
            cert_info = _normalize_cert_info(_decode_cert_binary(cert_binary))
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
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        conn_task = asyncio.ensure_future(
            asyncio.open_connection(host, parsed.port or 443, ssl=ssl_context),
        )
        _, writer = await asyncio.wait_for(
            conn_task,
            timeout=5,
        )
        ssl_obj = writer.get_extra_info("ssl_object")
        if ssl_obj is None:
            return {}
        cert_binary = ssl_obj.getpeercert(binary_form=True)
        return _normalize_cert_info(_decode_cert_binary(cert_binary))
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

async def _handle_js_redirect_async(client, url, content):
    from app_cybersparker.services.js_redirect import get_js_redirect_url
    js_redirect = get_js_redirect_url(content)
    if not js_redirect or js_redirect.startswith("javascript:") or js_redirect.startswith("#"):
        return {"uri_path": (urlparse(url).path or "/")[:512], "redirect_url": None}
    parsed_original = urlparse(url)
    if js_redirect.startswith("http"):
        redirect_url = js_redirect
    elif js_redirect.startswith("/"):
        redirect_url = f"{parsed_original.scheme}://{parsed_original.hostname}:{parsed_original.port}{js_redirect}"
    else:
        redirect_url = f"{parsed_original.scheme}://{parsed_original.hostname}:{parsed_original.port}/{js_redirect}"
    try:
        resp = await client.get(redirect_url, timeout=12)
        parsed_final = urlparse(str(resp.url))
        redirect_header = f"HTTP/1.1 {resp.status_code}\n" + "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        redirect_content = resp.text
        try:
            redirect_title = BS(redirect_content, 'html.parser').title.text.strip()
        except Exception:
            redirect_title = ''
        return {
            "uri_path": (parsed_final.path or "/")[:512],
            "redirect_url": redirect_url,
            "redirect_status_code": resp.status_code,
            "redirect_header": redirect_header,
            "redirect_content": redirect_content,
            "redirect_title": redirect_title,
        }
    except Exception:
        return {"uri_path": (urlparse(url).path or "/")[:512], "redirect_url": None}


def _build_context_from_extras(favicon_result, cert_result, redirect_result):
    cert_parts = []
    for value in [
        cert_result.get("cert_org"),
        cert_result.get("cert_org_unit"),
        cert_result.get("cert_common_name"),
    ]:
        if value and value not in cert_parts:
            cert_parts.append(value)
    return {
        "favicon": favicon_result.get("favicon_md5") or favicon_result.get("favicon"),
        "favicon_md5": favicon_result.get("favicon_md5"),
        "favicon_mmh3": favicon_result.get("favicon_mmh3"),
        "cert": " ".join(cert_parts) if cert_parts else None,
        "cert_org": cert_result.get("cert_org"),
        "cert_org_unit": cert_result.get("cert_org_unit"),
        "cert_common_name": cert_result.get("cert_common_name"),
        "cert_serial": cert_result.get("cert_serial"),
        "uri_path": redirect_result.get("uri_path"),
    }


def inputFingerIsTrue(fingerprint):
    pattern = r'(cert_common_name|cert_org_unit|cert_serial|cert_org|favicon_mmh3|favicon_md5|cert|favicon|uri_path|title|body|header)(=|~=|!=)(.*)'
    match = re.match(pattern, fingerprint)
    if match:
        return True
    return False


def evaluate_fingerprint(header, body, title, fingerprint, context=None):
    global regular_error, matched_text
    regular_error = False
    matched_text = ""
    matched = match_condition(
        fingerprint, header, body, title, context=context,
        rule_fn=_check_rule_with_info,
    )
    return {
        "matched": matched,
        "matched_text": matched_text,
        "regular_error": regular_error,
    }


def collect_library_matches(header, body, title, current_fingerprint, fingerprint_rows, context=None):
    matched_fingerprints = []
    for item in fingerprint_rows:
        condition = item["condition"]
        if condition == current_fingerprint:
            continue
        match_result = evaluate_fingerprint(header, body, title, condition, context=context)
        if match_result["matched"]:
            matched_fingerprints.append({
                "name": item["product"],
                "condition": condition,
                "matched_text": match_result["matched_text"],
            })
    return matched_fingerprints


def _prefetch_fingerprint_rows():
    return _builtin_list(
        models.fingerPrint.objects.all().values("product", "condition").order_by("-id")
    )


async def _run_io_block(client, url):
    """首次请求不跟随重定向 → 捕获 302 响应；手动跟随 → 落地页做指纹/JS跳转检测。"""
    # 首次请求：不跟随 HTTP 重定向，显式捕获 3xx 响应
    response = await client.get(url, timeout=12, follow_redirects=False)
    first_status_code = response.status_code
    first_header = f"HTTP/1.1 {response.status_code}\n" + "\n".join(f"{k}: {v}" for k, v in response.headers.items())
    first_content = response.text

    # 如果首次响应是 3xx 且有 Location，手动跟随跳转
    final_url = url
    if 300 <= response.status_code < 400:
        location = response.headers.get("Location") or response.headers.get("location")
        if location:
            from urllib.parse import urljoin
            final_url = urljoin(url, location)
            response = await client.get(final_url, timeout=12)

    header = f"HTTP/1.1 {response.status_code}\n" + "\n".join(f"{k}: {v}" for k, v in response.headers.items())
    content = response.text
    try:
        title = BS(content, 'html.parser').title.text.strip()
    except Exception:
        title = ''

    favicon_result, cert_result, redirect_result = await asyncio.gather(
        _fetch_favicon_async(client, final_url, content),
        _fetch_certificate_async(final_url, response),
        _handle_js_redirect_async(client, final_url, content),
        return_exceptions=True,
    )
    if isinstance(favicon_result, Exception):
        favicon_result = {"favicon": None, "favicon_md5": None, "favicon_mmh3": None}
    if isinstance(cert_result, Exception):
        cert_result = {}
    if isinstance(redirect_result, Exception):
        redirect_result = {"uri_path": (urlparse(final_url).path or "/")[:512], "redirect_url": None}

    return {
        "header": header,
        "content": content,
        "title": title,
        "first_status_code": first_status_code,
        "first_header": first_header,
        "first_content": first_content,
        "favicon": favicon_result,
        "cert": cert_result,
        "redirect": redirect_result,
    }


@deny_user
def mate(request):
    try:
        url = request.POST.get("url")
        # 裸域名（无 scheme）自动补 http://，避免 urlparse 把 host 错解析为 scheme
        if url and "://" not in url:
            url = f"http://{url}"
        fingerprint = request.POST.get("regex")
        proxy = request.POST.get("proxy")
        match_all_fingerprints = request.POST.get("match_all_fingerprints") in {"1", "true", "on"}
        if not inputFingerIsTrue(fingerprint):
            return JsonResponse({"status": False, 'error': "Fingerprint format error, The correct format is: title|body|header|cert|cert_org|cert_org_unit|cert_common_name|cert_serial|favicon|favicon_md5|favicon_mmh3|uri_path=\"xxx\""})
        proxy_url = str(proxy) if proxy else None

        fingerprint_rows = None
        if match_all_fingerprints:
            fingerprint_rows = _prefetch_fingerprint_rows()

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        client_kwargs = {"verify": ssl_ctx, "timeout": httpx.Timeout(12), "headers": requests_headers(), "trust_env": False}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async def _io_block():
            async with httpx.AsyncClient(**client_kwargs) as client:
                return await _run_io_block(client, url)

        io_result = asyncio.run(_io_block())
        header = io_result["header"]
        content = io_result["content"]
        title = io_result["title"]

        context = _build_context_from_extras(io_result["favicon"], io_result["cert"], io_result["redirect"])

        current_match_result = evaluate_fingerprint(header, content, title, fingerprint, context=context)

        matched_fingerprints = []
        if current_match_result["matched"]:
            matched_fingerprints.append({
                "name": "当前调试指纹",
                "condition": fingerprint,
                "matched_text": current_match_result["matched_text"],
            })
        if match_all_fingerprints and fingerprint_rows:
            matched_fingerprints.extend(
                collect_library_matches(header, content, title, fingerprint, fingerprint_rows, context=context)
            )

        result = {
            "status": current_match_result["matched"],
            'response_headers': header,
            'response_data': str(content),
            'matched_text': current_match_result["matched_text"] if current_match_result["matched"] else "",
            "matched_fingerprints": matched_fingerprints,
            "favicon": io_result["favicon"].get("favicon"),
            "favicon_md5": io_result["favicon"].get("favicon_md5"),
            "favicon_mmh3": io_result["favicon"].get("favicon_mmh3"),
            "cert_org": io_result["cert"].get("cert_org"),
            "cert_org_unit": io_result["cert"].get("cert_org_unit"),
            "cert_common_name": io_result["cert"].get("cert_common_name"),
            "cert_serial": io_result["cert"].get("cert_serial"),
            "uri_path": io_result["redirect"].get("uri_path"),
            "redirect_url": io_result["redirect"].get("redirect_url"),
        }

        # HTTP 302 首次响应：对跳转前的响应做指纹匹配
        first_status_code = io_result.get("first_status_code")
        first_header = io_result.get("first_header")
        first_content = io_result.get("first_content")
        if first_status_code is not None and 300 <= first_status_code < 400:
            first_context = _build_context_from_extras(
                io_result["favicon"], io_result["cert"],
                {"uri_path": (urlparse(url).path or "/")[:512]},
            )
            first_match_result = evaluate_fingerprint(
                first_header, first_content, "", fingerprint, context=first_context,
            )
            result["first_status_code"] = first_status_code
            result["first_response_headers"] = first_header
            result["first_response_data"] = first_content
            result["first_status"] = first_match_result["matched"]
            result["first_matched_text"] = (
                first_match_result["matched_text"] if first_match_result["matched"] else ""
            )
            first_matched_fingerprints = []
            if first_match_result["matched"]:
                first_matched_fingerprints.append({
                    "name": "当前调试指纹",
                    "condition": fingerprint,
                    "matched_text": first_match_result["matched_text"],
                })
            if match_all_fingerprints and fingerprint_rows:
                first_matched_fingerprints.extend(
                    collect_library_matches(
                        first_header, first_content, "", fingerprint,
                        fingerprint_rows, context=first_context,
                    )
                )
            result["first_matched_fingerprints"] = first_matched_fingerprints
            if first_match_result.get("regular_error"):
                result["first_regular_error"] = "Regular expression error"

        # JS 跳转目标页指纹匹配
        redirect_info = io_result["redirect"]
        redirect_content = redirect_info.get("redirect_content")
        if redirect_content:
            redirect_header = redirect_info["redirect_header"]
            redirect_title = redirect_info.get("redirect_title", "")
            redirect_context = _build_context_from_extras(
                io_result["favicon"], io_result["cert"], redirect_info
            )
            redirect_match_result = evaluate_fingerprint(
                redirect_header, redirect_content, redirect_title, fingerprint,
                context=redirect_context,
            )

            result["redirect_status_code"] = redirect_info.get("redirect_status_code")
            result["redirect_status"] = redirect_match_result["matched"]
            result["redirect_response_headers"] = redirect_header
            result["redirect_response_data"] = redirect_content
            result["redirect_matched_text"] = (
                redirect_match_result["matched_text"] if redirect_match_result["matched"] else ""
            )

            redirect_matched_fingerprints = []
            if redirect_match_result["matched"]:
                redirect_matched_fingerprints.append({
                    "name": "当前调试指纹",
                    "condition": fingerprint,
                    "matched_text": redirect_match_result["matched_text"],
                })
            if match_all_fingerprints and fingerprint_rows:
                redirect_matched_fingerprints.extend(
                    collect_library_matches(
                        redirect_header, redirect_content, redirect_title,
                        fingerprint, fingerprint_rows, context=redirect_context,
                    )
                )
            result["redirect_matched_fingerprints"] = redirect_matched_fingerprints
            if redirect_match_result.get("regular_error"):
                result["redirect_regular_error"] = "Regular expression error"

        if current_match_result.get("regular_error"):
            result["regular_error"] = "Regular expression error"
        return JsonResponse(result)
    except httpx.HTTPError as http_err:
        return JsonResponse({"status": False, 'error': str(http_err), "matched_fingerprints": []})
    except Exception as e:
        traceback.print_exc()
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "fingerprint_debug error"
        error_log(e_info,tips)
        return JsonResponse({"status": False, "tips": "fingerprint_debug error", "matched_fingerprints": []})
