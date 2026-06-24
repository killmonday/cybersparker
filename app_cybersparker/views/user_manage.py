import json

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from app_cybersparker.models import UserProfile


def get_current_role(request):
    return request.session.get("info", {}).get("role", "")


def get_current_user_id(request):
    return request.session.get("info", {}).get("id")


def invalidate_user_sessions(user_id):
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if data.get("info", {}).get("id") == user_id:
            session.delete()


# ——— 用户列表 ———
@require_http_methods(["GET"])
def user_list_api(request):
    role = get_current_role(request)
    if role not in ('super_admin', 'admin'):
        return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    qs = User.objects.filter(is_active=True).select_related('profile').order_by('-date_joined')

    if role == 'admin':
        qs = qs.filter(profile__role='user')

    users = []
    for u in qs:
        users.append({
            "id": u.id,
            "username": u.username,
            "role": u.profile.role,
            "is_active": u.is_active,
            "date_joined": u.date_joined.isoformat() if u.date_joined else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        })

    return JsonResponse({"status": True, "users": users})


# ——— 创建用户 ———
@require_http_methods(["POST"])
def user_create_api(request):
    current_role = get_current_role(request)
    if current_role not in ('super_admin', 'admin'):
        return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    body = json.loads(request.body)
    username = (body.get('username', '') or '').strip()
    password = body.get('password', '') or ''
    target_role = body.get('role', 'user')

    if not username:
        return JsonResponse({"status": False, "message": "用户名不能为空"}, status=400)
    if len(password) < 1:
        return JsonResponse({"status": False, "message": "密码不能为空"}, status=400)

    if User.objects.filter(username=username).exists():
        return JsonResponse({"status": False, "message": "用户名已存在"}, status=409)

    if current_role == 'admin':
        if target_role != 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)
    elif current_role == 'super_admin':
        if target_role not in ('admin', 'user'):
            return JsonResponse({"status": False, "message": "无效的角色"}, status=400)

    user = User.objects.create_user(username=username, password=password, is_active=True)
    UserProfile.objects.filter(user=user).update(role=target_role)

    return JsonResponse({
        "status": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": target_role,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
            "last_login": None,
        }
    }, status=201)


# ——— 删除用户 ———
@require_http_methods(["DELETE"])
def user_delete_api(request, user_id):
    current_role = get_current_role(request)
    current_uid = get_current_user_id(request)

    if current_role not in ('super_admin', 'admin'):
        return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    if int(user_id) == current_uid:
        return JsonResponse({"status": False, "message": "不能删除自己"}, status=400)

    try:
        target = User.objects.select_related('profile').get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"status": False, "message": "用户不存在"}, status=404)

    if current_role == 'admin':
        if target.profile.role != 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    target.delete()
    invalidate_user_sessions(int(user_id))

    return JsonResponse({"status": True, "message": "用户已删除"})


# ——— 修改角色 ———
@require_http_methods(["PUT"])
def user_role_api(request, user_id):
    current_role = get_current_role(request)
    if current_role != 'super_admin':
        return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    body = json.loads(request.body)
    new_role = body.get('role', '')

    if new_role not in ('super_admin', 'admin', 'user'):
        return JsonResponse({"status": False, "message": "无效的角色"}, status=400)

    try:
        target_user = User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        return JsonResponse({"status": False, "message": "用户不存在"}, status=404)

    UserProfile.objects.filter(user=target_user).update(role=new_role)
    invalidate_user_sessions(int(user_id))

    return JsonResponse({"status": True, "message": "角色已更新"})


# ——— 修改他人密码 ———
@require_http_methods(["PUT"])
def user_password_api(request, user_id):
    current_role = get_current_role(request)

    if current_role not in ('super_admin', 'admin'):
        return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    try:
        target = User.objects.select_related('profile').get(id=user_id, is_active=True)
    except User.DoesNotExist:
        return JsonResponse({"status": False, "message": "用户不存在"}, status=404)

    if current_role == 'admin':
        if target.profile.role != 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)

    body = json.loads(request.body)
    new_password = body.get('password', '') or ''
    if len(new_password) < 1:
        return JsonResponse({"status": False, "message": "密码不能为空"}, status=400)

    target.set_password(new_password)
    target.save()
    invalidate_user_sessions(int(user_id))

    return JsonResponse({"status": True, "message": "密码已重置"})


# ——— 修改自己密码 ———
@require_http_methods(["PUT"])
def user_me_password_api(request):
    current_uid = get_current_user_id(request)
    if not current_uid:
        return JsonResponse({"status": False, "message": "未登录"}, status=401)

    body = json.loads(request.body)
    new_password = body.get('password', '') or ''
    if len(new_password) < 1:
        return JsonResponse({"status": False, "message": "密码不能为空"}, status=400)

    try:
        user = User.objects.get(id=current_uid)
    except User.DoesNotExist:
        return JsonResponse({"status": False, "message": "用户不存在"}, status=404)

    user.set_password(new_password)
    user.save()
    invalidate_user_sessions(current_uid)

    return JsonResponse({"status": True, "message": "密码已修改，请重新登录"})
