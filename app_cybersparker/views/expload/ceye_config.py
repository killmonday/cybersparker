from datetime import datetime
import os
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
import cybersparker.settings as sett
from app_cybersparker.permissions import deny_user


pwd = sett.THIS_DIR


def error_log(e_info, tips, time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = os.path.join(pwd, "..", "error_log", f"{now_time}_error-log.txt")
    try:
        with open(error_log_path, "a+") as f:
            f.write(f"[ceye_config {tips}] {time} : {e_info}\n")
    except Exception:
        pass


class CeyeConfigForm(BootStrapModelForm):
    class Meta:
        model = models.CeyeConfig
        fields = ["api_token", "identifier"]


def _get_ceye_config():
    return models.CeyeConfig.objects.first()


def list(request):
    config = _get_ceye_config()
    form = CeyeConfigForm(instance=config) if config else CeyeConfigForm()
    context = {
        "form": form,
        "config": config,
    }
    return render(request, "project/expload/ceye_config.html", context)


# ======================== JSON API ========================

import json


def ceye_config_api(request):
    from app_cybersparker.permissions import get_role
    if request.method in ('POST', 'PUT', 'DELETE'):
        if get_role(request) == 'user':
            return JsonResponse({"status": False, "message": "无操作权限"}, status=403)
    if request.method == "GET":
        config = _get_ceye_config()
        data = {"api_token": config.api_token, "identifier": config.identifier} if config else {"api_token": "", "identifier": ""}
        return JsonResponse({"status": True, "data": data, "legacy_list_url": "/ceye_config"})
    elif request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8"))
            config = _get_ceye_config()
            if config:
                form = CeyeConfigForm(body, instance=config)
            else:
                form = CeyeConfigForm(body)
            if form.is_valid():
                form.save()
                return JsonResponse({"status": True})
            return JsonResponse({"status": False, "errors": form.errors})
        except Exception as e:
            return JsonResponse({"status": False, "error": str(e)})
    return JsonResponse({"status": False, "error": "method not allowed"}, status=405)


@deny_user
def save(request):
    try:
        config = _get_ceye_config()
        if config:
            form = CeyeConfigForm(data=request.POST, instance=config)
        else:
            form = CeyeConfigForm(data=request.POST)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": True})
        return JsonResponse({"status": False, "error": form.errors})
    except Exception as e:
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "ceye_config save error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info, tips, time_str)
        return JsonResponse({"status": False, "tips": "ceye config save error"})
