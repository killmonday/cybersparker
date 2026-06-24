from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.views.decorators.http import require_POST


def get_user_role(user):
    try:
        return user.profile.role
    except user.profile.RelatedObjectDoesNotExist:
        return 'user'


def login(request):
    next_url = request.GET.get('next', '') or request.POST.get('next', '')

    if request.method == "GET":
        if request.headers.get('Accept', '').startswith('application/json'):
            info = request.session.get("info")
            if info:
                return JsonResponse({"authenticated": True, "user": info})
            return JsonResponse({"authenticated": False, "login_url": "/login"})
        return render(request, 'project/login.html', {'next': next_url})

    # POST — 支持 JSON 和 form 两种格式
    if request.content_type == 'application/json':
        import json
        body = json.loads(request.body)
        username = body.get('username', '')
        password = body.get('password', '')
    else:
        username = request.POST.get("username", '')
        password = request.POST.get("password", '')

    if not password:
        if request.content_type == 'application/json':
            return JsonResponse({"status": False, "message": "username or password required"}, status=400)
        return render(request, 'project/login.html', {'error': "username or password error"})

    user = authenticate(request, username=username, password=password)
    if user and user.is_active:
        request.session["info"] = {
            "id": user.id,
            "username": user.username,
            "role": get_user_role(user),
        }
        auth_login(request, user)

        if request.content_type == 'application/json':
            return JsonResponse({"status": True, "next": next_url or '/react-shell/dashboard'})

        url = next_url or '/react-shell/dashboard'
        return redirect(url)

    if request.content_type == 'application/json':
        return JsonResponse({"status": False, "message": "username or password error"}, status=401)

    return render(request, 'project/login.html', {'error': "username or password error"})


@require_POST
def logout(request):
    auth_logout(request)
    request.session.flush()
    return redirect('/login')


def session_status(request):
    info = request.session.get("info")
    if not info:
        return JsonResponse(
            {
                "code": "UNAUTHENTICATED",
                "message": "login required",
                "login_url": "/login",
            },
            status=401,
        )
    return JsonResponse({"authenticated": True, "user": info})
