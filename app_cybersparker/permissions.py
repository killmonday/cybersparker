from functools import wraps
from django.http import JsonResponse


def get_role(request):
    try:
        info = request.session.get("info", {})
    except AttributeError:
        return ""
    return info.get("role", "") if isinstance(info, dict) else ""


def require_role(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if get_role(request) not in roles:
                return JsonResponse(
                    {"status": False, "message": "无操作权限"}, status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def deny_user(view_func):
    """阻止普通用户（super_admin + admin 放行）"""
    return require_role('super_admin', 'admin')(view_func)
