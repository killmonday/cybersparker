import threading
from collections.abc import Mapping

from app_cybersparker.lib.request_runtime.conf import conf
from app_cybersparker.lib.request_runtime.enums import HTTP_HEADER
from app_cybersparker.lib.request_runtime.utils import generate_random_user_agent, urlparse
from requests.models import Request
from requests.sessions import Session
from requests.sessions import merge_cookies
from requests.cookies import RequestsCookieJar
from requests.utils import get_encodings_from_content, to_key_val_list
from requests.compat import OrderedDict


def session_request(
    self,
    method,
    url,
    params=None,
    data=None,
    headers=None,
    cookies=None,
    files=None,
    auth=None,
    timeout=None,
    allow_redirects=True,
    proxies=None,
    hooks=None,
    stream=None,
    verify=None,
    cert=None,
    json=None,
):
    def _merge_retain_none(request_setting, session_setting, dict_class=OrderedDict):
        if session_setting is None:
            return request_setting
        if request_setting is None:
            return session_setting
        if not (
            isinstance(session_setting, Mapping) and isinstance(request_setting, Mapping)
        ):
            return request_setting
        merged_setting = dict_class(to_key_val_list(session_setting))
        merged_setting.update(to_key_val_list(request_setting))
        return merged_setting

    if conf.get("http_headers", {}) == {}:
        conf.http_headers = {}

    merged_cookies = merge_cookies(
        merge_cookies(RequestsCookieJar(), self.cookies),
        cookies or conf.get("cookie", None),
    )

    if (
        not conf.get("agent", "")
        and HTTP_HEADER.USER_AGENT not in conf.get("http_headers", {})
    ):
        conf.http_headers[HTTP_HEADER.USER_AGENT] = generate_random_user_agent()

    pr = urlparse(url)
    if str(pr.scheme).lower() not in ["http", "https"]:
        url = pr._replace(
            scheme="https" if str(pr.port).endswith("443") else "http"
        ).geturl()

    req = Request(
        method=method.upper(),
        url=url,
        headers=_merge_retain_none(headers, conf.get("http_headers", {})),
        files=files,
        data=data or {},
        json=json,
        params=params or {},
        auth=auth,
        cookies=merged_cookies,
        hooks=hooks,
    )
    prep = self.prepare_request(req)

    task_proxy = _get_task_proxy()
    if task_proxy is not None:
        proxies = dict(task_proxy)
    elif proxies is None:
        proxies = dict(conf.get("proxies", {}))
    if not proxies:
        proxies = {"http": None, "https": None}

    if verify is None:
        verify = conf.get("verify", False)

    settings = self.merge_environment_settings(prep.url, proxies, stream, verify, cert)

    timeout = timeout or conf.get("timeout", 10)
    if timeout:
        timeout = float(timeout)

    send_kwargs = {
        "timeout": timeout,
        "allow_redirects": allow_redirects,
    }
    send_kwargs.update(settings)
    resp = self.send(prep, **send_kwargs)

    if resp.encoding == "ISO-8859-1":
        encodings = get_encodings_from_content(resp.text)
        if encodings:
            encoding = encodings[0]
        else:
            encoding = resp.apparent_encoding
        resp.encoding = encoding

    return resp


_task_proxy = threading.local()


def set_task_proxy(proxies_dict):
    """任务执行器入口调用。proxies_dict={} 表示任务配置了不使用代理。"""
    _task_proxy.proxies = proxies_dict


def _get_task_proxy():
    """None = 未设置（非任务线程）；{} = 任务线程内配置了不使用代理。"""
    return getattr(_task_proxy, 'proxies', None)


def patch_session():
    Session.request = session_request
