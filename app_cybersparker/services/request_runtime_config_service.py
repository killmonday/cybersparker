from app_cybersparker import models
from app_cybersparker.lib.request_runtime.conf import conf
from app_cybersparker.lib.request_runtime.patch import patch_all_once


def _build_proxy_from_setting(proxy):
    if not proxy:
        return {}
    scheme = _proxy_scheme(proxy.proxy_type)
    proxy_url = f"{scheme}://{proxy.proxy_address}:{proxy.proxy_port}"
    return {"http": proxy_url, "https": proxy_url}


def _proxy_scheme(proxy_type):
    """将 proxy_type 整数值映射为代理 URL 的 scheme。

    1 → http，4 → socks5。未知值回退为 http，避免 https:// 等 urllib3 无法处理的 scheme。
    """
    return {1: "http", 4: "socks5"}.get(proxy_type, "http")


def refresh_conf_from_db():
    latest_proxy = models.ProxySetting.objects.order_by("-id").first()
    # 已废弃，任务代理改用 thread-local（set_task_proxy / _get_task_proxy）
    conf.proxies = _build_proxy_from_setting(latest_proxy)
    return conf


def bootstrap_request_runtime():
    patch_all_once()
    refresh_conf_from_db()
    return conf
