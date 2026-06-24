import json
import os
import uuid
from pathlib import Path

from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from app_cybersparker import models
from app_cybersparker.permissions import deny_user

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / 'upload_files'
MAX_UPLOAD_SIZE = 200 * 1024 * 1024  # 200MB


def _safe_upload_path(filename):
    """防止路径穿越：确保最终路径在 UPLOAD_DIR 内"""
    resolved = (UPLOAD_DIR / filename).resolve()
    if not str(resolved).startswith(str(UPLOAD_DIR.resolve())):
        raise ValueError('非法文件名')
    return resolved


def hosted_file_list_api(request):
    files = models.HostedFile.objects.all().order_by('-created_at')
    result = [
        {
            'id': f.id,
            'original_name': f.original_name,
            'stored_name': f.stored_name,
            'file_size': f.file_size,
            'is_public': f.is_public,
            'note': f.note,
            'created_at': f.created_at.isoformat() if f.created_at else None,
        }
        for f in files
    ]
    return JsonResponse({'status': True, 'data': {'files': result}})


@deny_user
def hosted_file_upload_api(request):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'data': {'error': 'method not allowed'}}, status=405)

    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'status': False, 'data': {'error': '没有上传文件'}}, status=400)

    if uploaded.size > MAX_UPLOAD_SIZE:
        return JsonResponse({'status': False, 'data': {'error': '文件大小超过 200MB 上限'}}, status=400)

    # 安全文件名：使用 UUID 避免重名，保留原始扩展名
    ext = ''
    if '.' in uploaded.name:
        ext = '.' + uploaded.name.rsplit('.', 1)[-1]
    stored_name = uuid.uuid4().hex + ext
    disk_path = _safe_upload_path(stored_name)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with open(disk_path, 'wb') as f:
        for chunk in uploaded.chunks():
            f.write(chunk)

    is_public = request.POST.get('is_public', 'true').lower() == 'true'

    # 截断过长的原始文件名（保留后缀），避免 DB 超长和 URL 过长
    safe_original = uploaded.name
    if len(safe_original) > 256:
        if '.' in safe_original:
            base, ext = safe_original.rsplit('.', 1)
            safe_original = base[:256 - len(ext) - 1] + '.' + ext
        else:
            safe_original = safe_original[:256]

    record = models.HostedFile.objects.create(
        original_name=safe_original,
        stored_name=stored_name,
        file_size=uploaded.size,
        is_public=is_public,
    )

    return JsonResponse({
        'status': True,
        'data': {
            'id': record.id,
            'original_name': record.original_name,
            'stored_name': record.stored_name,
            'file_size': record.file_size,
            'is_public': record.is_public,
            'created_at': record.created_at.isoformat() if record.created_at else None,
        },
    })


@deny_user
def hosted_file_delete_api(request, file_id):
    try:
        record = models.HostedFile.objects.get(id=file_id)
    except models.HostedFile.DoesNotExist:
        return JsonResponse({'status': False, 'data': {'error': '文件不存在'}}, status=404)

    try:
        disk_path = _safe_upload_path(record.stored_name)
        if disk_path.exists():
            disk_path.unlink()
    except Exception:
        pass

    record.delete()
    return JsonResponse({'status': True, 'data': {'deleted': file_id}})


@deny_user
@require_http_methods(["PUT"])
def hosted_file_rename_api(request, file_id):
    try:
        record = models.HostedFile.objects.get(id=file_id)
    except models.HostedFile.DoesNotExist:
        return JsonResponse({'status': False, 'data': {'error': '文件不存在'}}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': False, 'data': {'error': '无效的 JSON'}}, status=400)

    new_name = body.get('new_name', '').strip()
    if not new_name:
        return JsonResponse({'status': False, 'data': {'error': 'new_name 不能为空'}}, status=400)

    # 路径穿越防护：拒绝路径分隔符、null 字节、以点开头
    if '/' in new_name or '\\' in new_name or '\x00' in new_name or new_name.startswith('.'):
        return JsonResponse({'status': False, 'data': {'error': '文件名包含非法字符'}}, status=400)

    # 生成带 UUID 前缀的安全新名，保留扩展名
    if '.' in new_name:
        base, ext = new_name.rsplit('.', 1)
        safe_new_name = f"{base}-{uuid.uuid4().hex[:8]}.{ext}"
    else:
        safe_new_name = f"{new_name}-{uuid.uuid4().hex[:8]}"

    old_path = _safe_upload_path(record.stored_name)
    new_path = _safe_upload_path(safe_new_name)

    if not old_path.exists():
        return JsonResponse({'status': False, 'data': {'error': '磁盘文件不存在'}}, status=404)

    os.rename(str(old_path), str(new_path))
    record.stored_name = safe_new_name
    record.save(update_fields=['stored_name', 'updated_at'])

    return JsonResponse({
        'status': True,
        'data': {
            'id': record.id,
            'original_name': record.original_name,
            'stored_name': record.stored_name,
        },
    })


@deny_user
def hosted_file_access_api(request, file_id):
    try:
        record = models.HostedFile.objects.get(id=file_id)
    except models.HostedFile.DoesNotExist:
        return JsonResponse({'status': False, 'data': {'error': '文件不存在'}}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': False, 'data': {'error': '无效的 JSON'}}, status=400)

    record.is_public = bool(body.get('is_public', True))
    record.save(update_fields=['is_public', 'updated_at'])

    return JsonResponse({
        'status': True,
        'data': {
            'id': record.id,
            'is_public': record.is_public,
        },
    })


@deny_user
@require_http_methods(["PUT"])
def hosted_file_note_api(request, file_id):
    try:
        record = models.HostedFile.objects.get(id=file_id)
    except models.HostedFile.DoesNotExist:
        return JsonResponse({'status': False, 'data': {'error': '文件不存在'}}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': False, 'data': {'error': '无效的 JSON'}}, status=400)

    record.note = body.get('note', '') or ''
    record.save(update_fields=['note', 'updated_at'])

    return JsonResponse({
        'status': True,
        'data': {'id': record.id, 'note': record.note},
    })


def hosted_file_download(request, file_id, filename):
    try:
        record = models.HostedFile.objects.get(id=file_id)
    except models.HostedFile.DoesNotExist:
        return HttpResponse('Not Found', status=404)

    # 防止 ID 枚举：URL 中的文件名必须与记录一致
    if filename != record.original_name:
        return HttpResponse('Not Found', status=404)

    # 鉴权检查：非公开文件需登录
    if not record.is_public:
        if not request.session.get('info'):
            return HttpResponse('Forbidden', status=403)

    try:
        disk_path = _safe_upload_path(record.stored_name)
    except ValueError:
        return HttpResponse('Not Found', status=404)

    if not disk_path.exists():
        return HttpResponse('Not Found', status=404)

    # 安全处置 Content-Disposition：剔除可能注入响应头的字符
    safe_name = record.original_name.replace('\r', '').replace('\n', '').replace('"', '')

    resp = FileResponse(open(disk_path, 'rb'), content_type='application/octet-stream')
    resp['Content-Disposition'] = f'attachment; filename="{safe_name}"'
    resp['Content-Length'] = str(record.file_size)
    return resp
