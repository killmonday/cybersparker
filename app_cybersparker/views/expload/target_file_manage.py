"""目标文件管理 API：列表、上传、下载、删除、批量删除"""
import os
from datetime import datetime

from django.conf import settings as s
from django.http import FileResponse, JsonResponse

from app_cybersparker.models import auto_scan_tasks
from app_cybersparker.models import batch_EXPTask
from app_cybersparker.permissions import deny_user


TARGET_DIR = os.path.join(os.path.dirname(s.THIS_DIR), "EXP_input")
MERGED_DIR = os.path.join(TARGET_DIR, ".merged")
ENGINE_ASSETS_DIR = os.path.join(TARGET_DIR, "engine_assets")
MAX_UPLOAD_SIZE = 30 * 1024 * 1024  # 30MB
ALLOWED_EXT = ".txt"


def _safe_target_path(filename):
    """双重校验：1) 不逃逸项目根目录 2) 在 EXP_input/ 内且不在子目录。

    返回安全的绝对路径，不合法时返回 None。
    """
    raw = os.path.join(TARGET_DIR, str(filename or "").strip())
    # 第一重：get_absolute_target_path 防 ../
    from app_cybersparker.services.cyberspace_engine_service import get_absolute_target_path
    resolved = get_absolute_target_path(raw)
    if not resolved:
        return None
    # 第二重：必须在 EXP_input/ 目录内
    target_norm = os.path.normpath(TARGET_DIR) + os.sep
    resolved_norm = os.path.normpath(resolved)
    if not resolved_norm.startswith(target_norm):
        return None
    # 禁止子目录
    relative = resolved_norm[len(target_norm):]
    if os.sep in relative.rstrip(os.sep):
        return None
    return resolved_norm


def _count_non_empty_lines(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def _list_target_files():
    """列出 EXP_input/ 根目录下所有文件（排除子目录和子目录内容）"""
    files = []
    if not os.path.isdir(TARGET_DIR):
        return files
    for fname in sorted(os.listdir(TARGET_DIR), reverse=True):
        fpath = os.path.join(TARGET_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        mtime = os.path.getmtime(fpath)
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        fsize = os.path.getsize(fpath)
        lines = _count_non_empty_lines(fpath)
        files.append({
            "file_name": fname,
            "mtime": mtime_str,
            "size": fsize,
            "size_display": _format_size(fsize),
            "lines": lines,
        })
    return files


def _find_referencing_tasks(filename):
    """查找引用了该文件名的任务，返回 [(model_label, task_id), ...]"""
    refs = []
    for t in auto_scan_tasks.objects.filter(history_files__icontains=filename):
        if filename in (t.history_files or "").split(","):
            refs.append(("auto_scan", t.id))
    for t in batch_EXPTask.objects.filter(history_files__icontains=filename):
        if filename in (t.history_files or "").split(","):
            refs.append(("batch", t.id))
    return refs


def _remove_filename_from_history_fields(filename):
    """从所有引用该文件的任务 history_files 字段中移除该文件名"""
    for t in auto_scan_tasks.objects.filter(history_files__icontains=filename):
        files = [f.strip() for f in (t.history_files or "").split(",") if f.strip()]
        if filename in files:
            files.remove(filename)
            t.history_files = ",".join(files)
            t.save(update_fields=["history_files"])
    for t in batch_EXPTask.objects.filter(history_files__icontains=filename):
        files = [f.strip() for f in (t.history_files or "").split(",") if f.strip()]
        if filename in files:
            files.remove(filename)
            t.history_files = ",".join(files)
            t.save(update_fields=["history_files"])


def _resolve_unique_name(filename):
    """给定文件名，如果 TARGET_DIR 下已存在则加数字后缀直到不冲突"""
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(TARGET_DIR, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1
    return candidate


def target_file_list_api(request):
    """GET /api/v1/target-files"""
    files = _list_target_files()
    return JsonResponse({"status": True, "data": {"files": files}})


@deny_user
def target_file_upload_api(request):
    """POST /api/v1/target-files/upload"""
    if request.method != "POST":
        return JsonResponse({"status": False, "data": {"error": "仅支持 POST 方法"}}, status=405)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"status": False, "data": {"error": "未选择文件"}}, status=400)

    # 后缀校验
    fname = uploaded.name
    if not fname.lower().endswith(ALLOWED_EXT):
        return JsonResponse({"status": False, "data": {"error": "仅支持 .txt 后缀的文本文件"}}, status=400)

    # 大小校验
    if uploaded.size > MAX_UPLOAD_SIZE:
        return JsonResponse({"status": False, "data": {"error": f"文件大小不能超过 30MB"}}, status=400)

    # 重名加后缀
    safe_name = _resolve_unique_name(fname)
    dest = os.path.join(TARGET_DIR, safe_name)

    os.makedirs(TARGET_DIR, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in uploaded.chunks():
            f.write(chunk)

    return JsonResponse({
        "status": True,
        "data": {"file_name": safe_name, "original_name": fname if safe_name != fname else None}
    })


def target_file_download_api(request, filename):
    """GET /api/v1/target-files/<filename>/download"""
    safe = _safe_target_path(filename)
    if not safe or not os.path.isfile(safe):
        return JsonResponse({"status": False, "data": {"error": "文件不存在"}}, status=404)

    return FileResponse(
        open(safe, "rb"),
        as_attachment=True,
        filename=os.path.basename(safe),
        content_type="text/plain; charset=utf-8",
    )


@deny_user
def target_file_delete_api(request, filename):
    """DELETE /api/v1/target-files/<filename>"""
    safe = _safe_target_path(filename)
    if not safe or not os.path.isfile(safe):
        return JsonResponse({"status": False, "data": {"error": "文件不存在"}}, status=404)

    fname = os.path.basename(safe)
    refs = _find_referencing_tasks(fname)

    if request.method == "DELETE":
        # 有引用时返回引用信息，让前端确认
        if refs:
            return JsonResponse({
                "status": True,
                "data": {
                    "has_refs": True,
                    "refs": [{"model": m, "task_id": tid} for m, tid in refs],
                    "file_name": fname,
                }
            })
        # 无引用直接删
        os.remove(safe)
        return JsonResponse({"status": True, "data": {"deleted": fname}})

    return JsonResponse({"status": False, "data": {"error": "仅支持 DELETE 方法"}}, status=405)


@deny_user
def target_file_delete_confirm_api(request, filename):
    """POST /api/v1/target-files/<filename>/delete-confirm — 确认删除（含引用清理）"""
    safe = _safe_target_path(filename)
    if not safe or not os.path.isfile(safe):
        return JsonResponse({"status": False, "data": {"error": "文件不存在"}}, status=404)

    fname = os.path.basename(safe)
    _remove_filename_from_history_fields(fname)
    os.remove(safe)
    return JsonResponse({"status": True, "data": {"deleted": fname}})


@deny_user
def target_file_batch_delete_api(request):
    """POST /api/v1/target-files/batch-delete"""
    if request.method != "POST":
        return JsonResponse({"status": False, "data": {"error": "仅支持 POST 方法"}}, status=405)

    import json
    try:
        body = json.loads(request.body)
        filenames = body.get("filenames", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"status": False, "data": {"error": "请求格式错误"}}, status=400)

    results = []
    for fname in filenames:
        safe = _safe_target_path(fname)
        if not safe or not os.path.isfile(safe):
            results.append({"file_name": fname, "error": "文件不存在"})
            continue

        name = os.path.basename(safe)
        refs = _find_referencing_tasks(name)
        if refs:
            results.append({
                "file_name": name,
                "has_refs": True,
                "refs": [{"model": m, "task_id": tid} for m, tid in refs],
            })
        else:
            _remove_filename_from_history_fields(name)
            os.remove(safe)
            results.append({"file_name": name, "deleted": True})

    # 分离已删除和待确认的文件
    has_pending = any(r.get("has_refs") for r in results)
    return JsonResponse({
        "status": True,
        "data": {
            "results": results,
            "has_pending_refs": has_pending,
        }
    })


@deny_user
def target_file_batch_delete_confirm_api(request):
    """POST /api/v1/target-files/batch-delete-confirm — 确认批量删除（跳过引用检查）"""
    if request.method != "POST":
        return JsonResponse({"status": False, "data": {"error": "仅支持 POST 方法"}}, status=405)

    import json
    try:
        body = json.loads(request.body)
        filenames = body.get("filenames", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"status": False, "data": {"error": "请求格式错误"}}, status=400)

    deleted = []
    for fname in filenames:
        safe = _safe_target_path(fname)
        if not safe or not os.path.isfile(safe):
            continue
        name = os.path.basename(safe)
        _remove_filename_from_history_fields(name)
        os.remove(safe)
        deleted.append(name)

    return JsonResponse({"status": True, "data": {"deleted": deleted}})
