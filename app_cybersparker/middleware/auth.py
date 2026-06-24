from django.http import JsonResponse
from django.shortcuts import redirect

REACT_SHELL_PREFIX = '/react-shell/'
SKIP_PATHS = {'/login', '/logout', '/api/v1/auth/session'}


class AuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        # React 壳页自己处理鉴权，中间件放行
        if path.startswith(REACT_SHELL_PREFIX):
            return self.get_response(request)

        # 免登录路径
        if path in SKIP_PATHS:
            return self.get_response(request)

        # 静态文件
        if path.startswith('/static/'):
            return self.get_response(request)

        # 文件托管公开下载入口，视图自己判断权限
        if path.startswith('/files/'):
            return self.get_response(request)

        info_dict = request.session.get("info")
        if info_dict:
            return self.get_response(request)

        if path.startswith('/api/v1/'):
            return JsonResponse(
                {
                    "code": "UNAUTHENTICATED",
                    "message": "login required",
                    "login_url": "/login",
                },
                status=401,
            )

        return redirect('/login')
