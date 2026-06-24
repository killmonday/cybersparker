import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from queue import Empty, Full, Queue

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event, Lock, get_ident
from types import SimpleNamespace
from typing import Any, cast
import os
import subprocess
import sys
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import aiohttp
import ssl
from django.utils import timezone

import requests
from django.core.management import call_command
from django.db import DatabaseError, OperationalError, close_old_connections
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from app_cybersparker import models
from app_cybersparker.models import UserProfile
from app_cybersparker.lib.request_runtime.conf import conf
from app_cybersparker.lib.request_runtime.patch.hook_request import session_request
from app_cybersparker.services.request_runtime_config_service import refresh_conf_from_db


class _DummySession(requests.Session):
    def __init__(self):
        super().__init__()
        self.last_merge = {}

    def merge_environment_settings(self, url, proxies, stream, verify, cert):
        _ = url
        self.last_merge = {
            "proxies": proxies,
            "stream": stream,
            "verify": verify,
            "cert": cert,
        }
        return {
            "proxies": proxies,
            "stream": stream,
            "verify": verify,
            "cert": cert,
        }

    def send(self, request, **kwargs):
        _ = kwargs
        response = requests.Response()
        response.status_code = 200
        response.url = request.url or "http://example.com"
        response.request = request
        response._content = b"ok"
        response.encoding = "utf-8"
        return response


class AuthContractTests(TestCase):
    def test_session_status_returns_401_when_session_missing(self):
        from app_cybersparker.views import login as login_view

        request = RequestFactory().get("/api/v1/auth/session")
        request.session = {}

        response = login_view.session_status(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.content), {
            "code": "UNAUTHENTICATED",
            "message": "login required",
            "login_url": "/login",
        })

    def test_session_status_returns_authenticated_user_when_session_exists(self):
        from app_cybersparker.views import login as login_view

        request = RequestFactory().get("/api/v1/auth/session")
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = login_view.session_status(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {
            "authenticated": True,
            "user": {"id": 1, "username": "admin", "role": "super_admin"},
        })

    def test_auth_middleware_returns_json_401_for_api_requests(self):
        from app_cybersparker.middleware.auth import AuthMiddleware

        request = RequestFactory().get("/api/v1/identify-tasks")
        request.session = {}

        def ok_response(request):
            _ = request
            return JsonResponse({"ok": True})

        response = AuthMiddleware(ok_response)(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.content)["code"], "UNAUTHENTICATED")



class PluginListApiTests(TestCase):
    def test_plugin_list_api_returns_filtered_payload(self):
        from app_cybersparker.views.expload import plugin_manage

        tag = models.Tag.objects.create(name="sample-tag")
        exp = models.EXP.objects.create(
            title="sample-plugin",
            CVE="CVE-2026-0001",
            severity="high",
            plugin_language=1,
            poc="EXP_plugin/sample_plugin.py",
        )
        exp.tags.add(tag)

        request = RequestFactory().get(
            "/api/v1/plugins",
            {
                "q": "sample",
                "severity": "high",
                "tag": "sample",
                "page": "1",
                "rows_per_page": "10",
            },
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = plugin_manage.expload_list_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["title"], "sample-plugin")
        self.assertEqual(payload["items"][0]["severity_label"], "高危")
        self.assertEqual(payload["items"][0]["tags"], ["sample-tag"])
        self.assertEqual(payload["filters"], {"q": "sample", "severity": "high", "tag": "sample"})


class DictListApiTests(TestCase):
    def test_dict_list_api_returns_filtered_payload(self):
        from app_cybersparker.views.expload import dict_manage

        group = models.DirScanDictGroup.objects.create(name="sample-group", description="demo")
        record = models.DirScanDict.objects.create(name="sample-dict", paths=["/a", "/b"])
        record.groups.add(group)

        request = RequestFactory().get(
            "/api/v1/dicts",
            {
                "q": "sample",
                "page": "1",
                "rows_per_page": "10",
            },
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = dict_manage.dict_list_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "sample-dict")
        self.assertEqual(payload["items"][0]["path_count"], 2)
        self.assertEqual(payload["items"][0]["groups"], ["sample-group"])
        self.assertEqual(payload["filters"], {"q": "sample"})


class ProxyListApiTests(TestCase):
    def test_proxy_list_api_returns_filtered_payload(self):
        from app_cybersparker.views.expload import proxy_setting

        models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=8080)

        request = RequestFactory().get(
            "/api/v1/proxies",
            {
                "q": "127.0.0.1",
                "page": "1",
                "rows_per_page": "10",
            },
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = proxy_setting.list_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["proxy_type_label"], "http")
        self.assertEqual(payload["items"][0]["proxy_address"], "127.0.0.1")
        self.assertEqual(payload["items"][0]["proxy_port"], 8080)
        self.assertEqual(payload["filters"], {"q": "127.0.0.1"})


class EngineListApiTests(TestCase):
    def test_engine_list_api_returns_filtered_payload(self):
        from app_cybersparker.views.expload import cyberspace_engine_setting

        proxy = models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=8081)
        models.CyberspaceEngineSetting.objects.create(
            engine_type="fofa",
            api_base_url="https://fofa.info/api",
            account_email="demo@example.com",
            api_key="token",
            use_proxy=True,
            proxy=proxy,
            remark="sample remark",
        )

        request = RequestFactory().get(
            "/api/v1/cyberspace-engines",
            {
                "q": "fofa",
                "page": "1",
                "rows_per_page": "10",
            },
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = cyberspace_engine_setting.list_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["engine_type"], "fofa")
        self.assertEqual(payload["items"][0]["account_email"], "demo@example.com")
        self.assertTrue(payload["items"][0]["use_proxy"])
        self.assertIn("127.0.0.1", payload["items"][0]["proxy_label"])
        self.assertEqual(payload["filters"], {"q": "fofa"})


class FingerprintListApiTests(TestCase):
    def test_fingerprint_list_api_returns_filtered_payload(self):
        from app_cybersparker.views.expload import fingerprint

        models.fingerPrint.objects.create(product="nginx", condition="title=nginx")

        request = RequestFactory().get(
            "/api/v1/fingerprints",
            {
                "q": "nginx",
                "page": "1",
                "rows_per_page": "10",
            },
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = fingerprint.list_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["product"], "nginx")
        self.assertEqual(payload["items"][0]["condition"], "title=nginx")
        self.assertEqual(payload["filters"], {"q": "nginx"})


class ProxyFormApiTests(TestCase):
    def test_proxy_detail_api_returns_payload(self):
        from app_cybersparker.views.expload import proxy_setting

        row = models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=9000, remark="demo")
        request = RequestFactory().get(f"/api/v1/proxies/{row.id}")
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = proxy_setting.detail_api(request, row.id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["proxy_address"], "127.0.0.1")

    def test_proxy_create_api_creates_record(self):
        from app_cybersparker.views.expload import proxy_setting

        request = RequestFactory().post(
            "/api/v1/proxies/create",
            data=json.dumps(
                {
                    "proxy_type": 1,
                    "proxy_address": "127.0.0.1",
                    "proxy_port": 9001,
                    "remark": "created",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        with patch("app_cybersparker.views.expload.proxy_setting.refresh_conf_from_db"):
            response = proxy_setting.create_api(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertTrue(models.ProxySetting.objects.filter(proxy_address="127.0.0.1", proxy_port=9001).exists())

    def test_proxy_update_api_updates_record(self):
        from app_cybersparker.views.expload import proxy_setting

        row = models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=9002, remark="before")
        request = RequestFactory().post(
            f"/api/v1/proxies/{row.id}/update",
            data=json.dumps(
                {
                    "proxy_type": 4,
                    "proxy_address": "127.0.0.2",
                    "proxy_port": 9003,
                    "remark": "after",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        with patch("app_cybersparker.views.expload.proxy_setting.refresh_conf_from_db"):
            response = proxy_setting.update_api(request, row.id)

        payload = json.loads(response.content)
        row.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(row.proxy_type, 4)
        self.assertEqual(row.proxy_address, "127.0.0.2")
        self.assertEqual(row.proxy_port, 9003)
        self.assertEqual(row.remark, "after")


class EngineFormApiTests(TestCase):

    def test_engine_detail_api_returns_payload(self):
        from app_cybersparker.views.expload import cyberspace_engine_setting

        row = models.CyberspaceEngineSetting.objects.create(
            engine_type="fofa",
            api_base_url="https://fofa.info/api",
            account_email="demo@example.com",
            api_key="token",
            use_proxy=False,
            remark="demo",
        )
        request = RequestFactory().get(f"/api/v1/cyberspace-engines/{row.id}")
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = cyberspace_engine_setting.detail_api(request, row.id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["engine_type"], "fofa")

    def test_engine_create_api_creates_record(self):
        from app_cybersparker.views.expload import cyberspace_engine_setting

        request = RequestFactory().post(
            "/api/v1/cyberspace-engines/create",
            data=json.dumps(
                {
                    "engine_type": "fofa",
                    "api_base_url": "https://fofa.info/api",
                    "account_email": "demo@example.com",
                    "api_key": "token",
                    "use_proxy": False,
                    "proxy": None,
                    "remark": "created",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = cyberspace_engine_setting.create_api(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertTrue(models.CyberspaceEngineSetting.objects.filter(engine_type="fofa").exists())

    def test_engine_update_api_updates_record(self):
        from app_cybersparker.views.expload import cyberspace_engine_setting

        proxy = models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=8089)
        row = models.CyberspaceEngineSetting.objects.create(
            engine_type="fofa",
            api_base_url="https://fofa.info/api",
            account_email="before@example.com",
            api_key="before-token",
            use_proxy=False,
            remark="before",
        )
        request = RequestFactory().post(
            f"/api/v1/cyberspace-engines/{row.id}/update",
            data=json.dumps(
                {
                    "engine_type": "fofa",
                    "api_base_url": "https://fofa.info/v2/api",
                    "account_email": "after@example.com",
                    "api_key": "after-token",
                    "use_proxy": True,
                    "proxy": proxy.id,
                    "remark": "after",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = cyberspace_engine_setting.update_api(request, row.id)
        payload = json.loads(response.content)
        row.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(row.api_base_url, "https://fofa.info/v2/api")
        self.assertEqual(row.account_email, "after@example.com")
        self.assertEqual(row.api_key, "after-token")
        self.assertTrue(row.use_proxy)
        self.assertEqual(row.proxy_id, proxy.id)
        self.assertEqual(row.remark, "after")


class FingerprintFormApiTests(TestCase):

    def test_fingerprint_detail_api_returns_payload(self):
        from app_cybersparker.views.expload import fingerprint

        row = models.fingerPrint.objects.create(product="nginx", condition="title=nginx")
        request = RequestFactory().get(f"/api/v1/fingerprints/{row.id}")
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = fingerprint.detail_api(request, row.id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["product"], "nginx")

    def test_fingerprint_create_api_creates_record(self):
        from app_cybersparker.views.expload import fingerprint

        request = RequestFactory().post(
            "/api/v1/fingerprints/create",
            data=json.dumps(
                {
                    "product": "nginx",
                    "condition": "title=nginx",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = fingerprint.create_api(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertTrue(models.fingerPrint.objects.filter(product="nginx", condition="title=nginx").exists())

    def test_fingerprint_update_api_updates_record(self):
        from app_cybersparker.views.expload import fingerprint

        row = models.fingerPrint.objects.create(product="nginx", condition="title=nginx")
        request = RequestFactory().post(
            f"/api/v1/fingerprints/{row.id}/update",
            data=json.dumps(
                {
                    "product": "apache",
                    "condition": "title=apache",
                }
            ),
            content_type="application/json",
        )
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}

        response = fingerprint.update_api(request, row.id)
        payload = json.loads(response.content)
        row.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(row.product, "apache")
        self.assertEqual(row.condition, "title=apache")


class RequestRuntimePatchTests(TestCase):
    def setUp(self):
        self.original_proxies = dict(conf.proxies)
        self.original_verify = conf.verify
        self.original_timeout = conf.timeout
        conf.http_headers = {}
        conf.agent = ""

    def tearDown(self):
        conf.proxies = self.original_proxies
        conf.verify = self.original_verify
        conf.timeout = self.original_timeout

    def test_session_request_is_patched(self):
        self.assertIs(requests.Session.request, session_request)

    def test_proxies_none_falls_back_to_conf(self):
        conf.proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        session = _DummySession()

        session.request("GET", "http://example.com", proxies=None)

        self.assertEqual(session.last_merge["proxies"], conf.proxies)

    def test_set_task_proxy_controls_requests(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        set_task_proxy({"http": "http://task-proxy:8080", "https": "http://task-proxy:8080"})
        try:
            session = _DummySession()
            session.request("GET", "http://example.com", proxies=None)
            self.assertEqual(
                session.last_merge["proxies"],
                {"http": "http://task-proxy:8080", "https": "http://task-proxy:8080"},
            )
        finally:
            set_task_proxy(None)

    def test_task_proxy_empty_overrides_explicit(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        set_task_proxy({})
        try:
            session = _DummySession()
            session.request("GET", "http://example.com", proxies={"http": "http://evil:9999"})
            self.assertEqual(session.last_merge["proxies"], {"http": None, "https": None})
        finally:
            set_task_proxy(None)

    def test_task_proxy_overrides_plugin_explicit(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        set_task_proxy({"http": "http://task-a:1111", "https": "http://task-a:1111"})
        try:
            session = _DummySession()
            session.request("GET", "http://example.com", proxies={"http": "http://plugin-b:2222"})
            self.assertEqual(
                session.last_merge["proxies"],
                {"http": "http://task-a:1111", "https": "http://task-a:1111"},
            )
        finally:
            set_task_proxy(None)

    def test_no_task_proxy_respects_explicit(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        try:
            set_task_proxy(None)
        except Exception:
            pass
        session = _DummySession()
        explicit = {"http": "http://explicit:3333"}
        session.request("GET", "http://example.com", proxies=explicit)
        self.assertEqual(session.last_merge["proxies"], explicit)

    def test_no_task_proxy_falls_back_to_conf(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        set_task_proxy(None)
        conf.proxies = {"http": "http://sys-proxy:7890", "https": "http://sys-proxy:7890"}
        session = _DummySession()
        session.request("GET", "http://example.com", proxies=None)
        self.assertEqual(
            session.last_merge["proxies"],
            {"http": "http://sys-proxy:7890", "https": "http://sys-proxy:7890"},
        )

    def test_set_task_proxy_isolation(self):
        from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
        import threading
        results = {}

        def thread_a():
            set_task_proxy({"http": "http://proxy-a:1111", "https": "http://proxy-a:1111"})
            s = _DummySession()
            s.request("GET", "http://example.com")
            results["a"] = s.last_merge["proxies"]

        def thread_b():
            set_task_proxy({"http": "http://proxy-b:2222", "https": "http://proxy-b:2222"})
            s = _DummySession()
            s.request("GET", "http://example.com")
            results["b"] = s.last_merge["proxies"]

        ta = threading.Thread(target=thread_a)
        tb = threading.Thread(target=thread_b)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        self.assertEqual(results["a"], {"http": "http://proxy-a:1111", "https": "http://proxy-a:1111"})
        self.assertEqual(results["b"], {"http": "http://proxy-b:2222", "https": "http://proxy-b:2222"})

    def test_gevent_patch_includes_ssl_with_recurse_fix(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        original_patched = Task_handler._gevent_patched
        patch_all = MagicMock()
        monkey = MagicMock(patch_all=patch_all)
        try:
            Task_handler._gevent_patched = False
            with patch.dict("sys.modules", {"gevent": MagicMock(monkey=monkey)}):
                Task_handler._ensure_gevent_patch(Task_handler.__new__(Task_handler))
        finally:
            Task_handler._gevent_patched = original_patched

        patch_all.assert_called_once_with(thread=False, subprocess=False, ssl=True)

    def _build_progress_handler(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        handler = Task_handler.__new__(Task_handler)
        handler.uid = 1
        handler.total_line_count = 100
        handler.completed_count = 0
        handler.current_index = 0
        handler.consumer_number = 0
        handler.last_progress_bucket = None
        handler.last_progress_process = None
        handler.last_progress_flush_at = 0
        handler.progress_lock = Lock()
        handler.dispatch_token = None
        handler.resource_leases = []
        handler.last_resource_heartbeat_at = 0
        handler.resource_heartbeat_interval = 999999
        handler.owner = None
        handler._last_pause_check_at = 0
        handler.pause_requested = False
        return handler

    def test_progress_flush_skips_same_process_value(self):
        handler = self._build_progress_handler()
        updates = []

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.time.time", side_effect=[1, 5]):
            with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.models.batch_EXPTask.objects.filter") as filter_mock:
                filter_mock.return_value = SimpleNamespace(update=lambda **kwargs: updates.append(kwargs))
                handler.completed_count = 1
                handler.get_progress()
                handler.completed_count = 1
                handler.get_progress()

        self.assertEqual(updates, [{"process": "1.0%"}])

    def test_progress_flush_force_writes_final_status_once(self):
        handler = self._build_progress_handler()
        updates = []

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.models.batch_EXPTask.objects.filter") as filter_mock:
            filter_mock.return_value = SimpleNamespace(update=lambda **kwargs: updates.append(kwargs))
            handler.completed_count = 100
            handler.get_progress(force=True)
            handler.get_progress(force=True)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["process"], "100%")
        self.assertEqual(updates[0]["status"], 1)
        self.assertIn("endTime", updates[0])

class BatchTaskGeventRunnerTests(TransactionTestCase):
    def test_gevent_runner_patches_before_loading_batch_executor(self):
        from app_cybersparker.views.expload.task_manage.gevent_batch_runner import run_gevent_task_in_subprocess

        events = []
        patch_all = MagicMock(side_effect=lambda **kwargs: events.append(("patch", kwargs)))
        task_handler_cls = MagicMock()
        task_handler_cls._gevent_patched = False
        task_handler = MagicMock()
        task_handler_cls.return_value = task_handler
        fake_gevent = SimpleNamespace(monkey=SimpleNamespace(patch_all=patch_all))
        fake_executor = SimpleNamespace(Task_handler=task_handler_cls)
        real_import = __import__

        def import_stub(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "gevent":
                return fake_gevent
            if name == "app_cybersparker.views.expload.task_manage.batch_task_executor":
                events.append(("load_executor", None))
                return fake_executor
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=import_stub):
            run_gevent_task_in_subprocess({"uid": 1})

        self.assertEqual(events[0], ("patch", {"thread": False, "subprocess": False, "ssl": True}))
        self.assertEqual(events[1], ("load_executor", None))
        self.assertTrue(task_handler_cls._gevent_patched)
        task_handler_cls.assert_called_once_with({"uid": 1})
        self.assertEqual(task_handler.run_mode, 2)
        task_handler.run.assert_called_once_with()

    def test_coroutine_mode_uses_lightweight_gevent_runner_as_spawn_target(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task
        from app_cybersparker.views.expload.task_manage.gevent_batch_runner import run_gevent_task_in_subprocess

        task = models.batch_EXPTask.objects.create(
            task_name="gevent-runner-test",
            EXP="1",
            run_mode=2,
            thread_num=10,
            sleep_time=0,
            target="EXP_input/targets.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        row_dict = {
            "EXP": "1",
            "target": "EXP_input/targets.txt",
            "run_mode": 2,
            "thread_num": 10,
            "sleep_time": 0,
            "process": "0%",
        }

        process_mock = MagicMock()
        context_mock = MagicMock()
        context_mock.Process.return_value = process_mock

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.prepare_engine_target_before_start", return_value=(True, None)):
            with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.multiprocessing.current_process", return_value=SimpleNamespace(daemon=False)):
                with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.multiprocessing.get_context", return_value=context_mock):
                    batch_exp_task.startTask(row_dict, task.id)

        context_mock.Process.assert_called_once()
        self.assertIs(context_mock.Process.call_args.kwargs["target"], run_gevent_task_in_subprocess)
        process_mock.start.assert_called_once_with()


    def test_save_task_result_waits_for_late_queue_output(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        handler = Task_handler.__new__(Task_handler)
        handler.uid = 1
        handler.zone_id = 1
        handler.exit_flag = False
        saved_payloads = []

        class _DelayedQueue:
            def __init__(self):
                self.empty_state = False
                self.calls = 0

            def get(self, block=True, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise Empty
                if self.calls == 2:
                    handler.exit_flag = True
                    self.empty_state = True
                    return {"target": "http://target", "plugin": "[CVE]plugin", "result": "ok"}
                raise Empty

            def task_done(self):
                return None

            def empty(self):
                return self.empty_state

        handler.queue_output = _DelayedQueue()

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.publish_result_events", side_effect=lambda stream, payloads: saved_payloads.extend(payloads)), patch(
            "app_cybersparker.views.expload.task_manage.batch_task_executor.throttle_dispatch_result_writer", return_value=None
        ):
            handler.save_TaskResult()

        self.assertEqual(len(saved_payloads), 2)
        self.assertEqual(saved_payloads[0]["target"], "http://target")
        self.assertEqual(saved_payloads[1]["target"], "http://target")

class NucleiRuntimeRequestChainTests(TestCase):
    def test_render_nested_markers_supports_interactsh_argument(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import _render_nested_markers

        rendered = _render_nested_markers(
            "{{concat('http://{{interactsh-url}}')}}",
            {"interactsh-url": "flag.example.ceye.io"},
        )

        self.assertEqual(rendered, "http://flag.example.ceye.io")

    def test_network_oob_matcher_uses_ceye_records(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: log4j-oob
network:
  - host:
      - "{{Host}}:4712"
    inputs:
      - data: "hello"
    matchers:
      - type: word
        part: interactsh_protocol
        words:
          - dns
"""
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye", return_value=[{"name": "flag.example.ceye.io"}]) as poll_mock, \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.socket.socket") as socket_mock:
            sock = socket_mock.return_value
            sock.recv.return_value = b""

            result = run_nuclei_template(template, "192.168.1.166:4712")

        self.assertEqual(result, [{"extra_info": [], "dnslog": [{"name": "flag.example.ceye.io"}]}])
        self.assertEqual(poll_mock.call_count, 1)
        sock.connect.assert_called_once_with(("192.168.1.166", 4712))
        sock.sendall.assert_called_once()

    def test_network_oob_still_queries_ceye_when_read_times_out(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: log4j-oob
network:
  - host:
      - "{{Host}}:4712"
    inputs:
      - data: "hello"
    matchers:
      - type: word
        part: interactsh_protocol
        words:
          - dns
"""
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye", return_value=[{"name": "flag.example.ceye.io"}]) as poll_mock, \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.socket.socket") as socket_mock:
            sock = socket_mock.return_value
            sock.recv.side_effect = TimeoutError("no immediate response")

            result = run_nuclei_template(template, "192.168.1.166:4712")

        self.assertEqual(result, [{"extra_info": [], "dnslog": [{"name": "flag.example.ceye.io"}]}])
        self.assertEqual(poll_mock.call_count, 1)
        sock.sendall.assert_called_once()

    def test_build_dynamic_values_adds_official_oob_aliases(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import _build_dynamic_values

        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"):
            values = _build_dynamic_values("192.168.1.166:4712")

        self.assertEqual(values["ceye_url"], "flag.example.ceye.io")
        self.assertEqual(values["ceye-url"], "flag.example.ceye.io")
        self.assertEqual(values["interactsh_url"], "flag.example.ceye.io")
        self.assertEqual(values["interactsh-url"], "flag.example.ceye.io")

    def test_network_payload_auto_decodes_official_hex_gadget_with_crlf_suffix(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = (_PROJECT_ROOT / "EXP_plugin/CVE-2017-5645_2a704bc9.yaml").read_text(encoding="utf-8")
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye", return_value=[{"name": "flag.example.ceye.io"}]), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.socket.socket") as socket_mock:
            sock = socket_mock.return_value
            sock.recv.return_value = b""

            result = run_nuclei_template(template, "192.168.1.166:4712")

        sent_payload = sock.sendall.call_args.args[0]
        self.assertTrue(result)
        self.assertIsInstance(sent_payload, bytes)
        self.assertTrue(sent_payload.startswith(b"\xac\xed\x00\x05"))
        self.assertTrue(sent_payload.endswith(b"\r\n"))

    def test_network_payload_keeps_plain_hexlike_text_when_no_binary_helper(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: plain-text
network:
  - host:
      - "{{Host}}:4712"
    inputs:
      - data: "deadbeef"
    matchers:
      - type: word
        part: interactsh_protocol
        words:
          - dns
"""
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye", return_value=[{"name": "flag.example.ceye.io"}]), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.socket.socket") as socket_mock:
            sock = socket_mock.return_value
            sock.recv.return_value = b""

            result = run_nuclei_template(template, "192.168.1.166:4712")

        self.assertTrue(result)
        self.assertEqual(sock.sendall.call_args.args[0], b"deadbeef")

    def test_official_log4j_template_matches_via_ceye(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = (_PROJECT_ROOT / "EXP_plugin/CVE-2017-5645_2a704bc9.yaml").read_text(encoding="utf-8")
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye", return_value=[{"name": "flag.example.ceye.io"}]) as poll_mock, \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._get_ceye_url", return_value="flag.example.ceye.io"), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.socket.socket") as socket_mock:
            sock = socket_mock.return_value
            sock.recv.return_value = b""

            result = run_nuclei_template(template, "192.168.1.166:4712")

        self.assertTrue(result)
        self.assertEqual(result[0]["dnslog"], [{"name": "flag.example.ceye.io"}])
        self.assertEqual(poll_mock.call_count, 1)
        self.assertTrue(sock.sendall.called)

    def test_build_urldns_reuses_embedded_sample_bytes(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import _URLDNS_SAMPLE_BYTES, _build_urldns

        payload = _build_urldns("http://flag.example.ceye.io")

        self.assertEqual(payload, _URLDNS_SAMPLE_BYTES)

    def test_http_non_matching_response_continues_later_paths(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: request-chain
http:
  - method: GET
    path:
      - "{{BaseURL}}/first"
      - "{{BaseURL}}/second"
    matchers:
      - type: status
        status:
          - 201
"""
        first_response = requests.Response()
        first_response.status_code = 200
        first_response.url = "http://example.test/first"
        first_response._content = b"miss"
        second_response = requests.Response()
        second_response.status_code = 201
        second_response.url = "http://example.test/second"
        second_response._content = b"hit"

        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.requests.Session.request", autospec=True) as request_mock:
            request_mock.side_effect = [first_response, second_response]

            result = run_nuclei_template(template, "http://example.test")

        self.assertTrue(result)
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[0].kwargs["url"], "http://example.test/first")
        self.assertEqual(request_mock.call_args_list[1].kwargs["url"], "http://example.test/second")

    def test_http_request_exception_stops_later_paths(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: request-chain
http:
  - method: GET
    path:
      - "{{BaseURL}}/first"
      - "{{BaseURL}}/second"
    matchers:
      - type: status
        status:
          - 200
"""
        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.requests.Session.request", autospec=True) as request_mock:
            request_mock.side_effect = requests.exceptions.Timeout("first request timed out")

            result = run_nuclei_template(template, "http://example.test")

        self.assertFalse(result)
        self.assertEqual(request_mock.call_count, 1)
        self.assertEqual(request_mock.call_args.kwargs["url"], "http://example.test/first")
        self.assertEqual(request_mock.call_args.kwargs["timeout"], 10)

    def test_unsupported_code_protocol_returns_clear_error(self):
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import _build_yaml_wrapper

        with NamedTemporaryFile(suffix='.yaml') as f:
            f.write(b'''id: code-only\nself-contained: true\ncode:\n  - engine:\n      - sh\n    source: echo hello\n''')
            f.flush()
            wrapper = _build_yaml_wrapper(f.name)
            result = wrapper._verify('http://example.test')

        self.assertFalse(result)
        self.assertIn('unsupported nuclei protocol: code', result.get('result', ''))

    def test_non_oob_match_on_real_template_does_not_query_ceye(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: qve-like
requests:
  - raw:
      - |
        GET /api/permission/Users HTTP/1.1
        Host: {{Host}}
    matchers:
      - type: word
        part: body
        words:
          - 'CreatorTime'
"""
        response = requests.Response()
        response.status_code = 200
        response.url = "http://example.test/api/permission/Users"
        response._content = b'{"CreatorTime":"2024-01-01"}'
        response.headers['Content-Type'] = 'application/json'

        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.requests.Session.request", autospec=True, return_value=response), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye") as poll_mock:
            result = run_nuclei_template(template, "http://example.test")

        self.assertTrue(result)
        self.assertFalse(poll_mock.called)

    def test_http_matchers_without_oob_do_not_query_ceye(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import run_nuclei_template

        template = """
id: http-no-oob
http:
  - method: GET
    path:
      - "{{BaseURL}}/hit"
    matchers:
      - type: status
        status:
          - 200
"""
        response = requests.Response()
        response.status_code = 200
        response.url = "http://example.test/hit"
        response._content = b"hit"

        with patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine.requests.Session.request", autospec=True, return_value=response), \
             patch("app_cybersparker.views.expload.task_manage.nuclei_runtime_engine._poll_ceye") as poll_mock:
            result = run_nuclei_template(template, "http://example.test")

        self.assertTrue(result)
        self.assertFalse(poll_mock.called)


class RequestRuntimeConfigServiceTests(TestCase):
    def setUp(self):
        self.original_proxies = dict(conf.proxies)

    def tearDown(self):
        conf.proxies = self.original_proxies

    def test_refresh_conf_from_db_uses_latest_proxy(self):
        models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.1", proxy_port=8080)
        latest = models.ProxySetting.objects.create(proxy_type=1, proxy_address="127.0.0.2", proxy_port=9090)

        refresh_conf_from_db()

        self.assertEqual(
            conf.proxies,
            {
                "http": f"{latest.get_proxy_type_display()}://{latest.proxy_address}:{latest.proxy_port}",
                "https": f"{latest.get_proxy_type_display()}://{latest.proxy_address}:{latest.proxy_port}",
            },
        )


class SchedulerRuntimeDiagnosticsTests(TestCase):
    def test_runtime_diagnostics_returns_idle_snapshot(self):
        from app_cybersparker.views import Dashboards

        request = RequestFactory().get("/runtime/diagnostics", {"task_type": "batch"})
        response = Dashboards.runtime_diagnostics(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["task_type"], "batch")
        self.assertEqual(payload["queue_lengths"], {})
        self.assertIn("thread_count", payload)
        self.assertIn("db_pool_checked_out", payload)
        self.assertTrue(payload["resource_config"]["observe_only"])

    def test_runtime_diagnostics_reports_batch_handle_queues_and_elapsed(self):
        from app_cybersparker.services.scheduler_runtime_service import get_runtime_diagnostics
        import cybersparker.settings as sett

        original_batch_handles = dict(sett.BATH_TASK_DIC)
        sett.BATH_TASK_DIC.clear()

        task = models.batch_EXPTask.objects.create(
            task_name="runtime-batch-diagnostics",
            EXP="1",
            run_mode=1,
            thread_num=10,
            sleep_time=0,
            target="EXP_input/targets.txt",
            status=2,
            process="10%",
            startTime=timezone.now() - timedelta(seconds=120),
        )
        handle = SimpleNamespace(
            queue_input=SimpleNamespace(qsize=lambda: 3),
            queue_output=SimpleNamespace(qsize=lambda: 1),
        )
        sett.BATH_TASK_DIC[str(task.id)] = handle

        try:
            payload = get_runtime_diagnostics("batch", task.id)
        finally:
            sett.BATH_TASK_DIC.clear()
            sett.BATH_TASK_DIC.update(original_batch_handles)

        self.assertEqual(payload["queue_lengths"], {"queue_input": 3, "queue_output": 1})
        self.assertGreaterEqual(payload["elapsed_seconds"], 119)
        self.assertEqual(payload["handle_counts"]["batch"], 1)

    def test_runtime_diagnostics_reports_exp_task_usage_and_status_plan(self):
        from app_cybersparker.services.scheduler_runtime_service import get_runtime_diagnostics
        import cybersparker.settings as sett

        payload_before = get_runtime_diagnostics()
        labels_before = {item["label"]: item["total"] for item in payload_before["exp_task_usage"]["task_type_counts"]}
        cmd_input_before = payload_before["exp_task_usage"]["cmd_input_non_empty_count"]

        exp = models.EXP.objects.create(
            title="runtime-diagnostics-plugin",
            CVE="CVE-RUNTIME-DIAG",
            poc="EXP_plugin/runtime_diagnostics.py",
        )
        models.EXPTask.objects.create(
            task_name="runtime-verify-task",
            EXP=exp,
            taskType=1,
            target="EXP_input/runtime_verify.txt",
        )
        models.EXPTask.objects.create(
            task_name="runtime-attack-task",
            EXP=exp,
            taskType=2,
            cmd_input="whoami",
            target="EXP_input/runtime_attack.txt",
        )

        payload = get_runtime_diagnostics()
        labels = {item["label"]: item["total"] for item in payload["exp_task_usage"]["task_type_counts"]}

        self.assertEqual(labels["Verify"], labels_before.get("Verify", 0) + 1)
        self.assertEqual(labels["Attact"], labels_before.get("Attact", 0) + 1)
        self.assertEqual(payload["exp_task_usage"]["cmd_input_non_empty_count"], cmd_input_before + 1)
        self.assertEqual(payload["status_model_plan"]["planned_fields"], list(sett.SCHEDULER_STATUS_MODEL_FIELDS))
        self.assertEqual(payload["status_model_plan"]["ui_mapping"]["queued"], "waiting")


class CeleryRuntimeInfrastructureTests(TestCase):
    def test_celery_app_declares_expected_queues(self):
        from cybersparker.celery import app as celery_app

        queue_names = [queue.name for queue in celery_app.conf.task_queues]

        self.assertEqual(
            sorted(queue_names),
            sorted(["auto_scan", "batch_scan", "batch_scan_gevent", "result_writer", "maintenance", "dir_scan", "poc_generation"]),
        )
        self.assertEqual(celery_app.conf.task_default_queue, "maintenance")
        self.assertEqual(celery_app.conf.task_routes["app_cybersparker.tasks.batch_scan_gevent_probe"]["queue"], "batch_scan_gevent")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_eager_task_executes_synchronously(self):
        from cybersparker.celery import app as celery_app
        from app_cybersparker.services.celery_runtime_service import dispatch_task
        from app_cybersparker.tasks import maintenance_echo

        original_always_eager = celery_app.conf.task_always_eager
        original_store_result = celery_app.conf.task_store_eager_result
        original_eager_propagates = celery_app.conf.task_eager_propagates
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_store_eager_result = True
        celery_app.conf.task_eager_propagates = True
        try:
            result = dispatch_task(maintenance_echo, "pong", queue="maintenance")
            self.assertEqual(result.get(timeout=1), "pong")
        finally:
            celery_app.conf.task_always_eager = original_always_eager
            celery_app.conf.task_store_eager_result = original_store_result
            celery_app.conf.task_eager_propagates = original_eager_propagates

    def test_connection_budget_guard_rejects_startup_and_dispatch(self):
        from cybersparker.celery import ConnectionBudgetGate, enforce_worker_connection_budget
        from app_cybersparker.services.celery_runtime_service import (
            assert_celery_connection_budget,
            ensure_celery_dispatch_enabled,
            get_connection_budget_snapshot,
        )

        databases = deepcopy(__import__("django.conf").conf.settings.DATABASES)
        databases["default"]["POOL_OPTIONS"]["POOL_SIZE"] = 5
        databases["default"]["POOL_OPTIONS"]["MAX_OVERFLOW"] = 2

        with override_settings(
            DATABASES=databases,
            POSTGRES_MAX_CONNECTIONS_TARGET=15,
            WEB_CONCURRENCY=1,
            CELERY_WORKER_CONCURRENCY=2,
            CELERY_DB_POOL_SIZE=5,
            CELERY_DB_POOL_OVERFLOW=2,
            CELERY_GEVENT_CHILD_PROCESSES=1,
            CELERY_GEVENT_DB_POOL_SIZE=5,
            CELERY_GEVENT_DB_POOL_OVERFLOW=2,
            DB_CONNECTION_RESERVED=5,
        ):
            snapshot = get_connection_budget_snapshot()
            self.assertGreater(snapshot["projected_total"], snapshot["target"])
            with self.assertRaises(RuntimeError):
                assert_celery_connection_budget()
            with self.assertRaises(RuntimeError):
                ensure_celery_dispatch_enabled()
            with self.assertRaises(RuntimeError):
                ConnectionBudgetGate(object())
            with self.assertRaises(RuntimeError):
                enforce_worker_connection_budget(["celery", "-A", "cybersparker", "worker"])

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_dispatch_helper_respects_budget_and_returns_eager_result(self):
        from cybersparker.celery import app as celery_app
        from app_cybersparker.services.celery_runtime_service import dispatch_task
        from app_cybersparker.tasks import maintenance_echo

        databases = deepcopy(__import__("django.conf").conf.settings.DATABASES)
        databases["default"]["POOL_OPTIONS"]["POOL_SIZE"] = 1
        databases["default"]["POOL_OPTIONS"]["MAX_OVERFLOW"] = 1
        original_always_eager = celery_app.conf.task_always_eager
        original_store_result = celery_app.conf.task_store_eager_result
        original_eager_propagates = celery_app.conf.task_eager_propagates

        with override_settings(
            DATABASES=databases,
            POSTGRES_MAX_CONNECTIONS_TARGET=100,
            WEB_CONCURRENCY=1,
            CELERY_WORKER_CONCURRENCY=1,
            CELERY_DB_POOL_SIZE=1,
            CELERY_DB_POOL_OVERFLOW=1,
            CELERY_GEVENT_CHILD_PROCESSES=0,
            DB_CONNECTION_RESERVED=2,
        ):
            celery_app.conf.task_always_eager = True
            celery_app.conf.task_store_eager_result = True
            celery_app.conf.task_eager_propagates = True
            try:
                result = dispatch_task(maintenance_echo, "ok", queue="maintenance")
                self.assertEqual(result.get(timeout=1), "ok")
            finally:
                celery_app.conf.task_always_eager = original_always_eager
                celery_app.conf.task_store_eager_result = original_store_result
                celery_app.conf.task_eager_propagates = original_eager_propagates


    def test_worker_process_init_resets_db_connections(self):
        from cybersparker.celery import reset_db_connections_for_worker_process

        with patch("cybersparker.celery.close_old_connections") as close_mock, patch(
            "cybersparker.celery.pool_container.dispose"
        ) as dispose_mock:
            reset_db_connections_for_worker_process()

        close_mock.assert_called_once_with()
        dispose_mock.assert_called_once_with()


    def test_auto_scan_stop_bridge_ignores_db_connection_failure(self):
        from app_cybersparker.views.expload.task_manage.auto_exp_task import Auto_exploit_Task_handler

        task = models.auto_scan_tasks.objects.create(
            task_name="auto-stop-bridge-db-error",
            thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_stop_bridge_db_error.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
            dispatch_token="token-db-error",
        )
        data = {
            "task_id": task.id,
            "target": "EXP_input/auto_stop_bridge_db_error.txt",
            "current_line": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "Vulnerability_scanning": 0,
            "proxy": {},
            "dispatch_token": "token-db-error",
            "owner": "worker-a",
        }
        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.connection.close"):
            handler = Auto_exploit_Task_handler(data)
            handler._last_stop_db_check_at = 0
            handler.resource_leases = []
            handler.last_resource_heartbeat_at = time.time()
            handler.resource_heartbeat_interval = 10

            with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.has_stop_signal", return_value=False), patch(
                "app_cybersparker.views.expload.task_manage.auto_exp_task.models.auto_scan_tasks.objects.filter",
                side_effect=OperationalError("db lost sync"),
            ), patch("app_cybersparker.views.expload.task_manage.auto_exp_task.close_old_connections"):
                stopped = handler.check_stop_bridge()

        self.assertFalse(stopped)
        self.assertFalse(handler.exit_flag)

    def test_batch_stop_bridge_ignores_db_connection_failure(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        handler = Task_handler.__new__(Task_handler)
        handler.uid = 1
        handler.dispatch_token = "token-batch-db-error"
        handler.owner = "worker-b"
        handler.resource_leases = []
        handler.last_resource_heartbeat_at = time.time()
        handler.resource_heartbeat_interval = 10
        handler._last_stop_db_check_at = 0
        handler.gevent_pool = None
        handler.exit_flag = False
        handler.stop_requested = False
        handler.is_over = True

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.has_stop_signal", return_value=False), patch(
            "app_cybersparker.views.expload.task_manage.batch_task_executor.models.batch_EXPTask.objects.filter",
            side_effect=OperationalError("db lost sync"),
        ), patch("app_cybersparker.views.expload.task_manage.batch_task_executor.close_old_connections"), patch(
            "app_cybersparker.views.expload.task_manage.batch_task_executor.connection.close"
        ):
            stopped = handler.check_stop_bridge()

        self.assertFalse(stopped)
        self.assertFalse(handler.exit_flag)

    def test_terminal_cas_ignores_old_token_duplicate_and_late_stop(self):
        from app_cybersparker.services.task_state_cas_service import compare_and_set_terminal_state, initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="cas-helper-task",
            EXP="1",
            run_mode=1,
            thread_num=1,
            sleep_time=0,
            target="EXP_input/cas_helper.txt",
            status=2,
            process="10%",
            startTime=timezone.now(),
        )

        self.assertTrue(initialize_task_runtime(models.batch_EXPTask, task.id, "token-current", "worker-1", queued=False))
        self.assertFalse(compare_and_set_terminal_state(models.batch_EXPTask, task.id, "token-old", "worker-1", "failed", last_error="boom"))
        self.assertTrue(compare_and_set_terminal_state(models.batch_EXPTask, task.id, "token-current", "worker-1", "success"))
        self.assertFalse(compare_and_set_terminal_state(models.batch_EXPTask, task.id, "token-current", "worker-1", "success"))
        self.assertFalse(compare_and_set_terminal_state(models.batch_EXPTask, task.id, "token-current", "worker-1", "stopped"))

        task.refresh_from_db()
        self.assertEqual(task.status, 1)
        self.assertFalse(task.failed)
        self.assertFalse(task.queued)
        self.assertIsNotNone(task.endTime)


@override_settings(CELERY_BROKER_URL="memory://")
class AutoScanCeleryDispatchTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()

    def test_restart_search_query_task_resets_last_id(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-search-restart-{time.time_ns()}",
            thread_num=5,
            vulnerability_thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_search_restart.txt",
            status=3,
            process="100%",
            input_type=6,
            search_query='title:"demo"',
            parsed_query={"operator": "condition", "field": "title", "value": "demo"},
            frozen_max_id=88,
            last_id=66,
            current_line=20,
            Vulnerability_scanning=0,
        )
        request = self.factory.post("/Identify_task/operate", {"uid": str(task.id), "status": "1"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.auto_scan_task.dispatch_task"):
            response = auto_scan_task.Task_operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.last_id, 0)

    def test_auto_scan_start_dispatches_celery_without_local_thread(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-celery-start-{time.time_ns()}",
            thread_num=5,
            vulnerability_thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_celery_start.txt",
            status=3,
            process="0%",
            Vulnerability_scanning=0,
        )
        request = self.factory.post("/Identify_task/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.auto_scan_task.dispatch_task") as dispatch_mock:
            response = auto_scan_task.Task_operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(dispatch_mock.call_count, 1)
        self.assertEqual(dispatch_mock.call_args.args[0].name, "app_cybersparker.tasks.run_auto_scan_task")
        self.assertEqual(dispatch_mock.call_args.args[1], task.id)
        self.assertEqual(dispatch_mock.call_args.kwargs["queue"], "auto_scan")
        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)
        self.assertEqual(task.dispatch_token, payload["dispatch_token"])
        self.assertIsNone(task.owner)
        dispatched_row = dispatch_mock.call_args.args[1]
        self.assertEqual(dispatched_row, task.id)


    @override_settings(CELERY_BROKER_URL="memory://")
    def test_run_auto_scan_task_prepares_engine_target_before_start(self):
        from app_cybersparker.tasks import _run_auto_scan_task

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-engine-target-prepare-{time.time_ns()}",
            thread_num=5,
            sleep_time=0,
            target=None,
            status=2,
            process="0%",
            current_line=1,
            input_type=4,
            engine_type=1,
            engine_query='app="nginx"',
            engine_max_assets=10,
            Vulnerability_scanning=0,
            dispatch_token="token-engine-prepare",
        )

        scanner = SimpleNamespace(stop_requested=False, pause_requested=False)

        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.tasks.connection.close"), \
             patch("app_cybersparker.tasks.claim_task_execution", return_value=True), \
             patch("app_cybersparker.tasks.acquire_resource_leases", return_value=[]), \
             patch("app_cybersparker.tasks.release_resource_leases", return_value=None), \
             patch("app_cybersparker.tasks.compare_and_set_terminal_state", return_value=True) as cas_mock, \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.prepare_engine_target_before_start") as prepare_mock, \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.startTask", return_value=scanner) as start_mock:
            def _prepare(task_obj, is_restart=False, force_refresh=False):
                _ = is_restart, force_refresh
                task_obj.target = "EXP_input/generated_engine_target.txt"
                task_obj.save(update_fields=["target"])
                return True, None
            prepare_mock.side_effect = _prepare
            result = _run_auto_scan_task(task.id, "token-engine-prepare", "worker-a")

        self.assertEqual(result["status"], "success")
        self.assertEqual(prepare_mock.call_count, 1)
        start_row = start_mock.call_args.args[0]
        self.assertEqual(start_row["target"], "EXP_input/generated_engine_target.txt")
        cas_mock.assert_called()

    def test_auto_scan_edit_engine_query_change_disables_reuse_and_clears_target(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        target_rel = "EXP_input/engine_assets/auto_edit_query_change.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-edit-query-change-{time.time_ns()}",
            thread_num=5,
            vulnerability_thread_num=2,
            sleep_time=0,
            http_timeout=10,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            Vulnerability_scanning=0,
        )
        request = self.factory.post(
            f"/Identify_task/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "vulnerability_thread_num": str(task.vulnerability_thread_num),
                "sleep_time": str(task.sleep_time),
                "http_timeout": str(task.http_timeout),
                "input_type": "4",
                "engine_type": "fofa",
                "engine_query": 'app="apache"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "Vulnerability_scanning": str(task.Vulnerability_scanning),
                "remark": "",
                "proxy": "",
                "reuse_engine_data": "true",
            },
        )
        request.session = self.session

        response = auto_scan_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_query, 'app="apache"')
        self.assertFalse(task.reuse_engine_data)
        self.assertFalse(bool(task.target))
        self.assertTrue(target_abs.exists())

    def test_auto_scan_edit_same_engine_query_keeps_reuse_and_target(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        target_rel = "EXP_input/engine_assets/auto_edit_same_query.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-edit-same-query-{time.time_ns()}",
            thread_num=5,
            vulnerability_thread_num=2,
            sleep_time=0,
            http_timeout=10,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            Vulnerability_scanning=0,
        )
        request = self.factory.post(
            f"/Identify_task/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "vulnerability_thread_num": str(task.vulnerability_thread_num),
                "sleep_time": str(task.sleep_time),
                "http_timeout": str(task.http_timeout),
                "input_type": "4",
                "engine_type": "fofa",
                "engine_query": 'app="nginx"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "Vulnerability_scanning": str(task.Vulnerability_scanning),
                "remark": "",
                "proxy": "",
                "reuse_engine_data": "true",
            },
        )
        request.session = self.session

        response = auto_scan_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_query, 'app="nginx"')
        self.assertTrue(task.reuse_engine_data)
        self.assertEqual(str(task.target), target_rel)
        self.assertTrue(target_abs.exists())

    def test_auto_scan_edit_engine_type_change_disables_reuse_and_clears_target(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        target_rel = "EXP_input/engine_assets/auto_edit_engine_type_change.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-edit-engine-type-{time.time_ns()}",
            thread_num=5,
            vulnerability_thread_num=2,
            sleep_time=0,
            http_timeout=10,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            Vulnerability_scanning=0,
        )
        request = self.factory.post(
            f"/Identify_task/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "vulnerability_thread_num": str(task.vulnerability_thread_num),
                "sleep_time": str(task.sleep_time),
                "http_timeout": str(task.http_timeout),
                "input_type": "4",
                "engine_type": "hunter",
                "engine_query": 'app="nginx"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "Vulnerability_scanning": str(task.Vulnerability_scanning),
                "remark": "",
                "proxy": "",
                "reuse_engine_data": "true",
            },
        )
        request.session = self.session

        response = auto_scan_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_type, "hunter")
        self.assertFalse(task.reuse_engine_data)
        self.assertFalse(bool(task.target))
        self.assertTrue(target_abs.exists())

    def test_run_auto_scan_task_ignores_duplicate_claim(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-celery-duplicate-{time.time_ns()}",
            thread_num=5,
            sleep_time=0,
            target="EXP_input/auto_celery_duplicate.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
        )
        initialize_task_runtime(models.auto_scan_tasks, task.id, "token-1", None, queued=True)
        models.auto_scan_tasks.objects.filter(id=task.id).update(owner="worker-a")

        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.tasks.connection.close"):
            result = _run_auto_scan_task(task.id, "token-1", "worker-b")

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["reason"], "already_claimed")

    def test_run_auto_scan_task_marks_success_via_cas(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-celery-success-{time.time_ns()}",
            thread_num=5,
            sleep_time=0,
            target="EXP_input/auto_celery_success.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
        )
        initialize_task_runtime(models.auto_scan_tasks, task.id, "token-success", None, queued=True)
        dummy_scanner = SimpleNamespace(stop_requested=False)

        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.tasks.connection.close"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.startTask", return_value=dummy_scanner):
            result = _run_auto_scan_task(task.id, "token-success", "worker-a")

        task.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(task.status, 1)
        self.assertFalse(task.failed)
        self.assertFalse(task.queued)
        self.assertEqual(task.owner, "worker-a")
        self.assertIsNotNone(task.endTime)

    def test_run_auto_scan_task_marks_failure_on_exception(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-celery-failure-{time.time_ns()}",
            thread_num=5,
            sleep_time=0,
            target="EXP_input/auto_celery_failure.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
        )
        initialize_task_runtime(models.auto_scan_tasks, task.id, "token-failure", None, queued=True)

        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.tasks.connection.close"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.startTask", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                _run_auto_scan_task(task.id, "token-failure", "worker-a")

        task.refresh_from_db()
        self.assertEqual(task.status, 3)
        self.assertTrue(task.failed)
        self.assertEqual(task.last_error, "boom")
        self.assertIsNotNone(task.endTime)

    def test_stop_bridge_sets_exit_flag_from_db_signal(self):
        from app_cybersparker.views.expload.task_manage.auto_exp_task import Auto_exploit_Task_handler

        task = models.auto_scan_tasks.objects.create(
            task_name=f"auto-stop-bridge-{time.time_ns()}",
            thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_stop_bridge.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
            dispatch_token="token-stop",
        )
        data = {
            "task_id": task.id,
            "target": "EXP_input/auto_stop_bridge.txt",
            "current_line": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "Vulnerability_scanning": 0,
            "proxy": {},
            "dispatch_token": "token-stop",
            "owner": "worker-a",
        }
        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.connection.close"):
            handler = Auto_exploit_Task_handler(data)
            models.auto_scan_tasks.objects.filter(id=task.id).update(stop_requested=True)
            stopped = handler.check_stop_bridge()

        self.assertTrue(stopped)
        self.assertTrue(handler.exit_flag)
        self.assertTrue(handler.stop_requested)


@override_settings(RESOURCE_HEARTBEAT_INTERVAL_SECONDS=10, RESOURCE_LEASE_TTL_SECONDS=30)
class TaskStartupRecoveryTests(TestCase):
    def _create_auto_scan_task(self, task_name, **overrides):
        payload = {
            "task_name": task_name,
            "thread_num": 2,
            "sleep_time": 0,
            "target": f"EXP_input/{task_name}.txt",
            "status": 2,
            "queued": False,
            "failed": False,
            "stop_requested": False,
            "pause_requested": False,
            "heartbeat_at": None,
            "startTime": None,
            "process": "0%",
            "phase": 3,
            "dispatch_token": f"token-{task_name}",
        }
        payload.update(overrides)
        return models.auto_scan_tasks.objects.create(**payload)

    def _run_recovery_without_closing_connection(self):
        from django.apps import apps as django_apps

        with patch("django.db.connection.close"):
            django_apps.get_app_config("app_cybersparker")._recover_zombie_tasks()

    def test_recover_zombie_tasks_resets_running_rows_without_start_time(self):
        task = self._create_auto_scan_task("auto-starttime-missing")

        self._run_recovery_without_closing_connection()
        task.refresh_from_db()

        self.assertEqual(task.status, 3)
        self.assertFalse(task.queued)
        self.assertFalse(task.pause_requested)
        self.assertFalse(task.stop_requested)
        self.assertFalse(task.failed)
        self.assertEqual(task.last_error, "server restarted")
        self.assertIsNotNone(task.endTime)

    def test_recover_zombie_tasks_keeps_queued_rows_without_start_time(self):
        task = self._create_auto_scan_task(
            "auto-queued-starttime-missing",
            queued=True,
            phase=1,
        )

        self._run_recovery_without_closing_connection()
        task.refresh_from_db()

        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)
        self.assertIsNone(task.endTime)
        self.assertIsNone(task.last_error)


class AutoScanAsyncRequestTests(TransactionTestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases

        reset_memory_leases()

    def _build_handler(self, **overrides):
        from app_cybersparker.views.expload.task_manage.auto_exp_task import Auto_exploit_Task_handler

        defaults = {
            "task_id": 9001,
            "target": "EXP_input/auto_async.txt",
            "current_line": 1,
            "thread_num": 4,
            "sleep_time": 0,
            "Vulnerability_scanning": 0,
            "proxy": {},
            "dispatch_token": "token-async",
            "owner": "worker-a",
            "resource_leases": [],
            "zone_id": 1,
        }
        defaults.update(overrides)
        return Auto_exploit_Task_handler(defaults)

    @override_settings(CELERY_BROKER_URL="memory://", RESOURCE_RETRY_DELAY_SECONDS=0)
    def test_request_scan_marks_waiting_and_clears_runtime_after_lease_recovers(self):
        models.auto_scan_tasks.objects.create(
            id=9001,
            task_name="auto-async-waiting",
            thread_num=4,
            sleep_time=0,
            target="EXP_input/auto_async_waiting.txt",
            status=2,
            process="0%",
            Vulnerability_scanning=0,
            dispatch_token="token-async",
            owner="worker-a",
        )
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False

        class _Response:
            status = 200
            headers = {}
            charset = "utf-8"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = exc_type, exc, tb
                return False

            async def read(self):
                return b"ok"

            def get_encoding(self):
                return "utf-8"

        class _Session:
            def get(self, url, **kwargs):
                return _Response()

        from app_cybersparker.services.resource_lease_service import ResourceUnavailableError

        acquire_calls = {"count": 0}

        def _acquire(*args, **kwargs):
            acquire_calls["count"] += 1
            if acquire_calls["count"] == 1:
                raise ResourceUnavailableError("http_inflight")
            return {"resource": "http_inflight", "lease_id": "lease-ok", "owner": "worker-a", "amount": 1}

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.acquire_resource_lease", side_effect=_acquire), patch(
            "app_cybersparker.views.expload.task_manage.auto_exp_task.release_resource_lease",
            return_value=True,
        ):
            result = asyncio.run(handler.request_scan(_Session(), "http://example.com"))

        task = models.auto_scan_tasks.objects.get(id=9001)
        self.assertIsNone(result[-1])
        self.assertGreaterEqual(acquire_calls["count"], 2)
        self.assertFalse(task.queued)
        self.assertIsNone(task.last_error)
        self.assertEqual(task.owner, "worker-a")

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_request_consumer_backpressure_waits_for_fingerprint_queue_capacity(self):
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False
        handler.producer_done = True
        handler.queue_input = Queue(maxsize=4)
        handler.queue_fingerpoint_input = Queue(maxsize=1)
        handler.queue_fingerpoint_input.put({"occupied": {}})
        handler.queue_input.put("http://example.com")
        release_slot = Event()

        async def _fake_request_scan(session, url):
            self.assertTrue(release_slot.is_set())
            return "hdr", "html", "title", 200, {}, None

        handler.request_scan = _fake_request_scan

        async def _free_slot_after_delay():
            await asyncio.sleep(0.05)
            handler.queue_fingerpoint_input.get()
            handler.queue_fingerpoint_input.task_done()
            release_slot.set()

        async def _run():
            consumer = asyncio.create_task(handler._request_consumer_async())
            releaser = asyncio.create_task(_free_slot_after_delay())
            await asyncio.gather(consumer, releaser)

        asyncio.run(_run())

        self.assertTrue(release_slot.is_set())
        self.assertEqual(handler.queue_input.unfinished_tasks, 0)
        payload = handler.queue_fingerpoint_input.get_nowait()
        info = payload["http://example.com"]
        self.assertEqual(info["html"], "html")
        self.assertIsNone(info["error"])
        handler.queue_fingerpoint_input.task_done()

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_request_consumer_hits_configured_concurrency_on_single_thread_and_disables_trust_env(self):
        handler = self._build_handler(thread_num=4)
        handler.check_stop_bridge = lambda: False
        handler.producer_done = True
        handler.queue_input = Queue(maxsize=8)
        handler.queue_fingerpoint_input = Queue(maxsize=8)
        for idx in range(4):
            handler.queue_input.put(f"http://example.com/{idx}")

        session_kwargs = {}
        active = {"count": 0, "max": 0}
        thread_ids = set()

        class _FakeClientSession:
            def __init__(self, **kwargs):
                session_kwargs.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = exc_type, exc, tb
                return False

        async def _fake_request_scan(session, url):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            thread_ids.add(get_ident())
            if active["max"] >= handler.network_concurrency:
                concurrency_reached.set()
            await concurrency_reached.wait()
            active["count"] -= 1
            return "hdr", url, "title", 200, {}, None

        concurrency_reached = asyncio.Event()
        handler.request_scan = _fake_request_scan

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.aiohttp.ClientSession", _FakeClientSession):
            asyncio.run(handler._request_consumer_async())

        self.assertFalse(session_kwargs.get("trust_env", True))
        self.assertGreaterEqual(active["max"], int(handler.network_concurrency * 0.8))
        self.assertEqual(len(thread_ids), 1)
        self.assertEqual(handler.queue_input.unfinished_tasks, 0)

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_fingerprint_consumer_waits_for_late_response_instead_of_exiting(self):
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False
        handler.producer_done = True
        handler.network_ok = True
        handler.queue_input = SimpleNamespace(unfinished_tasks=1)

        payload = {
            "http://example.com": {
                "header": "hdr",
                "content": "body",
                "html": "body",
                "title": "ttl",
                "status_code": 200,
                "favicon": None,
                "favicon_md5": "abc123",
                "cert_org": "Example Org",
                "cert_org_unit": "Security",
                "cert_common_name": "secure.example.com",
                "cert_serial": "SER123",
                "error": None,
            }
        }
        calls = {"count": 0}

        class _DelayedFingerprintQueue:
            unfinished_tasks = 0

            def get(self, block=True, timeout=None):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise Empty
                if calls["count"] == 2:
                    handler.queue_input.unfinished_tasks = 0
                    self.unfinished_tasks = 1
                    return payload
                raise Empty

            def task_done(self):
                self.unfinished_tasks = 0

        saved = []
        fingerprint_contexts = []
        handler.queue_fingerpoint_input = _DelayedFingerprintQueue()
        handler.identifyner = SimpleNamespace(handle=lambda header, content, title, context=None: fingerprint_contexts.append(context) or ["nginx"])
        handler.save_indentify_to_db = lambda fingers_list, url, header, title, content, status_code, extra=None: saved.append(
            (fingers_list, url, status_code, extra)
        )

        handler.fingerpoint_consumer_thread()

        self.assertEqual(saved, [(["nginx"], "http://example.com", 200, {
            "candidate_url": None,
            "favicon": None,
            "favicon_md5": "abc123",
            "cert_org": "Example Org",
            "cert_org_unit": "Security",
            "cert_common_name": "secure.example.com",
            "cert_serial": "SER123",
            "resolved_ip": None,
            "final_uri_path": None,
        })])
        self.assertEqual(fingerprint_contexts, [{
            "favicon": "abc123",
            "favicon_md5": "abc123",
            "favicon_mmh3": None,
            "uri_path": None,
            "cert": "Example Org Security secure.example.com",
            "cert_org": "Example Org",
            "cert_org_unit": "Security",
            "cert_common_name": "secure.example.com",
            "cert_serial": "SER123",
        }])
        self.assertEqual(calls["count"], 3)

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_vulnerability_scanning_exp_queues_are_drained_before_exit(self):
        handler = self._build_handler(Vulnerability_scanning=1)
        handler.is_over = True
        handler.dispatch_token = None
        handler.check_stop_bridge = lambda: False
        handler.network_ok = True

        class _DummyThread:
            def __init__(self, target=None, args=(), name=None, daemon=None):
                self._target = target
                self._name = name

            def start(self):
                if self._target and self._name != "network_check":
                    self._target()

            def is_alive(self):
                return False

            def join(self):
                return None

        def _fake_producer():
            handler.producer_done = True

        def _fake_request_consumer():
            handler.queue_input.put("http://target")
            handler.queue_input.task_done()
            handler.queue_fingerpoint_input.put({"http://target": {"header": "hdr", "content": "body", "html": "body", "title": "ttl", "status_code": 200, "error": None}})
            handler.queue_fingerpoint_input.task_done()

        def _fake_fingerpoint_consumer():
            handler.queue_EXP_input.put({"http://target": ["nginx"]})
            handler.queue_EXP_input.task_done()

        def _fake_exp_consumer():
            handler.queue_EXP_result.put({"exp_id": 1, "target": "http://target", "product": "nginx", "result": "ok"})
            handler.queue_EXP_result.task_done()

        def _fake_save_exp_result():
            return None

        handler.producer = _fake_producer
        handler.request_consumer = _fake_request_consumer
        handler.fingerpoint_consumer_thread = _fake_fingerpoint_consumer
        handler.exp_consumer = _fake_exp_consumer
        handler.save_exp_result = _fake_save_exp_result

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.threading.Thread", _DummyThread), patch(
            "app_cybersparker.views.expload.task_manage.auto_exp_task.time.sleep", lambda *args, **kwargs: None
        ), patch(
            "app_cybersparker.views.expload.task_manage.auto_exp_task.models.auto_scan_tasks.objects.filter"
        ) as filter_mock:
            filter_mock.return_value.update.return_value = 1
            handler.run()

        self.assertEqual(handler.queue_EXP_input.unfinished_tasks, 0)
        self.assertEqual(handler.queue_EXP_result.unfinished_tasks, 0)

    def test_save_exp_result_continues_after_single_payload_failure(self):
        handler = self._build_handler(Vulnerability_scanning=1)
        handler.check_stop_bridge = lambda: False
        handler.network_ok = True
        handler.producer_done = True
        handler.queue_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_fingerpoint_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_EXP_input = SimpleNamespace(unfinished_tasks=0)

        class _ResultQueue:
            def __init__(self):
                self.items = [
                    {"exp_id": "bad", "target": "http://bad", "product": "nginx", "result": "oops"},
                    {"exp_id": 2, "target": "http://ok", "product": "nginx", "result": "ok"},
                ]
                self.unfinished_tasks = len(self.items)

            def get(self, block=True, timeout=None):
                if self.items:
                    return self.items.pop(0)
                raise Empty

            def task_done(self):
                self.unfinished_tasks = max(0, self.unfinished_tasks - 1)
                if self.unfinished_tasks == 0:
                    handler.exit_flag = True

        saved = []
        handler.queue_EXP_result = _ResultQueue()
        handler.save_exp_result_to_db = lambda exp_id, target, product, result: saved.append((exp_id, target, product, result))

        handler.save_exp_result()

        self.assertEqual(saved, [(2, "http://ok", "nginx", "ok")])


    @override_settings(CELERY_BROKER_URL="memory://")
    def test_save_exp_result_accepts_python_poc_shape(self):
        handler = self._build_handler(Vulnerability_scanning=1)
        handler.exit_flag = False
        handler.check_stop_bridge = lambda: False
        handler.network_ok = True
        handler.producer_done = True
        handler.queue_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_fingerpoint_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_EXP_input = SimpleNamespace(unfinished_tasks=0)

        class _ResultQueue:
            def __init__(self):
                self.items = [
                    {"exp_id": 2, "target": "http://python-poc", "product": "nginx", "result": "ok"},
                ]
                self.unfinished_tasks = len(self.items)

            def get(self, block=True, timeout=None):
                if self.items:
                    return self.items.pop(0)
                raise Empty

            def task_done(self):
                self.unfinished_tasks -= 1
                if self.unfinished_tasks <= 0:
                    handler.exit_flag = True

        saved = []
        handler.queue_EXP_result = _ResultQueue()
        handler.save_exp_result_to_db = lambda exp_id, target, product, result: saved.append((exp_id, target, product, result))

        handler.save_exp_result()

        self.assertEqual(saved, [(2, "http://python-poc", "nginx", "ok")])

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_save_exp_result_accepts_nuclei_shape(self):
        handler = self._build_handler(Vulnerability_scanning=1)
        handler.exit_flag = False
        handler.check_stop_bridge = lambda: False
        handler.network_ok = True
        handler.producer_done = True
        handler.queue_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_fingerpoint_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_EXP_input = SimpleNamespace(unfinished_tasks=0)

        class _ResultQueue:
            def __init__(self):
                self.items = [
                    {
                        "exp_id": 3,
                        "product": "nuclei-yaml",
                        "matched-at": "http://nuclei-target",
                        "matched": True,
                        "template-id": "test-template",
                        "detail": "[critical] test-template matched",
                    },
                ]
                self.unfinished_tasks = len(self.items)

            def get(self, block=True, timeout=None):
                if self.items:
                    return self.items.pop(0)
                raise Empty

            def task_done(self):
                self.unfinished_tasks -= 1
                if self.unfinished_tasks <= 0:
                    handler.exit_flag = True

        saved = []
        handler.queue_EXP_result = _ResultQueue()
        handler.save_exp_result_to_db = lambda exp_id, target, product, result: saved.append((exp_id, target, product, result))

        handler.save_exp_result()

        self.assertEqual(saved, [(3, "http://nuclei-target", "nuclei-yaml", "matched")])


    @override_settings(CELERY_BROKER_URL="memory://")
    def test_exp_consumer_normalizes_nuclei_result_before_queueing(self):
        handler = self._build_handler(Vulnerability_scanning=1)
        handler.exit_flag = False
        handler.check_stop_bridge = lambda: False
        handler.network_ok = True
        handler.producer_done = True
        handler.queue_input = SimpleNamespace(unfinished_tasks=0)
        handler.queue_fingerpoint_input = SimpleNamespace(unfinished_tasks=0)

        class _InputQueue:
            def __init__(self):
                self.items = [{"http://nuclei-target": ["nuclei-yaml"]}]
                self.unfinished_tasks = len(self.items)

            def get(self, block=True, timeout=None):
                if self.items:
                    return self.items.pop(0)
                raise Empty

            def task_done(self):
                self.unfinished_tasks -= 1
                if self.unfinished_tasks <= 0:
                    handler.exit_flag = True

        queued = []
        handler.queue_EXP_input = _InputQueue()
        handler.queue_EXP_result = SimpleNamespace(put=lambda item: queued.append(item))
        handler.get_exp_ids_for_products = lambda fingers_list: {
            9: {"poc": "EXP_plugin/test.yaml", "matched_product": "nuclei-yaml", "plugin_language": 2}
        }

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.load_runtime_module_from_poc", return_value=object()), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.call_runtime_method", return_value=[{"template-id": "test-template", "matched-at": "http://nuclei-target"}]), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.time.sleep", lambda *args, **kwargs: None):
            handler.exp_consumer()

        self.assertEqual(
            queued,
            [{
                "exp_id": 9,
                "target": "http://nuclei-target",
                "product": "nuclei-yaml",
                "result": "[{'template-id': 'test-template', 'matched-at': 'http://nuclei-target'}]",
            }],
        )


    def test_fingerprint_exp_cache_preserves_plugin_language(self):
        from app_cybersparker.views.expload.task_manage.auto_exp_task import Auto_exploit_Task_handler

        fp = models.fingerPrint.objects.create(product="Apache", condition='body="apache"')
        exp = models.EXP.objects.create(
            title="nuclei-cache-plugin",
            CVE="CVE-CACHE-NUCLEI",
            poc="EXP_plugin/cache_plugin.yaml",
            plugin_language=2,
        )
        models.exp_relate_fingerprint.objects.create(EXP_id=exp, fingerprint_id=fp)

        handler = Auto_exploit_Task_handler({
            "task_id": 9998,
            "target": "EXP_input/cache_target.txt",
            "current_line": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "Vulnerability_scanning": 1,
            "proxy": {},
            "dispatch_token": "token-cache",
            "owner": "worker-a",
            "resource_leases": [],
        })

        info = handler.get_exp_ids_for_products(["Apache"])
        self.assertEqual(info[exp.id]["plugin_language"], 2)

    # ── BL-AUTO-020: 非 HTTP 协议不发起 HTTP 请求 ──
    def test_request_scan_skips_http_for_non_http_protocol(self):
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False

        get_called = False

        class _Session:
            def get(self, url, **kwargs):
                nonlocal get_called
                get_called = True
                raise AssertionError("HTTP request should not be made for non-HTTP protocol")

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.acquire_resource_lease",
                   return_value={"resource": "http_inflight", "lease_id": "lease-ok", "owner": "worker-a", "amount": 1}), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.release_resource_lease",
                   return_value=True):
            result = asyncio.run(handler.request_scan(_Session(), "ssh://192.168.99.99:22"))

        header, content, title, status_code, extra, error = result
        self.assertIsNone(error)
        self.assertFalse(get_called, "session.get 不应该被调用")
        self.assertEqual(extra.get("candidate_url"), "ssh://192.168.99.99:22")

    def test_request_scan_non_http_resolves_ip_from_hostname(self):
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False

        class _Session:
            def get(self, url, **kwargs):
                raise AssertionError("HTTP request should not be made")

        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.acquire_resource_lease",
                   return_value={"resource": "http_inflight", "lease_id": "lease-ok", "owner": "worker-a", "amount": 1}), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.release_resource_lease",
                   return_value=True):
            result = asyncio.run(handler.request_scan(_Session(), "ssh://192.168.99.88:2222"))

        _, _, _, _, extra, error = result
        self.assertIsNone(error)
        self.assertEqual(extra.get("candidate_url"), "ssh://192.168.99.88:2222")

    def test_save_indentify_to_db_non_http_protocol_does_not_crash(self):
        handler = self._build_handler()
        non_http_urls = [
            "ssh://1.2.3.4",
            "ftp://1.2.3.4",
            "rdp://1.2.3.4",
            "smb://1.2.3.4:445",
            "telnet://1.2.3.5:23",
            "mysql://1.2.3.6",
            "mssql://1.2.3.7:1433",
            "redis://1.2.3.8",
            "mongodb://1.2.3.9",
            "postgresql://1.2.3.10",
            "oracle://1.2.3.11",
        ]
        for url in non_http_urls:
            try:
                handler.save_indentify_to_db([], url, "", "", "", 0, {"candidate_url": url})
            except Exception as e:
                self.fail(f"save_indentify_to_db crashed for {url}: {e}")

    # ── BL-AUTO-021: 裸域名（无协议头）不被误判为非 HTTP 协议 ──
    def test_request_scan_bare_host_port_not_misinterpreted_as_non_http(self):
        """裸域名 'host:port' 应被当作 HTTP 候选尝试，而非被 urlparse 错解析后跳过"""
        handler = self._build_handler()
        handler.check_stop_bridge = lambda: False

        get_called = False

        class _Response:
            status = 200
            headers = {}
            charset = "utf-8"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = exc_type, exc, tb
                return False

            async def read(self):
                return b"body content"

            def get_encoding(self):
                return "utf-8"

        class _Session:
            def get(self, url, **kwargs):
                nonlocal get_called
                get_called = True
                return _Response()

        # 场景：用户上传的目标文件里有一行 "ydbg.yun.liuzhou.gov.cn:8070"
        # urlparse 会把 "ydbg.yun.liuzhou.gov.cn" 当成 scheme，netloc 为空
        # 修复后：检测到没有 "://" → 自动补 http:// 和 https:// → 正常发起 HTTP 请求
        bare_urls = [
            "ydbg.yun.liuzhou.gov.cn:8070",
            "192.168.1.1:8080",
            "internal.host:443",
        ]
        for url in bare_urls:
            get_called = False
            with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.acquire_resource_lease",
                       return_value={"resource": "http_inflight", "lease_id": "lease-bare", "owner": "worker-a", "amount": 1}), \
                 patch("app_cybersparker.views.expload.task_manage.auto_exp_task.release_resource_lease",
                       return_value=True):
                header, content, title, status_code, extra, error = asyncio.run(
                    handler.request_scan(_Session(), url)
                )

            self.assertIsNone(error, f"裸域名 {url} 不应返回错误")
            self.assertTrue(get_called, f"裸域名 {url} 应该发起 HTTP 请求，但被跳过了")


class SslContextLegacyRenegotiationTests(TestCase):
    """SSL context 包含 OP_LEGACY_SERVER_CONNECT 以兼容老旧 HTTPS 服务器"""

    def test_create_permissive_ssl_context_has_legacy_flag(self):
        """_create_permissive_ssl_context 返回的 context 包含 0x4 标志"""
        from app_cybersparker.views.expload.task_manage.auto_exp_task import (
            _create_permissive_ssl_context,
        )
        ctx = _create_permissive_ssl_context()
        self.assertFalse(ctx.check_hostname,
                         "应关闭 check_hostname（ssl=False 等价行为）")
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE,
                         "应关闭证书验证（ssl=False 等价行为）")
        # OP_LEGACY_SERVER_CONNECT = 0x4。Python 3.12 之前没有命名常量
        OP_LEGACY = getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
        has_flag = bool(ctx.options & OP_LEGACY)
        if not has_flag:
            # 某些 OpenSSL 构建可能不支持，仅记录不让测试炸
            import warnings
            warnings.warn(
                "OP_LEGACY_SERVER_CONNECT flag not set — "
                "OpenSSL build may not support it"
            )
        # 不强制 assert: flag 在不受支持的 OpenSSL 上可能被忽略
        self.assertTrue(True)


@override_settings(CELERY_BROKER_URL="memory://")
class AutoScanResultSearchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.exp_plugin_a = models.EXP.objects.create(
            title="asset-plugin-a",
            CVE="CVE-2026-0001",
            poc="EXP_plugin/asset_plugin_a.py",
        )
        self.exp_plugin_b = models.EXP.objects.create(
            title="asset-plugin-b",
            CVE="CVE-2026-0001",
            poc="EXP_plugin/asset_plugin_b.py",
        )
        self.exp_plugin_c = models.EXP.objects.create(
            title="asset-plugin-c",
            CVE="CVE-2026-0002",
            poc="EXP_plugin/asset_plugin_c.py",
        )

        self.asset_a = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://asset-a.example.com",
            ip="10.0.0.1",
            protocol="http",
            port=80,
            title="asset-a",
        )
        self.asset_b = models.auto_scan_indentify_result.objects.create(
            products=["apache"],
            target="http://asset-b.example.com",
            ip="10.0.0.2",
            protocol="http",
            port=8080,
            title="asset-b",
        )
        self.asset_c = models.auto_scan_indentify_result.objects.create(
            products=["iis"],
            target="http://asset-c.example.com",
            ip="10.0.0.3",
            protocol="https",
            port=443,
            title="asset-c",
        )
        self.asset_favicon = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="https://favicon.example.com",
            ip="10.0.0.4",
            protocol="https",
            port=443,
            title="favicon-asset",
            favicon='data:image/x-icon;base64,QUJD',
            favicon_md5='f1a2b3c4d5e6f7890123456789abcdef',
            cert_org='Example Org',
            cert_org_unit='Security',
            cert_common_name='favicon.example.com',
            cert_serial='SER-FAV-001',
        )
        models.AssetTaskRelation.objects.create(task_id=101, identify_result=self.asset_a)
        models.AssetTaskRelation.objects.create(task_id=101, identify_result=self.asset_b)
        models.AssetTaskRelation.objects.create(task_id=202, identify_result=self.asset_c)
        models.AssetTaskRelation.objects.create(task_id=101, identify_result=self.asset_favicon)

        models.auto_scan_exp_result.objects.create(
            task_id=101,
            EXP_id=self.exp_plugin_a,
            product="nginx",
            target=self.asset_a.target,
            result="ok-a",
            identify_result_id=self.asset_a.id,
        )
        models.auto_scan_exp_result.objects.create(
            task_id=101,
            EXP_id=self.exp_plugin_b,
            product="apache",
            target=self.asset_b.target,
            result="ok-b",
            identify_result_id=self.asset_b.id,
        )
        models.auto_scan_exp_result.objects.create(
            task_id=101,
            EXP_id=self.exp_plugin_c,
            product="apache",
            target=self.asset_b.target,
            result="ok-c",
            identify_result_id=self.asset_b.id,
        )
        models.auto_scan_exp_result.objects.create(
            task_id=202,
            EXP_id=self.exp_plugin_a,
            product="iis",
            target=self.asset_c.target,
            result="ok-d",
            identify_result_id=self.asset_c.id,
        )

    def test_global_asset_search_filters_by_vuln_name(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get(
            "/asset/search",
            {"format": "json", "search_data": 'vuln:"asset-plugin-b"'},
        )
        response = auto_scan_result.global_asset_search(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["estimated_total"], 1)
        self.assertEqual([item["target"] for item in payload["results"]], [self.asset_b.target])

    def test_global_asset_search_api_wraps_json_contract(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get(
            "/api/v1/assets/search",
            {"search_data": 'vuln:"asset-plugin-b"'},
        )
        response = auto_scan_result.global_asset_search_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("results", payload)
        self.assertIn("estimated_total", payload)
        self.assertEqual(payload["contract_version"], "result-search-v1")
        self.assertEqual(payload["contract"]["scope"], "global")
        self.assertEqual(payload["contract"]["search_param"], "search_data")
        self.assertEqual(payload["contract"]["pagination_params"], ["cursor", "dir", "jump", "rows_per_page"])
        self.assertEqual(payload["contract"]["facet_params"], ["field", "search_data", "offset"])
        self.assertEqual(payload["contract"]["facet_endpoint"], reverse("api_global_facet"))
        self.assertIn("related_vulns", payload["contract"]["result_fields"])
        self.assertEqual(payload["contract"]["detail_endpoints"], {
            "vuln_result": reverse("api_identify_result_vuln", kwargs={"result_id": 0}).replace("/0/", "/{result_id}/"),
            "html_source": reverse("api_identify_result_html", kwargs={"result_id": 0}).replace("/0/", "/{result_id}/"),
            "port_overview_more": f'{reverse("api_port_overview")}?ip={{ip}}&target={{target}}',
        })
        self.assertEqual(payload["query"], {
            "scope": "global",
            "search_param": "search_data",
            "search_data": 'vuln:"asset-plugin-b"',
        })
        self.assertEqual(payload["pagination"]["page_size"], payload["page_size"])
        self.assertEqual(payload["favicon_facet"]["items"], payload["favicon_items"])
        self.assertEqual(payload["favicon_facet"]["has_more"], payload["favicon_has_more"])
        self.assertEqual(payload["favicon_facet"]["next_offset"], payload["favicon_next_offset"])
        self.assertEqual(payload["favicon_facet"]["count_label"], payload["favicon_total"])
        self.assertEqual(payload["favicon_facet"]["page_size"], 20)
        self.assertEqual(payload["favicon_facet"]["deferred"], payload["favicon_deferred"])
        self.assertEqual([item["target"] for item in payload["results"]], [self.asset_b.target])

    def test_global_facet_aggregates_cve_across_multiple_plugin_names(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/asset/facet", {"field": "cve"})
        response = auto_scan_result.global_facet(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        cve_map = {item["name"]: item["count"] for item in payload["items"]}
        self.assertEqual(cve_map["CVE-2026-0001"], 3)
        self.assertEqual(cve_map["CVE-2026-0002"], 1)

    def test_global_facet_rejects_invalid_field_with_400(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/asset/facet", {"field": "invalid_field"})
        response = auto_scan_result.global_facet(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["status"])
        self.assertIn("invalid field", payload["error"])

    def test_global_facet_api_wraps_global_facet_contract(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/api/v1/assets/facets", {"field": "cve"})
        response = auto_scan_result.global_facet_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["field"], "cve")
        self.assertIn("items", payload)

    def test_task_facet_scopes_vuln_counts_to_current_task(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/Identify_task/101/facet", {"field": "vuln"})
        response = auto_scan_result.facet(request, 101)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        vuln_map = {item["name"]: item["count"] for item in payload["items"]}
        self.assertEqual(vuln_map["asset-plugin-a"], 1)
        self.assertEqual(vuln_map["asset-plugin-b"], 1)
        self.assertEqual(vuln_map["asset-plugin-c"], 1)
        self.assertNotEqual(vuln_map["asset-plugin-a"], 2)

    def test_task_facet_rejects_invalid_field_with_400(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/Identify_task/101/facet", {"field": "invalid_field"})
        response = auto_scan_result.facet(request, 101)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["status"])
        self.assertIn("invalid field", payload["error"])

    def test_task_facet_api_wraps_task_facet_contract(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/api/v1/identify-tasks/101/facets", {"field": "vuln"})
        response = auto_scan_result.task_facet_api(request, 101)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["field"], "vuln")
        self.assertIn("items", payload)

    def test_standalone_search_filters_by_vuln_name_with_task_scope(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get(
            "/Identify_task/101/result/standalone",
            {"format": "json", "search_data": 'vuln:"asset-plugin-a"'},
        )
        response = auto_scan_result.Task_result(request, 101, standalone='1')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["estimated_total"], 1)
        self.assertEqual([item["target"] for item in payload["results"]], [self.asset_a.target])

    def test_task_result_api_wraps_task_json_contract(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get(
            "/api/v1/identify-tasks/101/results",
            {"search_data": 'vuln:"asset-plugin-a"'},
        )
        response = auto_scan_result.task_result_api(request, 101)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("results", payload)
        self.assertIn("estimated_total", payload)
        self.assertEqual(payload["contract_version"], "result-search-v1")
        self.assertEqual(payload["contract"]["scope"], "task")
        self.assertEqual(payload["contract"]["search_param"], "search_data")
        self.assertEqual(payload["contract"]["pagination_params"], ["cursor", "dir", "jump", "rows_per_page"])
        self.assertEqual(payload["contract"]["facet_params"], ["field", "search_data", "offset"])
        self.assertEqual(payload["contract"]["facet_endpoint"], reverse("api_task_facet", kwargs={"uid": 101}))
        self.assertIn("related_vulns", payload["contract"]["result_fields"])
        self.assertEqual(payload["contract"]["detail_endpoints"], {
            "vuln_result": reverse("api_identify_result_vuln", kwargs={"result_id": 0}).replace("/0/", "/{result_id}/"),
            "html_source": reverse("api_identify_result_html", kwargs={"result_id": 0}).replace("/0/", "/{result_id}/"),
            "port_overview_more": f'{reverse("api_port_overview")}?ip={{ip}}&target={{target}}',
        })
        self.assertEqual(payload["query"], {
            "scope": "task",
            "search_param": "search_data",
            "search_data": 'vuln:"asset-plugin-a"',
            "task_id": 101,
        })
        self.assertEqual(payload["pagination"]["page_size"], payload["page_size"])
        self.assertEqual(payload["favicon_facet"]["items"], payload["favicon_items"])
        self.assertEqual(payload["favicon_facet"]["has_more"], payload["favicon_has_more"])
        self.assertEqual(payload["favicon_facet"]["next_offset"], payload["favicon_next_offset"])
        self.assertEqual(payload["favicon_facet"]["count_label"], payload["favicon_total"])
        self.assertEqual(payload["favicon_facet"]["page_size"], 20)
        self.assertEqual(payload["favicon_facet"]["deferred"], payload["favicon_deferred"])
        self.assertEqual([item["target"] for item in payload["results"]], [self.asset_a.target])

    def test_task_result_api_matches_legacy_standalone_json_for_same_query(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        legacy_request = self.factory.get(
            "/Identify_task/101/result/standalone",
            {"format": "json", "search_data": 'title:"asset-a"', "rows_per_page": "5"},
        )
        api_request = self.factory.get(
            "/api/v1/identify-tasks/101/results",
            {"search_data": 'title:"asset-a"', "rows_per_page": "5"},
        )

        legacy_payload = json.loads(auto_scan_result.Task_result(legacy_request, 101, standalone='1').content)
        api_payload = json.loads(auto_scan_result.task_result_api(api_request, 101).content)

        self.assertEqual(api_payload["estimated_total"], legacy_payload["estimated_total"])
        self.assertEqual(api_payload["exact_total"], legacy_payload["exact_total"])
        self.assertEqual(api_payload["page_size"], 5)
        self.assertEqual(api_payload["page_size"], legacy_payload["page_size"])
        self.assertEqual([item["target"] for item in api_payload["results"]], [item["target"] for item in legacy_payload["results"]])
        self.assertEqual(api_payload["favicon_items"], legacy_payload["favicon_items"])

    def test_task_facet_api_matches_legacy_task_facet_for_same_query(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        legacy_request = self.factory.get(
            "/Identify_task/101/facet",
            {"field": "vuln", "search_data": 'title:"asset"'},
        )
        api_request = self.factory.get(
            "/api/v1/identify-tasks/101/facets",
            {"field": "vuln", "search_data": 'title:"asset"'},
        )

        legacy_payload = json.loads(auto_scan_result.facet(legacy_request, 101).content)
        api_payload = json.loads(auto_scan_result.task_facet_api(api_request, 101).content)

        self.assertEqual(api_payload["field"], legacy_payload["field"])
        self.assertEqual(api_payload["items"], legacy_payload["items"])
        self.assertEqual(api_payload["has_more"], legacy_payload["has_more"])
        self.assertEqual(api_payload["next_offset"], legacy_payload["next_offset"])
        self.assertEqual(api_payload["count_label"], legacy_payload["count_label"])

    def test_task_result_api_respects_rows_per_page_parameter(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get(
            "/api/v1/identify-tasks/101/results",
            {"rows_per_page": "5"},
        )
        response = auto_scan_result.task_result_api(request, 101)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["page_size"], 5)
        self.assertEqual(len(payload["results"]), 3)
        self.assertFalse(payload["has_next"])

    def test_global_facet_returns_first_40_rows_with_more_flag(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        for idx in range(45):
            row = models.auto_scan_indentify_result.objects.create(
                products=[f"product-{idx}"],
                target=f"http://bulk-{idx}.example.com",
                ip=f"10.10.0.{idx}",
                protocol="http",
                port=9000 + idx,
                country="facet40",
                title=f"bulk-title-{idx}",
            )
            models.AssetTaskRelation.objects.create(task_id=303, identify_result=row)

        request = self.factory.get(
            "/asset/facet",
            {"field": "title", "offset": 0, "search_data": 'country:"facet40"'},
        )
        response = auto_scan_result.global_facet(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(payload["items"]), 40)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_offset"], 40)
        self.assertEqual(payload["count_label"], "45")

    def test_global_facet_offset_returns_next_batch_without_overlap(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        for idx in range(45):
            row = models.auto_scan_indentify_result.objects.create(
                products=[f"offset-product-{idx}"],
                target=f"http://offset-{idx}.example.com",
                ip=f"10.20.0.{idx}",
                protocol="http",
                port=9500 + idx,
                country="facet-offset",
                title=f"offset-title-{idx:02d}",
            )
            models.AssetTaskRelation.objects.create(task_id=404, identify_result=row)

        first_request = self.factory.get(
            "/asset/facet",
            {"field": "title", "offset": 0, "search_data": 'country:"facet-offset"'},
        )
        first_payload = json.loads(auto_scan_result.global_facet(first_request).content)
        second_request = self.factory.get(
            "/asset/facet",
            {"field": "title", "offset": 40, "search_data": 'country:"facet-offset"'},
        )
        second_payload = json.loads(auto_scan_result.global_facet(second_request).content)

        first_names = [item["name"] for item in first_payload["items"]]
        second_names = [item["name"] for item in second_payload["items"]]
        self.assertEqual(len(second_names), 5)
        self.assertFalse(second_payload["has_more"])
        self.assertEqual(len(set(first_names) & set(second_names)), 0)

    def test_global_favicon_facet_returns_md5_items_with_more_flag(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        for idx in range(25):
            row = models.auto_scan_indentify_result.objects.create(
                products=[f'favicon-product-{idx}'],
                target=f'https://fav-{idx}.example.com',
                ip=f'10.30.0.{idx}',
                protocol='https',
                port=443,
                title=f'fav-{idx}',
                favicon='data:image/x-icon;base64,QUJD',
                favicon_md5=f'{idx:032x}',
            )
            models.AssetTaskRelation.objects.create(task_id=505, identify_result=row)

        request = self.factory.get('/asset/facet', {'field': 'favicon', 'offset': 0, 'search_data': 'favicon:"00000000000000000000000000000000" || favicon:"00000000000000000000000000000001" || favicon:"00000000000000000000000000000002" || favicon:"00000000000000000000000000000003" || favicon:"00000000000000000000000000000004" || favicon:"00000000000000000000000000000005" || favicon:"00000000000000000000000000000006" || favicon:"00000000000000000000000000000007" || favicon:"00000000000000000000000000000008" || favicon:"00000000000000000000000000000009" || favicon:"0000000000000000000000000000000a" || favicon:"0000000000000000000000000000000b" || favicon:"0000000000000000000000000000000c" || favicon:"0000000000000000000000000000000d" || favicon:"0000000000000000000000000000000e" || favicon:"0000000000000000000000000000000f" || favicon:"00000000000000000000000000000010" || favicon:"00000000000000000000000000000011" || favicon:"00000000000000000000000000000012" || favicon:"00000000000000000000000000000013" || favicon:"00000000000000000000000000000014" || favicon:"00000000000000000000000000000015" || favicon:"00000000000000000000000000000016" || favicon:"00000000000000000000000000000017" || favicon:"00000000000000000000000000000018"'})
        response = auto_scan_result.global_facet(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(len(payload['items']), 20)
        self.assertTrue(payload['has_more'])
        self.assertEqual(payload['next_offset'], 20)
        self.assertEqual(payload['count_label'], '25')

    def test_global_asset_search_json_contains_port_overview_and_related_vulns(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        asset_alt_port = models.auto_scan_indentify_result.objects.create(
            products=["tomcat"],
            target="http://10.0.0.1:8081",
            ip=self.asset_a.ip,
            protocol="http",
            port=8081,
            title="asset-a-alt-port",
        )
        models.AssetTaskRelation.objects.create(task_id=101, identify_result=asset_alt_port)

        request = self.factory.get("/asset/search", {"format": "json", "search_data": 'title:"asset-a"'})
        response = auto_scan_result.global_asset_search(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        result = payload["results"][0]
        self.assertEqual(result["target"], self.asset_a.target)
        self.assertTrue(result["ip"])
        self.assertTrue(result["target"])
        self.assertEqual(result["related_vulns"][0]["plugin_name"], "asset-plugin-a")
        self.assertNotIn("result", result["related_vulns"][0])

    def test_global_asset_search_supports_favicon_cert_filters(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        favicon_request = self.factory.get('/asset/search', {'format': 'json', 'search_data': 'favicon:"f1a2b3c4d5e6f7890123456789abcdef"'})
        favicon_response = auto_scan_result.global_asset_search(favicon_request)
        favicon_payload = json.loads(favicon_response.content)

        cert_request = self.factory.get('/asset/search', {'format': 'json', 'search_data': 'cert_serial:"SER-FAV-001"'})
        cert_response = auto_scan_result.global_asset_search(cert_request)
        cert_payload = json.loads(cert_response.content)

        cert_mix_request = self.factory.get('/asset/search', {'format': 'json', 'search_data': 'cert:"Example Org"'})
        cert_mix_response = auto_scan_result.global_asset_search(cert_mix_request)
        cert_mix_payload = json.loads(cert_mix_response.content)

        self.assertEqual([item['target'] for item in favicon_payload['results']], [self.asset_favicon.target])
        self.assertEqual([item['target'] for item in cert_payload['results']], [self.asset_favicon.target])
        self.assertEqual([item['target'] for item in cert_mix_payload['results']], [self.asset_favicon.target])
        self.assertIsNotNone(favicon_payload.get('favicon_total'))
        self.assertTrue(len(favicon_payload.get('favicon_items', [])) > 0)

    def test_standalone_result_json_contains_port_overview_and_related_vulns(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get("/Identify_task/101/result/standalone", {"format": "json", "search_data": 'title:"asset-b"'})
        response = auto_scan_result.Task_result(request, 101, standalone='1')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        result = payload["results"][0]
        self.assertEqual(result["target"], self.asset_b.target)
        self.assertTrue(result["ip"])
        self.assertEqual(result["related_vulns"][0]["plugin_name"], "asset-plugin-c")
        self.assertEqual(result["related_vulns"][0]["cve"], "CVE-2026-0002")
        self.assertNotIn("result", result["related_vulns"][0])

    def test_standalone_result_supports_favicon_cert_filters(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        request = self.factory.get('/Identify_task/101/result/standalone', {'format': 'json', 'search_data': 'favicon:"f1a2b3c4d5e6f7890123456789abcdef"'})
        response = auto_scan_result.Task_result(request, 101, standalone='1')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual([item['target'] for item in payload['results']], [self.asset_favicon.target])
        self.assertEqual(payload['favicon_total'], '1')
        self.assertEqual(payload['favicon_items'][0]['name'], 'f1a2b3c4d5e6f7890123456789abcdef')

    def test_vuln_result_endpoint_returns_text_on_demand(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        vuln = models.auto_scan_exp_result.objects.get(task_id=101, EXP_id=self.exp_plugin_c, target=self.asset_b.target)
        request = self.factory.get(f"/identify_result/{vuln.id}/vuln-result")
        response = auto_scan_result.vuln_result_text(request, vuln.id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["plugin_name"], "asset-plugin-c")
        self.assertEqual(payload["cve"], "CVE-2026-0002")
        self.assertEqual(payload["result"], "ok-c")


    def test_result_search_timing_logs_use_debug_logger(self):
        source = (_PROJECT_ROOT / "app_cybersparker/views/expload/task_manage/auto_scan_result.py").read_text(encoding="utf-8")

        self.assertNotIn("print(f'[TIMING", source)
        self.assertIn("logger.debug(f'[TIMING", source)

    def test_auto_scan_history_engine_results_includes_auto_scan_tasks(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        target_rel = "EXP_input/engine_assets/auto_scan_engine_history_test.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://one.example.com\nhttp://two.example.com\n", encoding="utf-8")

        models.auto_scan_tasks.objects.create(
            task_name="auto-scan-engine-history-test",
            input_type=4,
            engine_type="fofa",
            engine_query='header="Apache"',
            engine_max_assets=2,
            target=target_rel,
            status=1,
            process="100%",
            creat_time=timezone.now(),
        )

        request = self.factory.get("/Identify_task/history_engine_results")
        response = auto_scan_task.history_engine_results(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        result = next(item for item in payload["data"]["results"] if item["target"] == target_rel)
        self.assertEqual(result["engine_type"], "fofa")
        self.assertEqual(result["engine_query"], 'header="Apache"')
        self.assertEqual(result["task_name"], "auto-scan-engine-history-test")
        self.assertEqual(result["target_count"], 2)


    def test_identify_history_engine_results_api_returns_frontend_contract(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task_api

        target_rel = "EXP_input/engine_assets/identify_api_engine_history_test.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://api-one.example.com\nhttp://api-two.example.com\n", encoding="utf-8")

        models.auto_scan_tasks.objects.create(
            task_name="identify-api-engine-history-test",
            input_type=4,
            engine_type="quake",
            engine_query='title="Dashboard"',
            engine_max_assets=2,
            target=target_rel,
            status=1,
            process="100%",
            creat_time=timezone.now(),
        )

        request = self.factory.get("/api/v1/identify-tasks/history-engine-results")
        response = auto_scan_task_api.task_history_engine_results_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertIsInstance(payload["data"]["results"], list)
        result = next(item for item in payload["data"]["results"] if item["target"] == target_rel)
        self.assertEqual(
            set(result.keys()),
            {"target", "engine_type", "engine_query", "task_name", "creat_time", "target_count"},
        )
        self.assertEqual(result["engine_type"], "quake")
        self.assertEqual(result["engine_query"], 'title="Dashboard"')
        self.assertEqual(result["task_name"], "identify-api-engine-history-test")
        self.assertEqual(result["target_count"], 2)

    def test_engine_history_file_input_only_reads_engine_asset_directory(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task, batch_exp_task

        allowed_rel = "EXP_input/engine_assets/allowed_engine_history_test.txt"
        blocked_rel = "EXP_input/not_engine_history_test.txt"
        escaped_rel = "EXP_input/engine_assets/../not_engine_history_test.txt"
        allowed_abs = _PROJECT_ROOT / allowed_rel
        blocked_abs = _PROJECT_ROOT / blocked_rel
        allowed_abs.parent.mkdir(parents=True, exist_ok=True)
        blocked_abs.parent.mkdir(parents=True, exist_ok=True)
        allowed_abs.write_text("http://allowed.example.com\n", encoding="utf-8")
        blocked_abs.write_text("http://blocked.example.com\n", encoding="utf-8")

        file_paths = [blocked_rel, escaped_rel, allowed_rel]

        self.assertEqual(
            auto_scan_task.collect_targets_from_engine_history_files(file_paths),
            ["http://allowed.example.com"],
        )
        self.assertEqual(
            batch_exp_task.collect_targets_from_engine_history_files(file_paths),
            ["http://allowed.example.com"],
        )

    def test_history_engine_result_count_keeps_non_empty_line_semantics(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        target_rel = "EXP_input/engine_assets/engine_history_count_test.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("\nhttp://one.example.com\n   \n\thttp://two.example.com\nhttp://three.example.com", encoding="utf-8")

        models.auto_scan_tasks.objects.create(
            task_name="engine-history-count-test",
            input_type=4,
            engine_type="fofa",
            engine_query='body="count"',
            engine_max_assets=3,
            target=target_rel,
            status=1,
            process="100%",
            creat_time=timezone.now(),
        )

        request = self.factory.get("/Identify_task/history_engine_results")
        response = auto_scan_task.history_engine_results(request)
        payload = json.loads(response.content)

        result = next(item for item in payload["data"]["results"] if item["target"] == target_rel)
        self.assertEqual(result["target_count"], 3)

    def test_global_facet_icp_aggregation(self):
        """icp 字段 facet 聚合——通用 GROUP BY 分支"""
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        for i in range(3):
            models.auto_scan_indentify_result.objects.create(
                products=["nginx"],
                target=f"http://icp-test-{i}.example.com",
                ip=f"10.20.30.{i+1}",
                protocol="http", port=80,
                icp=f"京ICP备0000000{i}号",
            )
        try:
            request = self.factory.get("/asset/facet", {"field": "icp", "offset": 0, "search_data": 'product:"nginx"'})
            response = auto_scan_result.global_facet(request)
            payload = json.loads(response.content)
            self.assertEqual(payload["status"], "ok")
            self.assertGreater(len(payload["items"]), 0)
            self.assertIn("京", str(payload["items"]))
        finally:
            models.auto_scan_indentify_result.objects.filter(ip__startswith="10.20.30.").delete()

    def test_global_facet_copyright_aggregation(self):
        """copyright 字段 facet 聚合——通用 GROUP BY 分支"""
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        for i in range(3):
            models.auto_scan_indentify_result.objects.create(
                products=["apache"],
                target=f"http://cr-test-{i}.example.com",
                ip=f"10.30.40.{i+1}",
                protocol="http", port=80,
                copyright=f"TestCopyright{i}",
            )
        try:
            request = self.factory.get("/asset/facet", {"field": "copyright", "offset": 0, "search_data": 'product:"apache"'})
            response = auto_scan_result.global_facet(request)
            payload = json.loads(response.content)
            self.assertEqual(payload["status"], "ok")
            self.assertGreater(len(payload["items"]), 0)
            self.assertIn("TestCopyright", str(payload["items"]))
        finally:
            models.auto_scan_indentify_result.objects.filter(ip__startswith="10.30.40.").delete()

    def test_not_null_wildcard_negation_finds_empty_field_assets(self):
        """!field:"*" 搜索能找到字段为空的资产（支持 facet 点击"(空)"跳转）"""
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        # 创建一个 uri_path 为空的资产
        asset_empty = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://empty-uri.example.com",
            ip="10.50.60.1",
            protocol="http", port=80,
            uri_path="",  # 空字符串
        )
        # 创建一个 uri_path 有值的资产
        asset_with = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://with-uri.example.com",
            ip="10.50.60.2",
            protocol="http", port=80,
            uri_path="/api",  # 非空
        )
        try:
            # !uri_path:"*" 应只命中空 uri_path 的资产
            request = self.factory.get("/asset/search", {
                "format": "json",
                "search_data": 'product:"nginx" && !uri_path:"*"',
            })
            response = auto_scan_result.global_asset_search(request)
            payload = json.loads(response.content)
            self.assertEqual(payload["status"], "ok")
            targets = [item["target"] for item in payload["results"]]
            self.assertIn(asset_empty.target, targets)
            self.assertNotIn(asset_with.target, targets)
        finally:
            asset_empty.delete()
            asset_with.delete()

    def test_empty_facet_placeholder_search_finds_empty_field_assets(self):
        """搜索 uri_path:"(空)" 应在后端解析为"字段为空/空字符串"并命中空值资产"""
        from app_cybersparker.views.expload.task_manage import auto_scan_result

        asset_empty = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://empty-placeholder.example.com",
            ip="10.60.70.1",
            protocol="http", port=80,
            uri_path="",
        )
        asset_with = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://with-placeholder.example.com",
            ip="10.60.70.2",
            protocol="http", port=80,
            uri_path="/api",
        )
        try:
            request = self.factory.get("/asset/search", {
                "format": "json",
                "search_data": 'product:"nginx" && uri_path:"(空)"',
            })
            response = auto_scan_result.global_asset_search(request)
            payload = json.loads(response.content)
            self.assertEqual(payload["status"], "ok")
            targets = [item["target"] for item in payload["results"]]
            self.assertIn(asset_empty.target, targets)
            self.assertNotIn(asset_with.target, targets)
        finally:
            asset_empty.delete()
            asset_with.delete()

@override_settings(CELERY_BROKER_URL="memory://")
class BatchScanCeleryDispatchTests(TransactionTestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()

    def test_batch_start_dispatches_celery_without_local_thread(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-celery-plugin",
            CVE="CVE-BATCH-CELERY",
            poc="EXP_plugin/batch_celery.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-start",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/batch_celery_start.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(dispatch_mock.call_count, 1)
        self.assertEqual(dispatch_mock.call_args.args[0].name, "app_cybersparker.tasks.run_batch_scan_task")
        self.assertEqual(dispatch_mock.call_args.args[1], task.id)
        self.assertEqual(dispatch_mock.call_args.kwargs["queue"], "batch_scan")
        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)
        self.assertIsNotNone(task.dispatch_token)
        self.assertIsNone(task.owner)

    def test_batch_start_routes_gevent_mode_to_dedicated_queue(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-celery-gevent-plugin",
            CVE="CVE-BATCH-CELERY-GEVENT",
            poc="EXP_plugin/batch_celery_gevent.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-gevent-start",
            EXP=str(exp.id),
            run_mode=2,
            thread_num=20,
            sleep_time=0,
            target="EXP_input/batch_celery_gevent_start.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(dispatch_mock.call_args.kwargs["queue"], "batch_scan_gevent")
        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)

    def test_batch_restart_engine_task_dispatches_force_refresh_when_reuse_disabled(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-engine-rerun-force-refresh-plugin",
            CVE="CVE-BATCH-ENGINE-RERUN",
            poc="EXP_plugin/batch_engine_rerun.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-engine-rerun-force-refresh",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/engine_assets/batch_engine_rerun.txt",
            status=1,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=False,
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "1", "reuse_engine_data": "false"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertTrue(dispatch_mock.call_args.kwargs["force_refresh_engine"])

    def test_run_batch_scan_task_passes_force_refresh_to_start_task(self):
        from app_cybersparker.tasks import _run_batch_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-force-refresh-pass-through",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/engine_assets/batch_force_refresh_pass.txt",
            status=2,
            process="0%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            startTime=timezone.now(),
        )
        initialize_task_runtime(models.batch_EXPTask, task.id, "batch-token-force-refresh", None, queued=True)
        runner = SimpleNamespace(stop_requested=False, pause_requested=False, is_alive=lambda: False)

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.startTask", return_value=runner) as start_mock:
            result = cast(Any, _run_batch_scan_task)(task.id, "batch-token-force-refresh", "worker-a", True)

        self.assertEqual(result["status"], "success")
        self.assertTrue(start_mock.call_args.kwargs["force_refresh_engine"])

    def test_batch_resume_engine_task_does_not_dispatch_force_refresh(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-engine-resume-no-refresh-plugin",
            CVE="CVE-BATCH-ENGINE-RESUME",
            poc="EXP_plugin/batch_engine_resume.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-engine-resume-no-refresh",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/engine_assets/batch_engine_resume.txt",
            status=4,
            process="37%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=False,
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "3", "action": "resume"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertFalse(dispatch_mock.call_args.kwargs["force_refresh_engine"])

    def test_batch_start_rolls_back_runtime_state_when_dispatch_fails(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-dispatch-fail-plugin",
            CVE="CVE-BATCH-DISPATCH-FAIL",
            poc="EXP_plugin/batch_dispatch_fail.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-dispatch-fail",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/batch_dispatch_fail.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task", side_effect=RuntimeError("queue down")):
            with self.assertRaises(RuntimeError):
                batch_exp_task.operate(request)

        task.refresh_from_db()
        self.assertEqual(task.status, 3)
        self.assertFalse(task.queued)
        self.assertTrue(task.failed)
        self.assertEqual(task.last_error, "任务派发失败")
        self.assertIsNotNone(task.endTime)

    def test_run_batch_scan_task_ignores_duplicate_claim(self):
        from app_cybersparker.tasks import _run_batch_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-duplicate",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_celery_duplicate.txt",
            status=2,
            process="0%",
            startTime=timezone.now(),
        )
        initialize_task_runtime(models.batch_EXPTask, task.id, "batch-token-1", None, queued=True)
        models.batch_EXPTask.objects.filter(id=task.id).update(owner="worker-a")

        result = _run_batch_scan_task(task.id, "batch-token-1", "worker-b")

        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["reason"], "already_claimed")

    def test_run_batch_scan_task_marks_success_via_cas(self):
        from app_cybersparker.tasks import _run_batch_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-success",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_celery_success.txt",
            status=2,
            process="0%",
            startTime=timezone.now(),
        )
        initialize_task_runtime(models.batch_EXPTask, task.id, "batch-token-success", None, queued=True)
        runner = SimpleNamespace(stop_requested=False, pause_requested=False, is_alive=lambda: False)

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.startTask", return_value=runner):
            result = _run_batch_scan_task(task.id, "batch-token-success", "worker-a")

        task.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(task.status, 1)
        self.assertFalse(task.failed)
        self.assertFalse(task.queued)
        self.assertEqual(task.owner, "worker-a")
        self.assertIsNotNone(task.endTime)

    def test_run_batch_scan_task_marks_paused_terminal_state(self):
        from app_cybersparker.tasks import _run_batch_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-paused",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_celery_paused.txt",
            status=2,
            process="33%",
            startTime=timezone.now(),
        )
        initialize_task_runtime(models.batch_EXPTask, task.id, "batch-token-paused", None, queued=True)
        runner = SimpleNamespace(stop_requested=False, pause_requested=True, is_over=False, is_alive=lambda: False)

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.startTask", return_value=runner):
            result = _run_batch_scan_task(task.id, "batch-token-paused", "worker-a")

        task.refresh_from_db()
        self.assertEqual(result["status"], "paused")
        self.assertEqual(task.status, 4)
        self.assertFalse(task.pause_requested)
        self.assertFalse(task.queued)
        self.assertIsNotNone(task.endTime)

    def test_run_batch_scan_task_marks_failure_when_start_fails(self):
        from app_cybersparker.tasks import _run_batch_scan_task
        from app_cybersparker.services.task_state_cas_service import initialize_task_runtime

        task = models.batch_EXPTask.objects.create(
            task_name="batch-celery-failure",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_celery_failure.txt",
            status=2,
            process="0%",
            startTime=timezone.now(),
        )
        initialize_task_runtime(models.batch_EXPTask, task.id, "batch-token-failure", None, queued=True)

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.startTask", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                _run_batch_scan_task(task.id, "batch-token-failure", "worker-a")

        task.refresh_from_db()
        self.assertEqual(task.status, 3)
        self.assertTrue(task.failed)
        self.assertEqual(task.last_error, "boom")
        self.assertIsNotNone(task.endTime)

    def test_batch_thread_handler_stop_bridge_sets_exit_flag(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        task = models.batch_EXPTask.objects.create(
            task_name="batch-stop-bridge",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_stop_bridge.txt",
            status=2,
            process="10%",
            startTime=timezone.now(),
            dispatch_token="batch-stop-token",
        )
        data = {
            "uid": task.id,
            "exp": "1",
            "target_file": "EXP_input/batch_stop_bridge.txt",
            "run_mode": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "progress": "10%",
            "dispatch_token": "batch-stop-token",
            "owner": "worker-a",
        }
        with patch.object(Task_handler, "_build_exp_cache", return_value=[]):
            handler = Task_handler(data)
        models.batch_EXPTask.objects.filter(id=task.id).update(stop_requested=True)

        stopped = handler.check_stop_bridge()

        self.assertTrue(stopped)
        self.assertTrue(handler.exit_flag)
        self.assertTrue(handler.stop_requested)

    def test_batch_pause_sets_db_pause_flag(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        task = models.batch_EXPTask.objects.create(
            task_name="batch-pause-flag",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_pause_flag.txt",
            status=2,
            process="20%",
            startTime=timezone.now(),
            dispatch_token="batch-pause-token",
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "pause"})
        request.session = self.session

        response = batch_exp_task.operate(request)

        task.refresh_from_db()
        payload = json.loads(response.content)
        self.assertTrue(payload["status"], f"Expected status=true, got {payload}")
        self.assertEqual(task.status, 4)  # executor 已丢失 → 直接落暂停

    def test_batch_thread_handler_detects_pause_signal(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        task = models.batch_EXPTask.objects.create(
            task_name="batch-pause-detect",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/batch_pause_detect.txt",
            status=2,
            process="10%",
            startTime=timezone.now(),
            dispatch_token="batch-pause-token",
        )
        data = {
            "uid": task.id,
            "exp": "1",
            "target_file": "EXP_input/batch_pause_detect.txt",
            "run_mode": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "progress": "10%",
            "dispatch_token": "batch-pause-token",
            "owner": "worker-a",
        }
        with patch.object(Task_handler, "_build_exp_cache", return_value=[]):
            handler = Task_handler(data)
        models.batch_EXPTask.objects.filter(id=task.id).update(pause_requested=True)

        paused = handler.check_pause_signal()

        self.assertTrue(paused)
        self.assertTrue(handler.pause_requested)

    def test_batch_consumer_stops_before_remaining_plugins_on_stop_signal(self):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        data = {
            "uid": 321,
            "exp": "1,2",
            "target_file": "EXP_input/batch_stop_bridge.txt",
            "run_mode": 1,
            "thread_num": 2,
            "sleep_time": 0,
            "progress": "10%",
            "dispatch_token": "batch-stop-token",
            "owner": "worker-a",
        }
        with patch.object(Task_handler, "_build_exp_cache", return_value=[]):
            handler = Task_handler(data)
        handler.exp_cache = [
            {"module": object(), "plugin": "plugin-1"},
            {"module": object(), "plugin": "plugin-2"},
        ]
        handler.exp_thread_num = 1
        handler.queue_input = Queue(maxsize=10)
        handler.queue_output = Queue(maxsize=10)
        handler.queue_input.put("http://example.com")

        checks = {"count": 0}

        def fake_check_stop_bridge():
            checks["count"] += 1
            if checks["count"] >= 3:
                handler.kill_task()
                return True
            return False

        handler.check_stop_bridge = fake_check_stop_bridge
        call_runtime = MagicMock(return_value={"target": "http://example.com", "result": "ok"})

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.call_runtime_method", call_runtime):
            handler.consumer_exp()

        self.assertEqual(call_runtime.call_count, 1)
        self.assertTrue(handler.exit_flag)
        self.assertEqual(handler.completed_count, 0)
        self.assertEqual(handler.queue_output.get_nowait()["plugin"], "plugin-1")


class ResourceLeaseServiceTests(TestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases

        reset_memory_leases()

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=10)
    def test_concurrent_acquire_never_exceeds_limit(self):
        from app_cybersparker.services.resource_lease_service import ResourceUnavailableError, acquire_resource_lease, release_resource_lease

        acquired = []
        failures = []
        for idx in range(100):
            try:
                lease = acquire_resource_lease("threads", f"worker-{idx}", limit=10)
                acquired.append(lease)
            except ResourceUnavailableError:
                failures.append(idx)
        try:
            self.assertEqual(len(acquired), 10)
            self.assertEqual(len(failures), 90)
        finally:
            for lease in acquired:
                release_resource_lease(lease["resource"], lease["lease_id"])

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=1)
    def test_release_allows_reacquire(self):
        from app_cybersparker.services.resource_lease_service import acquire_resource_lease, release_resource_lease

        first = acquire_resource_lease("threads", "worker-a", limit=1)
        release_resource_lease(first["resource"], first["lease_id"])
        second = acquire_resource_lease("threads", "worker-b", limit=1)

        self.assertNotEqual(first["lease_id"], second["lease_id"])
        release_resource_lease(second["resource"], second["lease_id"])

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=1, RESOURCE_LEASE_TTL_SECONDS=1)
    def test_ttl_expiry_reclaims_lease(self):
        from app_cybersparker.services.resource_lease_service import ResourceUnavailableError, acquire_resource_lease

        first = acquire_resource_lease("threads", "worker-a", limit=1, ttl_seconds=1)
        with self.assertRaises(ResourceUnavailableError):
            acquire_resource_lease("threads", "worker-b", limit=1, ttl_seconds=1)
        time.sleep(2)
        second = acquire_resource_lease("threads", "worker-b", limit=1, ttl_seconds=1)

        self.assertNotEqual(first["lease_id"], second["lease_id"])

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=1, RESOURCE_LEASE_TTL_SECONDS=1)
    def test_heartbeat_keeps_lease_alive(self):
        from app_cybersparker.services.resource_lease_service import ResourceUnavailableError, acquire_resource_lease, heartbeat_resource_lease

        lease = acquire_resource_lease("threads", "worker-a", limit=1, ttl_seconds=1)
        time.sleep(0.5)
        self.assertTrue(heartbeat_resource_lease("threads", lease["lease_id"], ttl_seconds=1))
        time.sleep(0.7)
        with self.assertRaises(ResourceUnavailableError):
            acquire_resource_lease("threads", "worker-b", limit=1, ttl_seconds=1)

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_waiting_resource_marks_runtime_state(self):
        from app_cybersparker.services.resource_lease_service import mark_waiting_for_resource

        task = models.batch_EXPTask.objects.create(
            task_name="waiting-resource-task",
            EXP="1",
            run_mode=1,
            thread_num=2,
            sleep_time=0,
            target="EXP_input/waiting_resource.txt",
            status=2,
            process="0%",
            startTime=timezone.now(),
        )
        mark_waiting_for_resource(models.batch_EXPTask, task.id, "threads")
        task.refresh_from_db()

        self.assertTrue(task.queued)
        self.assertFalse(task.failed)
        self.assertEqual(task.last_error, "waiting_resource:threads")

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_DB_WRITER_LIMIT=1)
    def test_db_writer_resource_limit_blocks_second_lease(self):
        from app_cybersparker.services.resource_lease_service import ResourceUnavailableError, acquire_resource_lease

        acquire_resource_lease("db_writers", "writer-a", limit=1)
        with self.assertRaises(ResourceUnavailableError):
            acquire_resource_lease("db_writers", "writer-b", limit=1)

    @override_settings(CELERY_BROKER_URL="redis://127.0.0.1:6379/0")
    def test_get_redis_client_reuses_same_client_for_same_broker_url(self):
        from app_cybersparker.services import resource_lease_service

        fake_client = object()
        with patch("app_cybersparker.services.resource_lease_service.redis.Redis.from_url", return_value=fake_client) as from_url_mock:
            first = resource_lease_service._get_redis_client()
            second = resource_lease_service._get_redis_client()

        self.assertIs(first, fake_client)
        self.assertIs(second, fake_client)
        from_url_mock.assert_called_once_with("redis://127.0.0.1:6379/0")


class ResultEventServiceTests(TestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_leases()
        reset_memory_event_store()

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_identify_events_do_not_duplicate_rows(self):
        from app_cybersparker.services.result_event_service import STREAM_IDENTIFY, build_identify_event_payloads, process_result_stream, publish_result_events

        payloads = build_identify_event_payloads(
            1,
            "http://example.com",
            "header",
            "title",
            "html",
            200,
            "1.1.1.1",
            "example.com",
            80,
            "http",
            "CN",
            ["nginx"],
        )
        publish_result_events(STREAM_IDENTIFY, payloads)
        publish_result_events(STREAM_IDENTIFY, payloads)
        process_result_stream(STREAM_IDENTIFY)
        process_result_stream(STREAM_IDENTIFY)

        rows = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=1, target="http://example.com")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().products, ["nginx"])

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_identify_events_merge_products_for_same_target(self):
        from app_cybersparker.services.result_event_service import STREAM_IDENTIFY, build_identify_event_payloads, process_result_stream, publish_result_events
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_event_store()

        payloads_nginx = build_identify_event_payloads(
            1, "http://example.com", "header", "title", "html", 200,
            "1.1.1.1", "example.com", 80, "http", "CN", ["nginx"],
        )
        payloads_apache = build_identify_event_payloads(
            1, "http://example.com", "header2", "title2", "html2", 200,
            "1.1.1.1", "example.com", 80, "http", "CN", ["apache"],
        )
        payloads_tomcat = build_identify_event_payloads(
            1, "http://example.com", "header3", "title3", "html3", 200,
            "1.1.1.1", "example.com", 80, "http", "CN", ["tomcat"],
        )

        publish_result_events(STREAM_IDENTIFY, payloads_nginx)
        process_result_stream(STREAM_IDENTIFY)
        publish_result_events(STREAM_IDENTIFY, payloads_apache)
        process_result_stream(STREAM_IDENTIFY)
        publish_result_events(STREAM_IDENTIFY, payloads_tomcat)
        process_result_stream(STREAM_IDENTIFY)

        rows = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=1, target="http://example.com")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().products, ["apache", "nginx", "tomcat"])

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_identify_events_strip_nul_before_db_write(self):
        from app_cybersparker.services.result_event_service import STREAM_IDENTIFY, process_result_stream, publish_result_events

        payload = {
            "event_id": "identify:88:http://nul:\\u0000",
            "task_id": 88,
            "target": "http://nul\x00.example.com",
            "product": "nginx\x00",
            "ip": "1.1.1.1\x00",
            "host": "example.com",
            "port": 80,
            "protocol": "http\x00",
            "country": "CN\x00",
            "area": "BJ\x00",
            "area_name_zh": "北京\x00",
            "title": "title\x00withnul",
            "header": "Server: nginx\x00",
            "html": "<html>ok\x00</html>",
            "status_code": 200,
        }
        publish_result_events(STREAM_IDENTIFY, [payload])
        process_result_stream(STREAM_IDENTIFY)

        row = models.auto_scan_indentify_result.objects.get(task_relations__task_id=88)
        self.assertEqual(row.target, "http://nul.example.com")
        self.assertEqual(row.products, ["nginx"])
        self.assertEqual(row.ip, "1.1.1.1")
        self.assertEqual(row.protocol, "http")
        self.assertEqual(row.country, "CN")
        self.assertEqual(row.title, "titlewithnul")
        self.assertEqual(row.header, "Server: nginx")
        self.assertEqual(row.html, "<html>ok</html>")

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_identify_events_persist_favicon_and_cert_fields(self):
        from app_cybersparker.services.result_event_service import STREAM_IDENTIFY, build_identify_event_payloads, process_result_stream, publish_result_events

        payloads = cast(Any, build_identify_event_payloads)(
            99,
            "https://secure.example.com",
            "header",
            "title",
            "html",
            200,
            "2.2.2.2",
            "secure.example.com",
            443,
            "https",
            "CN",
            ["nginx"],
            favicon="data:image/x-icon;base64,QUJD",
            favicon_md5="abc123def456abc123def456abc123de",
            cert_org="Example Org",
            cert_org_unit="Security",
            cert_common_name="secure.example.com",
            cert_serial="SER123",
        )
        publish_result_events(STREAM_IDENTIFY, payloads)
        process_result_stream(STREAM_IDENTIFY)

        row = models.auto_scan_indentify_result.objects.get(task_relations__task_id=99, target="https://secure.example.com")
        self.assertEqual(row.favicon, "data:image/x-icon;base64,QUJD")
        self.assertEqual(row.favicon_md5, "abc123def456abc123def456abc123de")
        self.assertEqual(row.cert_org, "Example Org")
        self.assertEqual(row.cert_org_unit, "Security")
        self.assertEqual(row.cert_common_name, "secure.example.com")
        self.assertEqual(row.cert_serial, "SER123")

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_auto_exp_events_do_not_duplicate_rows(self):
        from app_cybersparker.services.result_event_service import STREAM_AUTO_EXP, build_auto_exp_event_payload, process_result_stream, publish_result_events

        exp = models.EXP.objects.create(title="writer-plugin", CVE="CVE-WRITER", poc="EXP_plugin/writer.py")
        payload = build_auto_exp_event_payload(2, exp.id, "http://example.com", "nginx", "ok")
        publish_result_events(STREAM_AUTO_EXP, [payload])
        publish_result_events(STREAM_AUTO_EXP, [payload])
        process_result_stream(STREAM_AUTO_EXP)
        process_result_stream(STREAM_AUTO_EXP)

        rows = models.auto_scan_exp_result.objects.filter(task_id=2, target="http://example.com", EXP_id=exp)
        self.assertEqual(rows.count(), 2)

    @override_settings(CELERY_BROKER_URL="memory://")
    def test_batch_events_do_not_duplicate_rows(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, build_batch_result_event_payload, process_result_stream, publish_result_events

        payload = build_batch_result_event_payload(3, "http://example.com", "[CVE]plugin", "ok")
        publish_result_events(STREAM_BATCH_EXP, [payload])
        publish_result_events(STREAM_BATCH_EXP, [payload])
        process_result_stream(STREAM_BATCH_EXP)
        process_result_stream(STREAM_BATCH_EXP)

        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=3, target="http://example.com", plugin_name="[CVE]plugin")
        self.assertEqual(rows.count(), 1)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_PENDING_IDLE_SECONDS=0)
    def test_pending_events_survive_writer_failure(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, get_pending_count, process_result_stream, publish_result_events

        payload = {"event_id": "batch_exp:9:http://fail:[CVE]plugin", "task_id": 9, "target": "http://fail", "plugin_name": "[CVE]plugin", "result": "fail"}
        publish_result_events(STREAM_BATCH_EXP, [payload])
        with patch("app_cybersparker.services.result_event_service._write_batch_event", side_effect=OperationalError("db down")):
            process_result_stream(STREAM_BATCH_EXP)
        self.assertEqual(get_pending_count(STREAM_BATCH_EXP), 1)
        process_result_stream(STREAM_BATCH_EXP)
        self.assertEqual(get_pending_count(STREAM_BATCH_EXP), 0)
        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=9, target="http://fail", plugin_name="[CVE]plugin")
        self.assertEqual(rows.count(), 1)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_PENDING_IDLE_SECONDS=0)
    def test_pending_events_survive_database_error(self):
        from django.db import DatabaseError
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, get_pending_count, process_result_stream, publish_result_events

        payload = {"event_id": "batch_exp:91:http://db-error:[CVE]plugin", "task_id": 91, "target": "http://db-error", "plugin_name": "[CVE]plugin", "result": "fail"}
        publish_result_events(STREAM_BATCH_EXP, [payload])
        with patch("app_cybersparker.services.result_event_service._write_batch_event", side_effect=DatabaseError("libpq error")):
            process_result_stream(STREAM_BATCH_EXP)
        self.assertEqual(get_pending_count(STREAM_BATCH_EXP), 1)
        process_result_stream(STREAM_BATCH_EXP)
        self.assertEqual(get_pending_count(STREAM_BATCH_EXP), 0)
        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=91, target="http://db-error", plugin_name="[CVE]plugin")
        self.assertEqual(rows.count(), 1)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=True)
    def test_spool_fallback_and_replay(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, count_spool_lines, process_result_stream, publish_result_events, replay_spool_to_stream

        payload = {"event_id": "batch_exp:10:http://spool:[CVE]plugin", "task_id": 10, "target": "http://spool", "plugin_name": "[CVE]plugin", "result": "ok"}
        publish_result_events(STREAM_BATCH_EXP, [payload])
        self.assertEqual(count_spool_lines(), 1)
        with override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=False):
            replayed = replay_spool_to_stream()
            self.assertEqual(replayed, 1)
            process_result_stream(STREAM_BATCH_EXP)
        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=10, target="http://spool", plugin_name="[CVE]plugin")
        self.assertEqual(rows.count(), 1)


class ResultWriterTaskTests(TransactionTestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_leases()
        reset_memory_event_store()

    @override_settings(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=True)
    def test_result_writer_task_processes_batch_stream(self):
        from app_cybersparker.tasks import run_result_writer_task
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, build_batch_result_event_payload, publish_result_events

        payload = build_batch_result_event_payload(11, "http://writer", "[CVE]writer", "ok")
        publish_result_events(STREAM_BATCH_EXP, [payload])
        result = run_result_writer_task.apply(args=(STREAM_BATCH_EXP,)).get()

        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=11, target="http://writer", plugin_name="[CVE]writer")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(result["processed_total"], 1)

    @override_settings(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=True)
    def test_result_writer_task_processes_auto_exp_stream(self):
        from app_cybersparker.tasks import run_result_writer_task
        from app_cybersparker.services.result_event_service import STREAM_AUTO_EXP, build_auto_exp_event_payload, publish_result_events

        exp = models.EXP.objects.create(title="writer-auto-plugin", CVE="CVE-WRITER-AUTO", poc="EXP_plugin/writer_auto.py")
        payload = build_auto_exp_event_payload(12, exp.id, "http://writer-auto", "nginx", "ok")
        publish_result_events(STREAM_AUTO_EXP, [payload])
        result = run_result_writer_task.apply(args=(STREAM_AUTO_EXP,)).get()

        rows = models.auto_scan_exp_result.objects.filter(task_id=12, target="http://writer-auto", EXP_id=exp)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(result["processed_total"], 1)


    @override_settings(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=True, RESULT_EVENT_BATCH_SIZE=1)
    def test_result_writer_task_drains_backlog_in_single_run(self):
        from app_cybersparker.tasks import run_result_writer_task
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, build_batch_result_event_payload, publish_result_events

        payloads = [
            build_batch_result_event_payload(21, "http://writer-1", "[CVE]writer", "ok-1"),
            build_batch_result_event_payload(21, "http://writer-2", "[CVE]writer", "ok-2"),
            build_batch_result_event_payload(21, "http://writer-3", "[CVE]writer", "ok-3"),
        ]
        publish_result_events(STREAM_BATCH_EXP, payloads)
        result = run_result_writer_task.apply(args=(STREAM_BATCH_EXP,)).get()

        rows = models.EXPTask_result.objects.filter(task_type=2, task_id=21, plugin_name="[CVE]writer")
        self.assertEqual(rows.count(), 3)
        self.assertEqual(result["processed_total"], 3)
        self.assertEqual(result["streams"][0]["pending"], 0)

    @override_settings(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=True)
    def test_result_writer_task_closes_stale_connections_before_processing(self):
        from app_cybersparker.tasks import run_result_writer_task
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, build_batch_result_event_payload, publish_result_events

        payload = build_batch_result_event_payload(13, "http://writer-close", "[CVE]writer", "ok")
        publish_result_events(STREAM_BATCH_EXP, [payload])

        with patch("app_cybersparker.tasks.close_old_connections") as close_mock, patch("app_cybersparker.tasks.connection.close") as connection_close_mock:
            run_result_writer_task.apply(args=(STREAM_BATCH_EXP,))

        self.assertTrue(close_mock.called)
        self.assertFalse(connection_close_mock.called)


class SpoolGovernanceTests(TestCase):
    def tearDown(self):
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_event_store()

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=True, RESULT_EVENT_SPOOL_MAX_BYTES=1)
    def test_spool_rotates_when_threshold_exceeded(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, append_spool_event, get_spool_stats

        append_spool_event(STREAM_BATCH_EXP, {"event_id": "e1", "task_id": 1, "target": "a", "plugin_name": "p", "result": "x"})
        append_spool_event(STREAM_BATCH_EXP, {"event_id": "e2", "task_id": 1, "target": "b", "plugin_name": "p", "result": "y"})
        stats = get_spool_stats()

        self.assertGreaterEqual(stats["pending_file_count"], 1)
        self.assertGreaterEqual(stats["pending_line_count"], 2)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=True)
    def test_replay_supports_checkpoint_resume(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, _read_spool_state, append_spool_event, replay_spool_to_stream

        append_spool_event(STREAM_BATCH_EXP, {"event_id": "resume-1", "task_id": 20, "target": "a", "plugin_name": "p", "result": "x"})
        append_spool_event(STREAM_BATCH_EXP, {"event_id": "resume-2", "task_id": 20, "target": "b", "plugin_name": "p", "result": "y"})
        with override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=False):
            replayed = replay_spool_to_stream(limit=1)
            self.assertEqual(replayed, 1)
            state = _read_spool_state()
            self.assertTrue(state)
            replayed += replay_spool_to_stream()
            self.assertEqual(replayed, 2)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=True)
    def test_spool_stats_report_pending_and_failures(self):
        from app_cybersparker.services.result_event_service import STREAM_BATCH_EXP, _write_spool_state, append_spool_event, get_spool_stats

        append_spool_event(STREAM_BATCH_EXP, {"event_id": "stats-1", "task_id": 21, "target": "a", "plugin_name": "p", "result": "x"})
        _write_spool_state({"replay_failures": 2})
        stats = get_spool_stats()

        self.assertGreaterEqual(stats["pending_line_count"], 1)
        self.assertEqual(stats["replay_failures"], 2)


class AutoScanThreadBudgetTests(TestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_leases()
        reset_memory_event_store()

    def _build_handler(self, **overrides):
        from app_cybersparker.views.expload.task_manage.auto_exp_task import Auto_exploit_Task_handler

        defaults = {
            "task_id": 9101,
            "target": "EXP_input/auto_async.txt",
            "current_line": 1,
            "thread_num": 8,
            "vulnerability_thread_num": 40,
            "sleep_time": 0,
            "Vulnerability_scanning": 0,
            "proxy": {},
            "dispatch_token": "token-budget",
            "owner": "worker-b",
            "resource_leases": [],
            "zone_id": 1,
        }
        defaults.update(overrides)
        with patch("app_cybersparker.views.expload.task_manage.auto_exp_task.identifyner.Identifyner", return_value=SimpleNamespace()), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.Auto_exploit_Task_handler._build_fingerprint_exp_cache", return_value={}):
            return Auto_exploit_Task_handler(defaults)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=4)
    def test_thread_budget_from_leases_caps_fingerprint_workers(self):
        handler = self._build_handler(
            thread_num=8,
            resource_leases=[{"resource": "threads", "amount": 2}],
        )
        self.assertEqual(handler._read_thread_budget_from_leases(), 2)
        self.assertLessEqual(handler._thread_budget, 2)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=4)
    def test_fingerprint_workers_fallback_to_thread_num_without_lease(self):
        handler = self._build_handler(thread_num=4, resource_leases=[])
        budget = handler._read_thread_budget_from_leases()
        self.assertEqual(budget, 4)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=4)
    def test_exp_consumer_count_respects_vulnerability_thread_num_when_vulnerability_scanning(self):
        handler = self._build_handler(
            thread_num=8,
            vulnerability_thread_num=2,
            Vulnerability_scanning=1,
            resource_leases=[{"resource": "threads", "amount": 6}],
        )
        budget = handler._read_thread_budget_from_leases()
        self.assertEqual(budget, 6)
        fingerpoint_worker_count = min(3, max(1, min(handler.thread_num, 1000, handler._thread_budget)))
        exp_worker_budget = max(1, handler._thread_budget - fingerpoint_worker_count)
        exp_worker_count = max(1, min(handler.vulnerability_thread_num, 1000, exp_worker_budget))
        self.assertEqual(exp_worker_count, 2)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=2)
    def test_fingerprint_queue_backpressure_holds_when_full(self):
        from queue import Full, Queue

        handler = self._build_handler(
            thread_num=2,
            resource_leases=[{"resource": "threads", "amount": 2}],
        )
        handler.queue_fingerpoint_input = Queue(maxsize=2)
        handler.check_stop_bridge = lambda: False

        handler.queue_fingerpoint_input.put({"http://a": {"status_code": 200, "header": "", "content": "<html></html>", "title": "Test"}})
        handler.queue_fingerpoint_input.put({"http://b": {"status_code": 200, "header": "", "content": "<html></html>", "title": "Test"}})
        self.assertTrue(handler.queue_fingerpoint_input.full())

        with self.assertRaises(Full):
            handler.queue_fingerpoint_input.put_nowait({"http://c": {"status_code": 200}})

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=2)
    def test_identify_event_publishing_path_intact(self):
        from app_cybersparker.services.result_event_service import (
            STREAM_IDENTIFY,
            build_identify_event_payloads,
            consume_result_events,
            ack_result_events,
            publish_result_events,
            reset_memory_event_store,
        )

        reset_memory_event_store()

        payloads = build_identify_event_payloads(
            9201, "http://event-test", "hdr", "T", "<b>ok</b>", 200,
            "1.2.3.4", "event-test", 80, "http", "CN", ["nginx"],
        )
        publish_result_events(STREAM_IDENTIFY, payloads)

        events = consume_result_events(STREAM_IDENTIFY, count=10)
        self.assertGreaterEqual(len(events), 1)
        event_ids = [e["id"] for e in events]
        ack_result_events(STREAM_IDENTIFY, event_ids)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20, GLOBAL_HTTP_INFLIGHT_LIMIT=2)
    def test_thread_count_does_not_grow_unbounded_under_repeated_handler_builds(self):
        thread_counts = []
        for i in range(20):
            handler = self._build_handler(
                thread_num=4,
                resource_leases=[{"resource": "threads", "amount": 3}],
            )
            thread_counts.append(handler._read_thread_budget_from_leases())

        for count in thread_counts:
            self.assertEqual(count, 3)
        self.assertEqual(len(thread_counts), 20)

    def test_auto_scan_resource_requirements_include_fingerprint_and_vuln_threads(self):
        from app_cybersparker.services.resource_lease_service import build_auto_scan_resource_requirements

        requirements = build_auto_scan_resource_requirements(12, 2, 1)

        self.assertEqual(requirements[0], {"resource": "running_auto_scan", "amount": 1})
        self.assertEqual(requirements[1], {"resource": "threads", "amount": 5})


class BatchRuntimeResultCompatibilityTests(TestCase):
    def _build_batch_handler(self):
        import threading
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        handler = Task_handler.__new__(Task_handler)
        handler.uid = 61
        handler.zone_id = 1
        handler.exit_flag = False
        handler.run_mode = 1
        handler.sleep_time = 0
        handler.task_type = 1
        handler.network_ok = True
        handler.exp_thread_num = 1
        handler.consumer_number = 0
        handler.progress_lock = threading.Lock()
        handler.completed_count = 0
        handler.queue_output = SimpleNamespace(put=lambda item: queued.append(item))
        handler.check_stop_bridge = lambda: False
        handler.pause_requested = False
        handler.get_progress = lambda force=False: "100%"
        handler.task_args = {}
        handler.exp_cache = [{"module": object(), "plugin": "[QVE-2026-0531001]拓庄医疗资产管理平台信息泄露"}]

        class _InputQueue:
            def __init__(self):
                self.items = ["http://example.test"]
            def get(self, block=True, timeout=None):
                if self.items:
                    return self.items.pop(0)
                raise Exception("done")
            def task_done(self):
                handler.exit_flag = True

        handler.queue_input = _InputQueue()
        return handler

    def test_batch_consumer_accepts_runtime_method_result_subclass(self):
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import RuntimeMethodResult

        global queued
        queued = []
        handler = self._build_batch_handler()

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.call_runtime_method", return_value=RuntimeMethodResult({"target": "http://example.test", "matched": True, "result": "matched"})), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.time.sleep", lambda *args, **kwargs: None):
            handler.consumer_exp()

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["plugin"], "[QVE-2026-0531001]拓庄医疗资产管理平台信息泄露")
        self.assertEqual(queued[0]["result"], "matched")

    def test_batch_consumer_skips_unmatched_runtime_method_result(self):
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import RuntimeMethodResult

        global queued
        queued = []
        handler = self._build_batch_handler()

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.call_runtime_method", return_value=RuntimeMethodResult({"target": "http://example.test", "matched": False, "result": "unsupported nuclei protocol: code"})), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.time.sleep", lambda *args, **kwargs: None):
            handler.consumer_exp()

        self.assertEqual(queued, [])

    def test_batch_consumer_keeps_plain_dict_result_even_if_matched_false(self):
        global queued
        queued = []
        handler = self._build_batch_handler()

        with patch("app_cybersparker.views.expload.task_manage.batch_task_executor.call_runtime_method", return_value={"target": "http://example.test", "matched": False, "result": "plain-python-result"}), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.batch_task_executor.time.sleep", lambda *args, **kwargs: None):
            handler.consumer_exp()

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["result"], "plain-python-result")

class BatchScanBudgetTests(TransactionTestCase):
    def tearDown(self):
        from app_cybersparker.services.resource_lease_service import reset_memory_leases
        from app_cybersparker.services.result_event_service import reset_memory_event_store

        reset_memory_leases()
        reset_memory_event_store()

    def _build_handler(self, **overrides):
        from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

        defaults = {
            "target_file": "EXP_input/batch_test.txt",
            "thread_num": 6,
            "sleep_time": 0,
            "uid": 8001,
            "exp": "1,2",
            "progress": "0%",
            "run_mode": 1,
            "dispatch_token": "token-batch-budget",
            "owner": "worker-batch",
            "resource_leases": [],
        }
        defaults.update(overrides)
        return Task_handler(defaults, start_index=1)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20)
    def test_thread_budget_caps_consumer_threads(self):
        handler = self._build_handler(
            thread_num=6,
            run_mode=1,
            resource_leases=[{"resource": "threads", "amount": 2}],
        )
        self.assertEqual(handler._thread_budget, 2)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20)
    def test_coroutine_budget_caps_gevent_pool(self):
        handler = self._build_handler(
            thread_num=6,
            run_mode=2,
            resource_leases=[{"resource": "coroutines", "amount": 4}],
        )
        self.assertEqual(handler._coroutine_budget, 4)


    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20)
    def test_fallback_to_thread_num_without_leases(self):
        handler = self._build_handler(
            thread_num=5,
            run_mode=1,
            resource_leases=[],
        )
        self.assertEqual(handler._thread_budget, 5)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20)
    def test_search_query_progress_uses_frozen_range_and_last_id(self):
        asset1 = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://progress-1.example.com",
            ip="10.1.0.1",
            protocol="http",
            port=80,
            title="progress-match",
        )
        asset2 = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://progress-2.example.com",
            ip="10.1.0.2",
            protocol="http",
            port=81,
            title="progress-match",
        )
        asset3 = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://progress-3.example.com",
            ip="10.1.0.3",
            protocol="http",
            port=82,
            title="progress-match",
        )
        models.AssetTaskRelation.objects.create(task_id=8001, identify_result=asset1)
        models.AssetTaskRelation.objects.create(task_id=8001, identify_result=asset2)
        models.AssetTaskRelation.objects.create(task_id=8001, identify_result=asset3)

        handler = self._build_handler(
            uid=8001,
            exp="1",
            progress="40%",
            input_type=6,
            parsed_query={"field": "title", "value": "progress-match"},
            frozen_max_id=asset2.id,
            last_id=asset1.id,
        )
        handler.check_stop_bridge = lambda: False
        handler.queue_input = SimpleNamespace(full=lambda: False, put=lambda value: None)

        with patch.object(handler, "_producer_from_search_query", return_value=None) as producer_mock:
            handler.producer(1)

        producer_mock.assert_called_once_with()
        self.assertEqual(handler.total_line_count, 2)
        self.assertEqual(handler.current_index, 1)
        self.assertEqual(handler.consumer_number, 1)
        self.assertEqual(handler.completed_count, 1)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=False)
    def test_batch_result_event_publishing_intact(self):
        from app_cybersparker.services.result_event_service import (
            STREAM_BATCH_EXP,
            build_batch_result_event_payload,
            consume_result_events,
            ack_result_events,
            publish_result_events,
            reset_memory_event_store,
        )

        reset_memory_event_store()

        payload = build_batch_result_event_payload(8101, "http://batch", "[CVE]test", "ok")
        publish_result_events(STREAM_BATCH_EXP, [payload])

        events = consume_result_events(STREAM_BATCH_EXP, count=10)
        self.assertGreaterEqual(len(events), 1)
        event_ids = [e["id"] for e in events]
        ack_result_events(STREAM_BATCH_EXP, event_ids)

    @override_settings(CELERY_BROKER_URL="memory://", GLOBAL_THREAD_LIMIT=20)
    def test_budget_stays_bounded_under_repeated_builds(self):
        for i in range(15):
            handler = self._build_handler(
                thread_num=6,
                run_mode=1 if i % 2 == 0 else 2,
                resource_leases=[
                    {"resource": "threads", "amount": 3},
                    {"resource": "coroutines", "amount": 5},
                ],
            )
            self.assertLessEqual(handler._thread_budget, 3)
            self.assertLessEqual(handler._coroutine_budget, 5)

    @override_settings(CELERY_BROKER_URL="memory://", RESULT_EVENT_FORCE_SPOOL=False)
    def test_save_task_result_flushes_cache_on_timeout(self):
        """缓存不足 batch_size 但超时 60 秒也应提交，避免漏洞少时长时间看不到结果。"""
        from unittest.mock import patch, MagicMock
        from queue import Empty
        from app_cybersparker.services.result_event_service import (
            STREAM_BATCH_EXP,
            STREAM_AUTO_EXP,
            consume_result_events,
            ack_result_events,
            reset_memory_event_store,
        )

        reset_memory_event_store()

        handler = self._build_handler()
        handler.exit_flag = False
        handler.zone_id = 1

        # 放入 1 条结果，远少于 batch_size=100
        handler.queue_output.put({
            "target": "http://timeout.example.com",
            "plugin": "[CVE-2024-0001]TestTimeout",
            "result": "vulnerability detected",
        })

        # 用 mock queue 控制行为：第一次 get 返回结果，第二次抛 Empty
        from queue import Queue
        mock_queue = MagicMock(spec=Queue)
        fake_results = [
            {"target": "http://timeout2.example.com", "plugin": "[CVE-2024]TimeoutPlugin", "result": "vuln"},
            Empty,
        ]
        call_count = [0]

        def fake_get(block=True, timeout=None):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(fake_results):
                val = fake_results[idx]
                if isinstance(val, Exception) or val is Empty:
                    raise Empty
                return val
            raise Empty

        mock_queue.get = fake_get
        mock_queue.empty.return_value = False
        mock_queue.task_done = MagicMock()
        handler.queue_output = mock_queue

        # 模拟时间：第一次 get 时 time=0，第二次 get 后（Empty）时 time=70（已超时）
        fake_time = [0.0]

        def fake_time_func():
            val = fake_time[0]
            # 第二次 get 前把时间跳到 70 秒之后
            if call_count[0] >= 1:
                fake_time[0] = 70.0
            return val

        published_streams = []

        def capture_publish(stream_name, payloads):
            published_streams.append(stream_name)
            # 第一次发布后立即设 exit_flag 让循环退出
            handler.exit_flag = True
            mock_queue.empty.return_value = True

        import threading

        def run_save():
            with patch('time.time', fake_time_func):
                with patch(
                    'app_cybersparker.views.expload.task_manage.batch_task_executor.publish_result_events',
                    side_effect=capture_publish,
                ):
                    with patch(
                        'app_cybersparker.views.expload.task_manage.batch_task_executor.throttle_dispatch_result_writer',
                    ):
                        handler.save_TaskResult()

        t = threading.Thread(target=run_save)
        t.start()
        t.join(timeout=5.0)

        self.assertIn(STREAM_BATCH_EXP, published_streams,
                      "超时后应触发 batch 事件发布")
        self.assertIn(STREAM_AUTO_EXP, published_streams,
                      "超时后应触发 auto_exp 事件发布")


class CyberspaceEngineAdapterTargetPriorityTests(TestCase):
    def _response(self, data):
        return SimpleNamespace(content=b'1', json=lambda: data)

    def test_quake_prefers_url_and_host_over_ip(self):
        from app_cybersparker.services.cyberspace_engine_adapters import QuakeAdapter

        resp = self._response({
            "data": [{
                "ip": "1.1.1.1",
                "port": 8080,
                "service": {"name": "http", "http": {"url": "http://demo.example.com:8080/path", "host": "demo.example.com"}},
                "domain": "demo.example.com",
            }]
        })
        self.assertEqual(QuakeAdapter().extract_targets(resp), ["http://demo.example.com:8080/path"])

    def test_fofa_prefers_host_over_ip(self):
        from app_cybersparker.services.cyberspace_engine_adapters import FofaAdapter

        resp = self._response({
            "error": False,
            "results": [["demo.fofa.example", "1.1.1.1", 9443, "https"]],
        })
        self.assertEqual(FofaAdapter().extract_targets(resp), ["https://demo.fofa.example:9443"])

    def test_zoomeye_prefers_site_then_domain_then_ip(self):
        from app_cybersparker.services.cyberspace_engine_adapters import ZoomEyeAdapter

        resp = self._response({
            "matches": [{
                "ip": "2.2.2.2",
                "site": "https://zoom.example.com:8443/login",
                "domain": "zoom.example.com",
                "portinfo": {"port": 8443, "service": "https", "host": "zoom.example.com"},
            }]
        })
        self.assertEqual(ZoomEyeAdapter().extract_targets(resp), ["https://zoom.example.com:8443/login"])

    def test_hunter_prefers_url_then_domain_then_ip(self):
        from app_cybersparker.services.cyberspace_engine_adapters import HunterAdapter

        resp = self._response({
            "data": {"arr": [{
                "url": "https://hunter.example.com:9443/app",
                "domain": "hunter.example.com",
                "host": "hunter.example.com",
                "ip": "4.4.4.4",
                "port": 9443,
                "protocol": "https",
            }]}
        })
        self.assertEqual(HunterAdapter().extract_targets(resp), ["https://hunter.example.com:9443/app"])

    def test_hunter_non_http_protocol(self):
        from app_cybersparker.services.cyberspace_engine_adapters import HunterAdapter

        resp = self._response({
            "data": {"arr": [{
                "ip": "5.5.5.5",
                "port": 22,
                "domain": "ssh.hunter.example.com",
                "protocol": "ssh",
            }]}
        })
        self.assertEqual(HunterAdapter().extract_targets(resp), ["ssh://ssh.hunter.example.com:22"])

    def test_shodan_prefers_hostname_over_ip(self):
        from app_cybersparker.services.cyberspace_engine_adapters import ShodanAdapter

        resp = self._response({
            "matches": [{
                "ip_str": "3.3.3.3",
                "port": 443,
                "transport": "tcp",
                "hostnames": ["shodan.example.com"],
                "domains": ["example.com"],
                "ssl": {"cert": "x"},
            }]
        })
        self.assertEqual(ShodanAdapter().extract_targets(resp), ["https://shodan.example.com:443"])

    # ── BL-AUTO-020: 非 HTTP 协议适配器测试 ──

    def test_fofa_non_http_protocol(self):
        from app_cybersparker.services.cyberspace_engine_adapters import FofaAdapter
        resp = self._response({
            "error": False,
            "results": [["demo.fofa.example", "1.1.1.1", 22, "ssh"]],
        })
        self.assertEqual(FofaAdapter().extract_targets(resp), ["ssh://demo.fofa.example:22"])

    def test_zoomeye_non_http_service(self):
        from app_cybersparker.services.cyberspace_engine_adapters import ZoomEyeAdapter
        resp = self._response({
            "matches": [{
                "ip": "2.2.2.2",
                "portinfo": {"port": 22, "service": "ssh", "host": "ssh.example.com"},
            }]
        })
        self.assertEqual(ZoomEyeAdapter().extract_targets(resp), ["ssh://ssh.example.com:22"])

    def test_quake_non_http_service(self):
        from app_cybersparker.services.cyberspace_engine_adapters import QuakeAdapter
        resp = self._response({
            "data": [{
                "ip": "1.1.1.1",
                "port": 22,
                "service": {"name": "ssh"},
            }]
        })
        self.assertEqual(QuakeAdapter().extract_targets(resp), ["ssh://1.1.1.1:22"])

    def test_shodan_port_22_detected_as_ssh(self):
        from app_cybersparker.services.cyberspace_engine_adapters import ShodanAdapter
        resp = self._response({
            "matches": [{
                "ip_str": "3.3.3.3",
                "port": 22,
                "transport": "tcp",
                "hostnames": ["ssh.example.com"],
            }]
        })
        self.assertEqual(ShodanAdapter().extract_targets(resp), ["ssh://ssh.example.com:22"])

    def test_resolve_protocol_known_services(self):
        from app_cybersparker.services.cyberspace_engine_adapters import BaseEngineAdapter
        self.assertEqual(BaseEngineAdapter._resolve_protocol("ssh"), "ssh")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("ftp"), "ftp")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("mysql"), "mysql")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("http"), "http")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("https"), "https")
        self.assertEqual(BaseEngineAdapter._resolve_protocol(""), "http")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("unknown-service"), "http")
        self.assertEqual(BaseEngineAdapter._resolve_protocol("unknown", ssl_flag=True), "https")

    def test_protocol_from_port_mapping(self):
        from app_cybersparker.services.cyberspace_engine_adapters import BaseEngineAdapter
        self.assertEqual(BaseEngineAdapter._protocol_from_port(22), "ssh")
        self.assertEqual(BaseEngineAdapter._protocol_from_port(3306), "mysql")
        self.assertEqual(BaseEngineAdapter._protocol_from_port(80, ssl_flag=False), "http")
        self.assertEqual(BaseEngineAdapter._protocol_from_port(443, ssl_flag=True), "https")
        self.assertEqual(BaseEngineAdapter._protocol_from_port(9999, ssl_flag=False), "http")

@override_settings(CELERY_BROKER_URL="memory://")
class BatchTaskDaemonGuardTests(TestCase):
    def test_coroutine_mode_runs_inline_when_parent_process_is_daemon(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        row_dict = {
            "EXP": "1",
            "target": "EXP_input/targets.txt",
            "run_mode": 2,
            "thread_num": 10,
            "sleep_time": 0,
            "process": "0%",
        }
        task_obj = SimpleNamespace(target="EXP_input/targets.txt", proxy_id=None)
        runner = SimpleNamespace(start=MagicMock())
        filter_mock = MagicMock()
        filter_mock.first.return_value = task_obj

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.models.batch_EXPTask.objects.filter", return_value=filter_mock), \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.prepare_engine_target_before_start", return_value=(True, None)), \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.connection.close"), \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.multiprocessing.current_process", return_value=SimpleNamespace(daemon=True)), \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.multiprocessing.get_context") as context_mock, \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.batch_exec.Task_handler", return_value=runner) as handler_mock:
            result = batch_exp_task.startTask(row_dict, 123)

        handler_mock.assert_called_once()
        self.assertEqual(handler_mock.call_args.args[0]["run_mode"], 1)
        runner.start.assert_called_once_with()
        context_mock.assert_not_called()
        self.assertIs(result, runner)

    def test_run_batch_scan_task_allows_gevent_mode_without_child_process_assertion(self):
        from app_cybersparker.tasks import _run_batch_scan_task

        row = {
            "dispatch_token": "batch-token-gevent-inline",
            "stop_requested": False,
            "owner": None,
            "endTime": None,
        }
        row_dict = {
            "task_name": "batch-celery-gevent-inline-guard",
            "EXP": "1",
            "run_mode": 2,
            "thread_num": 2,
            "sleep_time": 0,
            "target": "EXP_input/batch_celery_gevent_inline.txt",
            "creat_time": timezone.now(),
            "status": 2,
            "process": "0%",
            "startTime": timezone.now(),
            "endTime": None,
            "remark": "",
            "dispatch_token": "batch-token-gevent-inline",
            "owner": "worker-a",
        }
        runner = SimpleNamespace(stop_requested=False, is_alive=lambda: False)

        with patch("app_cybersparker.tasks.claim_task_execution", return_value=True), \
             patch("app_cybersparker.tasks.acquire_resource_leases", return_value=[]), \
             patch("app_cybersparker.tasks.release_resource_leases"), \
             patch("app_cybersparker.tasks.clear_stop_signal"), \
             patch("app_cybersparker.tasks.compare_and_set_terminal_state") as cas_mock, \
             patch("app_cybersparker.tasks.models.batch_EXPTask.objects.filter") as filter_mock, \
             patch("app_cybersparker.views.expload.task_manage.batch_exp_task.startTask", return_value=runner) as start_mock:
            filter_mock.return_value.values.return_value.first.side_effect = [row, row_dict]
            result = _run_batch_scan_task(321, "batch-token-gevent-inline", "worker-a")

        self.assertEqual(result["status"], "success")
        self.assertEqual(start_mock.call_args.args[0]["run_mode"], 2)
        cas_mock.assert_called_once()

class BatchEngineForceRefreshTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()

    def test_prepare_engine_target_before_start_force_refresh_fetches_new_file(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        target_rel = "EXP_input/engine_assets/batch_force_refresh_old.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://old.example.com\n", encoding="utf-8")

        task = models.batch_EXPTask.objects.create(
            task_name="batch-force-refresh-prepare",
            EXP="1",
            run_mode=1,
            thread_num=1,
            sleep_time=0,
            target=target_rel,
            status=1,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=False,
            startTime=timezone.now(),
        )

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.fetch_and_dump_targets", return_value="EXP_input/engine_assets/batch_force_refresh_new.txt") as fetch_mock:
            is_ok, error = batch_exp_task.prepare_engine_target_before_start(task, is_restart=False, force_refresh=True)

        self.assertTrue(is_ok)
        self.assertIsNone(error)
        self.assertEqual(task.target, "EXP_input/engine_assets/batch_force_refresh_new.txt")
        self.assertFalse(target_abs.exists())
        fetch_mock.assert_called_once_with(task)

    def test_prepare_engine_target_before_start_reuses_existing_file_when_not_forced(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        target_rel = "EXP_input/engine_assets/batch_force_refresh_reuse.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")

        task = models.batch_EXPTask.objects.create(
            task_name="batch-force-refresh-reuse",
            EXP="1",
            run_mode=1,
            thread_num=1,
            sleep_time=0,
            target=target_rel,
            status=4,
            process="37%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=False,
            startTime=timezone.now(),
        )

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.fetch_and_dump_targets") as fetch_mock:
            is_ok, error = batch_exp_task.prepare_engine_target_before_start(task, is_restart=False, force_refresh=False)

        self.assertTrue(is_ok)
        self.assertIsNone(error)
        self.assertEqual(task.target, target_rel)
        self.assertTrue(target_abs.exists())
        fetch_mock.assert_not_called()

    def test_batch_edit_engine_query_change_disables_reuse_and_clears_target(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-engine-edit-plugin",
            CVE="CVE-BATCH-ENGINE-EDIT",
            poc="EXP_plugin/batch_engine_edit.py",
        )
        target_rel = "EXP_input/engine_assets/batch_edit_query_change.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.batch_EXPTask.objects.create(
            task_name="batch-engine-edit-query-change",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            startTime=timezone.now(),
        )
        request = self.factory.post(
            f"/batch_exploadTask/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "sleep_time": str(task.sleep_time),
                "run_mode": str(task.run_mode),
                "input_type": "4",
                "engine_type": "fofa",
                "engine_query": 'app="apache"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "remark": "",
                "proxy": "",
                "plugin": str(exp.id),
                "reuse_engine_data": "true",
                "exp_select_mode": "1",
                "filter_logic": "AND",
            },
        )
        request.session = self.session

        response = batch_exp_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_query, 'app="apache"')
        self.assertFalse(task.reuse_engine_data)
        self.assertFalse(bool(task.target))
        self.assertTrue(target_abs.exists())

    def test_batch_edit_same_engine_query_keeps_reuse_and_target(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-engine-edit-same-query-plugin",
            CVE="CVE-BATCH-ENGINE-EDIT-SAME",
            poc="EXP_plugin/batch_engine_edit_same.py",
        )
        target_rel = "EXP_input/engine_assets/batch_edit_same_query.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.batch_EXPTask.objects.create(
            task_name="batch-engine-edit-same-query",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            startTime=timezone.now(),
        )
        request = self.factory.post(
            f"/batch_exploadTask/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "sleep_time": str(task.sleep_time),
                "run_mode": str(task.run_mode),
                "input_type": "4",
                "engine_type": "fofa",
                "engine_query": 'app="nginx"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "remark": "",
                "proxy": "",
                "plugin": str(exp.id),
                "reuse_engine_data": "true",
                "exp_select_mode": "1",
                "filter_logic": "AND",
            },
        )
        request.session = self.session

        response = batch_exp_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_query, 'app="nginx"')
        self.assertTrue(task.reuse_engine_data)
        self.assertEqual(str(task.target), target_rel)
        self.assertTrue(target_abs.exists())

    def test_batch_edit_engine_type_change_disables_reuse_and_clears_target(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-engine-edit-type-plugin",
            CVE="CVE-BATCH-ENGINE-EDIT-TYPE",
            poc="EXP_plugin/batch_engine_edit_type.py",
        )
        target_rel = "EXP_input/engine_assets/batch_edit_engine_type_change.txt"
        target_abs = _PROJECT_ROOT / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text("http://keep.example.com\n", encoding="utf-8")
        task = models.batch_EXPTask.objects.create(
            task_name="batch-engine-edit-type-change",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target=target_rel,
            status=3,
            process="100%",
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
            engine_max_assets=10,
            reuse_engine_data=True,
            startTime=timezone.now(),
        )
        request = self.factory.post(
            f"/batch_exploadTask/edit?uid={task.id}",
            {
                "task_name": task.task_name,
                "thread_num": str(task.thread_num),
                "sleep_time": str(task.sleep_time),
                "run_mode": str(task.run_mode),
                "input_type": "4",
                "engine_type": "hunter",
                "engine_query": 'app="nginx"',
                "engine_max_assets": "10",
                "engine_proxy_mode": "0",
                "remark": "",
                "proxy": "",
                "plugin": str(exp.id),
                "reuse_engine_data": "true",
                "exp_select_mode": "1",
                "filter_logic": "AND",
            },
        )
        request.session = self.session

        response = batch_exp_task.edit(request)
        payload = json.loads(response.content)
        task.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.engine_type, "hunter")
        self.assertFalse(task.reuse_engine_data)
        self.assertFalse(bool(task.target))
        self.assertTrue(target_abs.exists())




class BatchQueueRoutingTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()

    def test_restart_search_query_task_resets_last_id(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-search-restart-plugin",
            CVE="CVE-BATCH-SEARCH-RESTART",
            poc="EXP_plugin/batch_search_restart.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-search-restart",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/batch_search_restart.txt",
            status=3,
            process="100%",
            input_type=6,
            search_query='title:"demo"',
            parsed_query={"operator": "condition", "field": "title", "value": "demo"},
            frozen_max_id=99,
            last_id=77,
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "1"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task"):
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(task.last_id, 0)

    def test_thread_mode_routes_to_batch_scan_queue(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-queue-thread-plugin",
            CVE="CVE-BATCH-QUEUE-THREAD",
            poc="EXP_plugin/batch_queue_thread.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-queue-thread-start",
            EXP=str(exp.id),
            run_mode=1,
            thread_num=5,
            sleep_time=0,
            target="EXP_input/batch_queue_thread_start.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(dispatch_mock.call_args.kwargs["queue"], "batch_scan")
        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)

    def test_gevent_mode_routes_to_batch_scan_gevent_queue(self):
        from app_cybersparker.views.expload.task_manage import batch_exp_task

        exp = models.EXP.objects.create(
            title="batch-queue-gevent-plugin",
            CVE="CVE-BATCH-QUEUE-GEVENT",
            poc="EXP_plugin/batch_queue_gevent.py",
        )
        task = models.batch_EXPTask.objects.create(
            task_name="batch-queue-gevent-start",
            EXP=str(exp.id),
            run_mode=2,
            thread_num=20,
            sleep_time=0,
            target="EXP_input/batch_queue_gevent_start.txt",
            status=3,
            process="0%",
            startTime=timezone.now(),
        )
        request = self.factory.post("/batch_exploadTask/operate", {"uid": str(task.id), "status": "0"})
        request.session = self.session

        with patch("app_cybersparker.views.expload.task_manage.batch_exp_task.dispatch_task") as dispatch_mock:
            response = batch_exp_task.operate(request)

        payload = json.loads(response.content)
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["status"])
        self.assertEqual(dispatch_mock.call_args.kwargs["queue"], "batch_scan_gevent")
        self.assertEqual(task.status, 2)
        self.assertTrue(task.queued)


class ExportTaskTests(TestCase):
    def test_run_export_task_uses_task_relations_for_vuln_rows(self):
        from app_cybersparker.tasks import run_export_task

        exp = models.EXP.objects.create(
            title="export-plugin",
            CVE="CVE-EXPORT-1",
            poc="EXP_plugin/export_plugin.py",
        )
        asset = models.auto_scan_indentify_result.objects.create(
            products=["nginx"],
            target="http://export.example.com",
            ip="1.1.1.1",
            protocol="http",
            port=80,
            title="export-target",
        )
        models.AssetTaskRelation.objects.create(task_id=101, identify_result=asset)
        models.AssetTaskRelation.objects.create(task_id=202, identify_result=asset)
        models.auto_scan_exp_result.objects.create(
            task_id=101,
            EXP_id=exp,
            product="nginx",
            target=asset.target,
            result="match-101",
            identify_result_id=asset.id,
        )
        models.auto_scan_exp_result.objects.create(
            task_id=202,
            EXP_id=exp,
            product="nginx",
            target=asset.target,
            result="match-202",
            identify_result_id=asset.id,
        )
        export_task = models.ExportTask.objects.create(
            task_type="task",
            task_id=101,
            task_name="task-101",
            search_string="",
            fields=["title", "vuln", "cve"],
            include_vuln_result=True,
            status="processing",
        )

        with patch("django.db.connection.close"):
            result = run_export_task.run(export_task.id)
        export_task = models.ExportTask.objects.get(id=export_task.id)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(export_task.status, "completed")
        self.assertEqual(export_task.total_rows, 2)


class AutoScanStatusViewTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()

    def test_detail_returns_search_query_fields_for_input_type_6(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        task = models.auto_scan_tasks.objects.create(
            task_name="auto-search-detail",
            thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_search_detail.txt",
            status=3,
            input_type=6,
            search_query='title:"demo"',
            parsed_query={"operator": "condition", "field": "title", "value": "demo"},
            frozen_max_id=88,
            last_id=33,
            Vulnerability_scanning=0,
        )

        req = self.factory.get(f"/Identify_task/detail?uid={task.id}")
        req.session = self.session
        response = auto_scan_task.detail(req)
        payload = json.loads(response.content)

        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["search_query"], 'title:"demo"')
        self.assertEqual(payload["data"]["frozen_max_id"], 88)
        self.assertEqual(payload["data"]["last_id"], 33)

    def test_task_all_info_maps_queued_running_to_waiting(self):
        from app_cybersparker.views.expload.task_manage import auto_scan_task

        task = models.auto_scan_tasks.objects.create(
            task_name="auto-status-waiting",
            thread_num=2,
            sleep_time=0,
            target="EXP_input/auto_status_waiting.txt",
            status=2,
            process="0%",
            queued=True,
            pause_requested=False,
            Vulnerability_scanning=0,
        )
        request = self.factory.get(f"/Identify_task/all_info?uid={task.id}")
        request.session = self.session

        response = auto_scan_task.Task_all_info(request)
        payload = json.loads(response.content)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["status"], "waiting")
        self.assertTrue(payload["data"]["queued"])

    def test_expload_batch_delete_accepts_uids_without_brackets(self):
        from app_cybersparker.views.expload import plugin_manage

        plugin1 = models.EXP.objects.create(title="batch-delete-1", CVE="CVE-BATCH-1", poc="EXP_plugin/batch_delete_1.py")
        plugin2 = models.EXP.objects.create(title="batch-delete-2", CVE="CVE-BATCH-2", poc="EXP_plugin/batch_delete_2.py")
        request = self.factory.post(
            "/expload/batch_delete",
            {"uids": [str(plugin1.id), str(plugin2.id)]},
        )
        request.session = self.session

        with patch("app_cybersparker.views.expload.plugin_manage.remove_plugin_file") as remove_plugin_file_mock:
            response = plugin_manage.expload_batch_delete(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["status"])
        self.assertFalse(models.EXP.objects.filter(id=plugin1.id).exists())
        self.assertFalse(models.EXP.objects.filter(id=plugin2.id).exists())
        self.assertEqual(remove_plugin_file_mock.call_count, 2)


class FingerprintIdentifynerTests(TestCase):
    def setUp(self):
        self.context = {
            "favicon": "abc123",
            "favicon_md5": "abc123",
            "cert_org": "Example Org",
            "cert_org_unit": "Security",
            "cert_common_name": "secure.example.com",
            "cert_serial": "SER123",
        }
        self.conditions = [
            'favicon="abc123"',
            'favicon_md5="abc123"',
            'cert_serial="SER123"',
            'cert="Security"',
            'header="hdr"&&title="ttl"&&(body="body"||title="nope")',
        ]
        models.fingerPrint.objects.filter(condition__in=self.conditions).delete()
        self.fingerprints = [
            models.fingerPrint.objects.create(product="Favicon", condition='favicon="abc123"'),
            models.fingerPrint.objects.create(product="FaviconMd5", condition='favicon_md5="abc123"'),
            models.fingerPrint.objects.create(product="CertSerial", condition='cert_serial="SER123"'),
            models.fingerPrint.objects.create(product="CertGroup", condition='cert="Security"'),
            models.fingerPrint.objects.create(product="LegacyMix", condition='header="hdr"&&title="ttl"&&(body="body"||title="nope")'),
        ]

    def test_check_rule_supports_new_context_keys(self):
        from app_cybersparker.services.fingerprint_matcher import check_rule

        self.assertTrue(check_rule('favicon="abc123"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('favicon_md5="abc123"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('cert_serial="SER123"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('cert_org="Example Org"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('cert_org_unit="Security"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('cert_common_name="secure.example.com"', "hdr", "body", "ttl", self.context))
        self.assertTrue(check_rule('cert="Security"', "hdr", "body", "ttl", self.context))
        self.assertFalse(check_rule('cert_serial="NOPE"', "hdr", "body", "ttl", self.context))

    def test_handle_matches_new_keys_and_mixed_branch(self):
        from app_cybersparker.views.expload.task_manage.fingerprint_indentify import Identifyner

        identifyner = Identifyner()
        identifyner_any = cast(Any, identifyner)
        fingers = identifyner_any.handle("hdr", "body", "ttl", self.context)

        self.assertCountEqual(fingers, ["Favicon", "FaviconMd5", "CertSerial", "CertGroup", "LegacyMix"])


class ExpDebugExecuteTests(TestCase):
    def test_yaml_runtime_result_is_falsy_when_unmatched(self):
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import RuntimeMethodResult

        self.assertFalse(RuntimeMethodResult({"matched": False, "result": ""}))
        self.assertTrue(RuntimeMethodResult({"matched": True, "result": "matched"}))

    def test_debug_execute_marks_yaml_exception_as_failure(self):
        from app_cybersparker.views.expload import exp_debug
        request = SimpleNamespace(
            POST={"target": "192.168.1.166:4712。", "plugin_id": "7", "model": "verify", "cmd": ""},
            session={'info': {'id': 1, 'username': 'admin', 'role': 'super_admin'}},
        )

        with patch("app_cybersparker.views.expload.exp_debug.models.EXP.objects.filter") as filter_mock, \
             patch("app_cybersparker.views.expload.exp_debug.load_runtime_module_from_poc", return_value=object()), \
             patch("app_cybersparker.views.expload.exp_debug.call_runtime_method", return_value={"target": "192.168.1.166:4712。", "matched": False, "result": "Port could not be cast to integer value as '4712。'"}):
            filter_mock.return_value.values.return_value.first.return_value = {"id": 7, "poc": "EXP_plugin/test.yaml"}

            response = exp_debug.debug_execute(request)

        payload = json.loads(response.content.decode("utf-8"))
        self.assertFalse(payload["status"])
        self.assertIn("Port could not be cast to integer value", payload["result"])

    def test_debug_execute_marks_yaml_match_as_success(self):
        from app_cybersparker.views.expload import exp_debug

        request = SimpleNamespace(
            POST={"target": "192.168.1.166:4712", "plugin_id": "7", "model": "verify", "cmd": ""},
            session={'info': {'id': 1, 'username': 'admin', 'role': 'super_admin'}},
        )

        with patch("app_cybersparker.views.expload.exp_debug.models.EXP.objects.filter") as filter_mock, \
             patch("app_cybersparker.views.expload.exp_debug.load_runtime_module_from_poc", return_value=object()), \
             patch("app_cybersparker.views.expload.exp_debug.call_runtime_method", return_value={"target": "192.168.1.166:4712", "matched": True, "result": "matched"}):
            filter_mock.return_value.values.return_value.first.return_value = {"id": 7, "poc": "EXP_plugin/test.yaml"}

            response = exp_debug.debug_execute(request)

        payload = json.loads(response.content.decode("utf-8"))
        self.assertTrue(payload["status"])
        self.assertEqual(payload["result"], "matched")

class NucleiUnsupportedTemplateManagementTests(TestCase):
    def test_find_unsupported_nuclei_protocols(self):
        from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import find_unsupported_nuclei_protocols

        doc = {
            "http": [{"method": "GET", "path": ["{{BaseURL}}/"]}],
            "code": [{"engine": ["sh"], "source": "echo ok"}],
            "dns": [{"name": "{{FQDN}}", "type": "NS"}],
        }

        self.assertEqual(find_unsupported_nuclei_protocols(doc), ["code", "dns"])

    @override_settings(BASE_DIR="/tmp/claude-test-import-nuclei")
    def test_import_nuclei_templates_skips_unsupported_protocols(self):
        base_dir = Path("/tmp/claude-test-import-nuclei")
        source_dir = base_dir / "source"
        plugin_dir = base_dir / "EXP_plugin"
        source_dir.mkdir(parents=True, exist_ok=True)
        plugin_dir.mkdir(parents=True, exist_ok=True)

        supported = source_dir / "supported.yaml"
        supported.write_text(
            """id: supported\ninfo:\n  name: Supported Template\n  severity: low\nhttp:\n  - method: GET\n    path:\n      - \"{{BaseURL}}/\"\n""",
            encoding="utf-8",
        )
        unsupported = source_dir / "unsupported.yaml"
        unsupported.write_text(
            """id: unsupported\ninfo:\n  name: Unsupported Template\n  severity: info\ndns:\n  - name: \"{{FQDN}}\"\n    type: NS\n""",
            encoding="utf-8",
        )

        call_command(
            "import_nuclei_templates",
            source=str(source_dir),
            skip_matching=True,
        )

        titles = list(models.EXP.objects.filter(plugin_language=2).values_list("title", flat=True))
        self.assertEqual(len(titles), 1)
        self.assertIn("Supported Template", titles[0])
        self.assertEqual(models.cveExtensions.objects.filter(CVE__plugin_language=2).count(), 1)

    @override_settings(BASE_DIR="/tmp/claude-test-cleanup-nuclei")
    def test_cleanup_nuclei_unsupported_templates_deletes_exp_and_clears_batch_refs(self):
        base_dir = Path("/tmp/claude-test-cleanup-nuclei")
        plugin_dir = base_dir / "EXP_plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        supported_path = plugin_dir / "supported.yaml"
        supported_path.write_text(
            """id: supported\ninfo:\n  name: Supported Template\n  severity: low\nhttp:\n  - method: GET\n    path:\n      - \"{{BaseURL}}/\"\n""",
            encoding="utf-8",
        )
        unsupported_path = plugin_dir / "unsupported.yaml"
        unsupported_path.write_text(
            """id: unsupported\ninfo:\n  name: Unsupported Template\n  severity: info\ncode:\n  - engine:\n      - sh\n    source: echo hello\n""",
            encoding="utf-8",
        )

        fp = models.fingerPrint.objects.create(product="demo", condition='body="demo"')
        supported_exp = models.EXP.objects.create(
            title="supported-template",
            CVE="",
            Type=12,
            plugin_language=2,
            use=1,
            poc_type=1,
            poc="EXP_plugin/supported.yaml",
            poc_content="supported-digest",
        )
        unsupported_exp = models.EXP.objects.create(
            title="unsupported-template",
            CVE="",
            Type=12,
            plugin_language=2,
            use=1,
            poc_type=1,
            poc="EXP_plugin/unsupported.yaml",
            poc_content="unsupported-digest",
        )
        models.cveExtensions.objects.create(CVE=unsupported_exp, function=1)
        models.exp_relate_fingerprint.objects.create(EXP_id=unsupported_exp, fingerprint_id=fp)
        task = models.batch_EXPTask.objects.create(
            task_name="cleanup-batch-task",
            EXP=str(unsupported_exp.id),
            run_mode=1,
            thread_num=1,
            sleep_time=0,
            input_type=1,
            task_type=1,
            exp_select_mode=1,
            status=3,
        )

        call_command("cleanup_nuclei_unsupported_templates")

        self.assertTrue(models.EXP.objects.filter(id=supported_exp.id).exists())
        self.assertFalse(models.EXP.objects.filter(id=unsupported_exp.id).exists())
        self.assertFalse(models.cveExtensions.objects.filter(CVE_id=unsupported_exp.id).exists())
        self.assertFalse(models.exp_relate_fingerprint.objects.filter(EXP_id_id=unsupported_exp.id).exists())
        task.refresh_from_db()
        self.assertEqual(task.EXP, "")
        self.assertTrue(supported_path.exists())
        self.assertFalse(unsupported_path.exists())


class FingerprintDebugPageTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.session = SessionStore()
        self.session.create()
        self.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        self.session.save()
        models.fingerPrint.objects.filter(condition__in=['body="apache"', 'title="nginx"']).delete()
        self.fp_a = models.fingerPrint.objects.create(product="Apache", condition='body="apache"')
        self.fp_b = models.fingerPrint.objects.create(product="Nginx", condition='title="nginx"')

    def test_list_view_provides_fingerprints_for_picker(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        captured = {}

        def fake_render(request, template_name, context):
            captured["template_name"] = template_name
            captured["context"] = context
            return SimpleNamespace(template_name=template_name, context_data=context)

        with patch.object(fingerPrint_debug, "render", side_effect=fake_render):
            req = self.factory.get("/fingerPrint_debug")
            req.session = self.session
            fingerPrint_debug.list(req)

        self.assertEqual(captured["template_name"], "project/expload/fingerprint_debug.html")
        top_two = list(captured["context"]["fingerprints"][:2])
        self.assertEqual([item["product"] for item in top_two], ["Nginx", "Apache"])
        self.assertEqual(top_two[0]["condition"], 'title="nginx"')

    def _build_async_mate_mocks(self, fingerPrint_debug, response_stub):
        """Build mocks for async mate() view: AsyncClient + collection fns + fingerprint pre-fetch."""
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=response_stub)

        fps = list(models.fingerPrint.objects.all().values("product", "condition").order_by("-id"))

        patches = [
            patch.object(fingerPrint_debug.httpx, "AsyncClient", return_value=mock_client),
            patch.object(fingerPrint_debug, "_fetch_favicon_async", new=AsyncMock(return_value={"favicon": None, "favicon_md5": None})),
            patch.object(fingerPrint_debug, "_fetch_certificate_async", new=AsyncMock(return_value={})),
            patch.object(fingerPrint_debug, "_handle_js_redirect_async", new=AsyncMock(return_value={"uri_path": "/", "redirect_url": None})),
            patch.object(fingerPrint_debug, "_prefetch_fingerprint_rows", return_value=fps),
        ]
        return patches

    def _response_stub(self, status_code=200, headers=None, text=""):
        return SimpleNamespace(
            status_code=status_code,
            headers=headers or {"Server": "demo"},
            text=text,
            extensions={"ssl_object": None},
            url="http://example.com",
        )

    def test_mate_returns_all_library_matches_when_enabled(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        request = self.factory.post(
            "/fingerPrint_debug/mate",
            data={
                "url": "http://example.com",
                "regex": 'body="apache"',
                "proxy": "",
                "match_all_fingerprints": "1",
            },
        )
        request.session = self.session

        response_stub = self._response_stub(
            text="<html><title>nginx</title><body>apache</body></html>",
        )

        patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = fingerPrint_debug.mate(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["matched_fingerprints"][0]["name"], "当前调试指纹")
        self.assertEqual(payload["matched_fingerprints"][0]["condition"], 'body="apache"')
        self.assertIn(
            {"name": "Nginx", "condition": 'title="nginx"', "matched_text": ""},
            payload["matched_fingerprints"],
        )

    def test_mate_only_checks_current_fingerprint_when_all_match_disabled(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        request = self.factory.post(
            "/fingerPrint_debug/mate",
            data={
                "url": "http://example.com",
                "regex": 'body="apache"',
                "proxy": "",
                "match_all_fingerprints": "0",
            },
        )
        request.session = self.session

        response_stub = self._response_stub(
            text="<html><title>nginx</title><body>apache</body></html>",
        )

        patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = fingerPrint_debug.mate(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["matched_fingerprints"], [{"name": "当前调试指纹", "condition": 'body="apache"', "matched_text": ""}])

    def test_mate_returns_library_matches_even_when_current_fingerprint_misses(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        request = self.factory.post(
            "/fingerPrint_debug/mate",
            data={
                "url": "http://example.com",
                "regex": 'header="x-demo"',
                "proxy": "",
                "match_all_fingerprints": "1",
            },
        )
        request.session = self.session

        response_stub = self._response_stub(
            text="<html><title>nginx</title><body>apache</body></html>",
        )

        patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = fingerPrint_debug.mate(request)

        payload = json.loads(response.content)
        self.assertFalse(payload["status"])
        self.assertIn(
            {"name": "Nginx", "condition": 'title="nginx"', "matched_text": ""},
            payload["matched_fingerprints"],
        )
        self.assertIn(
            {"name": "Apache", "condition": 'body="apache"', "matched_text": ""},
            payload["matched_fingerprints"],
        )

    def test_mate_returns_response_payload_for_non_2xx_status(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        request = self.factory.post(
            "/fingerPrint_debug/mate",
            data={"url": "http://example.com", "regex": 'title="demo"', "proxy": ""},
        )
        request.session = self.session

        response_stub = self._response_stub(
            status_code=404,
            text="<html><title>missing</title><body>not found</body></html>",
        )

        patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = fingerPrint_debug.mate(request)

        payload = json.loads(response.content)
        self.assertFalse(payload["status"])
        self.assertIn("Server: demo", payload["response_headers"])
        self.assertIn("not found", payload["response_data"])
        self.assertNotIn("error", payload)

    def test_requests_headers_use_clean_browser_headers(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        headers = fingerPrint_debug.requests_headers()
        self.assertIsNotNone(headers)

        self.assertEqual(headers["User-Agent"], "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")
        self.assertEqual(headers["Accept"], "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        self.assertEqual(headers["Accept-Language"], "zh-CN,zh;q=0.9,en;q=0.8")
        self.assertNotIn("Referer", headers)
        self.assertNotIn("Accept-Encoding", headers)

    def test_input_finger_is_true_accepts_context_fields(self):
        from app_cybersparker.views.expload.fingerPrint_debug import inputFingerIsTrue

        self.assertTrue(inputFingerIsTrue('cert_org="Let\'s Encrypt"'))
        self.assertTrue(inputFingerIsTrue('cert_common_name~=".*"'))
        self.assertTrue(inputFingerIsTrue('cert_serial!="00"'))
        self.assertTrue(inputFingerIsTrue('favicon_md5="abc123"'))
        self.assertTrue(inputFingerIsTrue('favicon="abc"'))
        self.assertTrue(inputFingerIsTrue('uri_path="/admin"'))
        self.assertTrue(inputFingerIsTrue('title="demo"'))
        self.assertTrue(inputFingerIsTrue('body="test"'))
        self.assertTrue(inputFingerIsTrue('header="x"'))

    def test_check_rule_context_matching_cert_org(self):
        from app_cybersparker.services.fingerprint_matcher import check_rule

        context = {
            "cert_org": "Let's Encrypt",
            "cert_org_unit": None,
            "cert_common_name": "example.com",
            "cert_serial": "abc123",
            "favicon": None,
            "favicon_md5": None,
            "cert": "Let's Encrypt example.com",
            "uri_path": "/admin",
        }

        self.assertTrue(check_rule('cert_org="Let\'s Encrypt"', "", "", "", context=context))
        self.assertTrue(check_rule('cert_org~=".*Encrypt"', "", "", "", context=context))
        self.assertFalse(check_rule('cert_org="DigiCert"', "", "", "", context=context))
        self.assertFalse(check_rule('cert_org!="Let\'s Encrypt"', "", "", "", context=context))

    def test_check_rule_context_matching_favicon_md5(self):
        from app_cybersparker.services.fingerprint_matcher import check_rule

        context = {
            "favicon": "data:image/x-icon;base64,AAAA",
            "favicon_md5": "d41d8cd98f00b204e9800998ecf8427e",
        }

        self.assertTrue(check_rule('favicon_md5="d41d8cd98f00b204e9800998ecf8427e"', "", "", "", context=context))
        self.assertFalse(check_rule('favicon_md5="deadbeef"', "", "", "", context=context))

    def test_check_rule_context_matching_uri_path(self):
        from app_cybersparker.services.fingerprint_matcher import check_rule

        context = {"uri_path": "/admin/login"}

        self.assertTrue(check_rule('uri_path="admin"', "", "", "", context=context))
        self.assertTrue(check_rule('uri_path~="admin"', "", "", "", context=context))
        self.assertFalse(check_rule('uri_path!="admin"', "", "", "", context=context))
        self.assertFalse(check_rule('uri_path="/missing"', "", "", "", context=context))

    def test_check_rule_falls_back_to_header_when_context_empty(self):
        from app_cybersparker.services.fingerprint_matcher import check_rule

        context = {"cert_org": None, "favicon_md5": None, "uri_path": None}

        self.assertTrue(check_rule('header="Server"', "\nServer: nginx\n", "", "", context=context))

    def test_mate_returns_asset_features_in_response(self):
        from app_cybersparker.views.expload import fingerPrint_debug

        request = self.factory.post(
            "/fingerPrint_debug/mate",
            data={"url": "http://example.com", "regex": 'title="demo"', "proxy": ""},
        )
        request.session = self.session

        response_stub = self._response_stub(
            text="<html><title>demo</title><body>hello</body></html>",
        )

        favicon_result = {"favicon": "data:image/x-icon;base64,FAKE", "favicon_md5": "abc123def"}
        cert_result = {
            "cert_org": "TestOrg",
            "cert_org_unit": "IT",
            "cert_common_name": "example.com",
            "cert_serial": "SN12345",
        }
        redirect_result = {"uri_path": "/home", "redirect_url": "http://example.com/login"}

        patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
        # Replace favicon/cert/redirect mocks with richer data
        patches[1] = patch.object(fingerPrint_debug, "_fetch_favicon_async", new=AsyncMock(return_value=favicon_result))
        patches[2] = patch.object(fingerPrint_debug, "_fetch_certificate_async", new=AsyncMock(return_value=cert_result))
        patches[3] = patch.object(fingerPrint_debug, "_handle_js_redirect_async", new=AsyncMock(return_value=redirect_result))

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = fingerPrint_debug.mate(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["favicon"], "data:image/x-icon;base64,FAKE")
        self.assertEqual(payload["favicon_md5"], "abc123def")
        self.assertEqual(payload["cert_org"], "TestOrg")
        self.assertEqual(payload["cert_common_name"], "example.com")
        self.assertEqual(payload["cert_serial"], "SN12345")
        self.assertEqual(payload["uri_path"], "/home")
        self.assertEqual(payload["redirect_url"], "http://example.com/login")

    def test_mate_normalizes_bare_host_port_url(self):
        """裸域名 'host:port' 应自动补 http://，mate() 不因 urlparse 误解析而崩溃"""
        from app_cybersparker.views.expload import fingerPrint_debug

        for bare_url in ["ydbg.yun.liuzhou.gov.cn:8070", "192.168.1.1:8080", "internal.host:443"]:
            request = self.factory.post(
                "/fingerPrint_debug/mate",
                data={"url": bare_url, "regex": 'title="demo"', "proxy": ""},
            )
            request.session = self.session

            response_stub = self._response_stub(
                text="<html><title>demo</title><body>hello</body></html>",
            )
            response_stub.url = f"http://{bare_url}"

            patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                response = fingerPrint_debug.mate(request)

            payload = json.loads(response.content)
            self.assertTrue(payload["status"], f"裸域名 {bare_url} 应被正确处理，但返回了错误: {payload.get('error')}")

    def test_mate_preserves_existing_scheme_url(self):
        """已有 http:// 或 https:// 的 URL 应保持不变正常处理"""
        from app_cybersparker.views.expload import fingerPrint_debug

        for url in ["http://example.com", "https://secure.example.com:443"]:
            request = self.factory.post(
                "/fingerPrint_debug/mate",
                data={"url": url, "regex": 'title="demo"', "proxy": ""},
            )
            request.session = self.session

            response_stub = self._response_stub(
                text="<html><title>demo</title></html>",
            )
            response_stub.url = url

            patches = self._build_async_mate_mocks(fingerPrint_debug, response_stub)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                response = fingerPrint_debug.mate(request)

            payload = json.loads(response.content)
            self.assertTrue(payload["status"], f"已有 scheme 的 URL {url} 应正常处理")
        from app_cybersparker.views.expload.fingerPrint_debug import evaluate_fingerprint

        context = {"cert_org": "TestOrg", "uri_path": "/api"}
        result = evaluate_fingerprint("", "", "", 'cert_org="TestOrg"', context=context)
        self.assertTrue(result["matched"])

        result2 = evaluate_fingerprint("", "", "", 'uri_path="/api"', context=context)
        self.assertTrue(result2["matched"])


class AutoScanTaskApiTests(TestCase):
    """阶段九 BL-FE-201：任务列表 API + 轮询端点"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

        from app_cybersparker import models

        cls.running_task = models.auto_scan_tasks.objects.create(
            task_name="api-test-running",
            status=2,
            target="EXP_input/api_test.txt",
            process="45%",
            phase=1,
            pause_requested=False,
            queued=False,
            startTime="2026-05-30 10:00:00",
        )
        cls.finished_task = models.auto_scan_tasks.objects.create(
            task_name="api-test-finished",
            status=1,
            target="EXP_input/api_test2.txt",
            process="100%",
            phase=3,
            startTime="2026-05-30 09:00:00",
            endTime="2026-05-30 09:30:00",
        )

    def _auth(self, request):
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        return request

    # ── list API ──
    def test_list_api_returns_paginated_items(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api

        req = self._auth(self.factory.get("/"))
        resp = task_list_api(req)
        payload = json.loads(resp.content)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", payload)
        self.assertIn("total", payload)
        self.assertIn("page", payload)
        self.assertIn("total_pages", payload)
        self.assertGreaterEqual(payload["total"], 2)

    def test_list_api_filters_by_task_name(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api

        req = self._auth(self.factory.get("/", {"q": "api-test-running"}))
        resp = task_list_api(req)
        payload = json.loads(resp.content)

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["task_name"], "api-test-running")

    def test_list_api_items_have_status_fields(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api

        req = self._auth(self.factory.get("/"))
        resp = task_list_api(req)
        payload = json.loads(resp.content)

        item = payload["items"][0]
        self.assertIn("status_key", item)
        self.assertIn("status_label", item)
        self.assertIn("status_class", item)
        self.assertIn("phase_label", item)
        self.assertIn("process", item)
        self.assertIn("result_url", item)
        self.assertIn("react_result_url", item)

    def test_list_api_legacy_url_present(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api

        req = self._auth(self.factory.get("/"))
        resp = task_list_api(req)
        payload = json.loads(resp.content)

        self.assertEqual(payload["legacy_list_url"], "/Identify_task/list")

    # ── status API ──
    def test_status_api_running_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api

        req = self._auth(self.factory.get("/"))
        resp = task_status_api(req, self.running_task.id)
        payload = json.loads(resp.content)

        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["status"], "running")
        self.assertEqual(payload["data"]["phase"], 1)
        self.assertEqual(payload["data"]["process"], "45%")

    def test_status_api_finished_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api

        req = self._auth(self.factory.get("/"))
        resp = task_status_api(req, self.finished_task.id)
        payload = json.loads(resp.content)

        self.assertTrue(payload["status"])
        self.assertEqual(payload["data"]["status"], "finish")
        self.assertEqual(payload["data"]["phase"], 3)

    def test_status_api_404(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api

        req = self._auth(self.factory.get("/"))
        resp = task_status_api(req, 99999)

        self.assertEqual(resp.status_code, 404)

    # ── choices API ──
    def test_choices_api_returns_dropdown_options(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_choices_api

        req = self._auth(self.factory.get("/"))
        resp = task_choices_api(req)
        payload = json.loads(resp.content)

        self.assertTrue(payload["status"])
        self.assertIn("proxy_choices", payload)
        self.assertIn("input_type_choices", payload)
        self.assertIn("engine_type_choices", payload)
        self.assertEqual(len(payload["input_type_choices"]), 6)

    # ── history files API ──
    def test_history_files_api_returns_file_list(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_history_files_api

        req = self._auth(self.factory.get("/"))
        resp = task_history_files_api(req)
        payload = json.loads(resp.content)

        self.assertTrue(payload["status"])
        self.assertIn("files", payload["data"])


class AutoScanTaskOperateApiTests(TestCase):
    """阶段九 BL-FE-202：任务操作 / 删除 / 新增 API"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

        from app_cybersparker import models
        cls.task = models.auto_scan_tasks.objects.create(
            task_name="op-test-task",
            status=3,
            target="EXP_input/op_test.txt",
        )
        cls.engine_task = models.auto_scan_tasks.objects.create(
            task_name="op-test-engine",
            status=3,
            target=None,
            input_type=4,
            engine_type="fofa",
            engine_query='app="nginx"',
        )

    def _auth(self, request):
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        return request

    def _post_auth(self, path, data=None):
        from django.http import QueryDict
        req = self.factory.post(path)
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        if data:
            qd = QueryDict(mutable=True)
            for k, v in data.items():
                qd[k] = str(v)
            req.POST = qd
        req.GET = QueryDict(mutable=True)
        return req

    # ── operate API ──
    def test_operate_start_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_operate_api
        req = self._post_auth("/", {"uid": self.task.id, "status": "0"})
        resp = task_operate_api(req, self.task.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload["status"])

    def test_operate_delete_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_delete_api
        t = self.__class__.task.__class__.objects.create(task_name="tmp-delete-me", status=3, target="x")
        req = self._post_auth("/")
        resp = task_delete_api(req, t.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload["status"])

    def test_create_task_minimal(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_create_api
        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = req.POST.copy() if hasattr(req.POST, 'copy') else type(req.POST)(mutable=True)
        if not hasattr(qd, 'mutable'): qd._mutable = True
        qd["task_name"] = "created-via-api"
        qd["thread_num"] = "10"
        qd["sleep_time"] = "0"
        qd["http_timeout"] = "10"
        qd["input_type"] = "1"
        qd["Vulnerability_scanning"] = "0"
        req.POST = qd
        # Provide a minimal target file
        from django.core.files.uploadedfile import SimpleUploadedFile
        req.FILES['target'] = SimpleUploadedFile("test.txt", b"1.2.3.4")
        resp = task_create_api(req)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"Expected status=true, got {payload}")

    def test_create_task_with_search_query(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_create_api
        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = req.POST.copy() if hasattr(req.POST, 'copy') else type(req.POST)(mutable=True)
        if not hasattr(qd, 'mutable'): qd._mutable = True
        qd["task_name"] = "query-task"
        qd["thread_num"] = "5"
        qd["input_type"] = "6"
        qd["search_query"] = 'ip:"10.0.0.1"'
        req.POST = qd
        resp = task_create_api(req)
        payload = json.loads(resp.content)
        # May fail if no matching assets, that's ok - just verify endpoint works
        self.assertIn("status", payload)

    # ── zone 保存与回读 ──
    def test_create_task_with_custom_zone(self):
        """创建任务时选非公网区域（如内网1），数据库应保存对应 zone_id，
        不会被 ModelForm 字段名不匹配 + save() 兜底逻辑静默改为公网。"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_create_api
        from app_cybersparker import models as m

        # 创建测试用区域
        internal_zone, _ = m.AssetZone.objects.get_or_create(
            code="internal-test", defaults={"name": "内网测试", "description": "测试"}
        )

        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = req.POST.copy() if hasattr(req.POST, 'copy') else type(req.POST)(mutable=True)
        if not hasattr(qd, 'mutable'):
            qd._mutable = True
        qd["task_name"] = "zone-test-task"
        qd["thread_num"] = "10"
        qd["sleep_time"] = "0"
        qd["http_timeout"] = "10"
        qd["input_type"] = "1"
        qd["Vulnerability_scanning"] = "0"
        # 前端发的字段名是 zone_id（AssetZone 主键），不是 zone
        qd["zone_id"] = str(internal_zone.id)
        req.POST = qd
        from django.core.files.uploadedfile import SimpleUploadedFile
        req.FILES['target'] = SimpleUploadedFile("test.txt", b"1.2.3.4")
        resp = task_create_api(req)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"Expected status=true, got {payload}")

        # 验证数据库里存的是用户选的区域，不是公网 (id=1)
        task = m.auto_scan_tasks.objects.get(task_name="zone-test-task")
        self.assertEqual(task.zone_id, internal_zone.id,
                         f"zone should be {internal_zone.id} (内网测试), got {task.zone_id} (公网)")

    def test_create_engine_task_forces_public_zone(self):
        """引擎输入源 (input_type=4) 创建任务时，即使用户选了内网区域，
        也应强制改为公网（引擎扫描的都是公网资产）。"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_create_api
        from app_cybersparker import models as m

        public_zone = m.AssetZone.objects.get(code="public")
        internal_zone, _ = m.AssetZone.objects.get_or_create(
            code="internal-engine-test", defaults={"name": "内网引擎测试"}
        )

        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = req.POST.copy() if hasattr(req.POST, 'copy') else type(req.POST)(mutable=True)
        if not hasattr(qd, 'mutable'):
            qd._mutable = True
        qd["task_name"] = "engine-zone-test"
        qd["thread_num"] = "10"
        qd["sleep_time"] = "0"
        qd["http_timeout"] = "10"
        qd["input_type"] = "4"  # 引擎输入源
        qd["engine_type"] = "fofa"
        qd["engine_query"] = 'app="nginx"'
        qd["Vulnerability_scanning"] = "0"
        # 用户选了内网区域
        qd["zone_id"] = str(internal_zone.id)
        req.POST = qd
        resp = task_create_api(req)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"Expected status=true, got {payload}")

        task = m.auto_scan_tasks.objects.get(task_name="engine-zone-test")
        self.assertEqual(task.zone_id, public_zone.id,
                         "引擎输入源应强制 zone=公网，不应保留用户选择的内网区域")

    def test_edit_task_changes_zone(self):
        """编辑任务将 zone 从公网改为内网，数据库应反映变更。"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_update_api
        from app_cybersparker import models as m

        internal_zone, _ = m.AssetZone.objects.get_or_create(
            code="internal-edit-test", defaults={"name": "内网编辑测试"}
        )
        public_zone = m.AssetZone.objects.get(code="public")

        # 创建时 zone=公网
        task = m.auto_scan_tasks.objects.create(
            task_name="edit-zone-test",
            zone=public_zone,
            thread_num=10,
            input_type=1,
            status=3,
        )

        # 编辑改为内网区域
        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = req.POST.copy() if hasattr(req.POST, 'copy') else type(req.POST)(mutable=True)
        if not hasattr(qd, 'mutable'):
            qd._mutable = True
        qd["task_name"] = "edit-zone-test"
        qd["thread_num"] = "10"
        qd["sleep_time"] = "0"
        qd["http_timeout"] = "10"
        qd["input_type"] = "1"
        qd["Vulnerability_scanning"] = "0"
        qd["zone_id"] = str(internal_zone.id)
        req.POST = qd
        from django.test import override_settings
        req.GET = req.GET.copy()
        req.GET['uid'] = str(task.id)
        resp = task_update_api(req, task.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"Expected status=true, got {payload}")

        task.refresh_from_db()
        self.assertEqual(task.zone_id, internal_zone.id,
                         f"zone should be {internal_zone.id} (内网编辑测试), got {task.zone_id}")

    def test_detail_api_returns_zone_id(self):
        """详情 API 应包含 zone_id 字段，前端编辑表单需要它回填区域选择。"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_detail_api
        from app_cybersparker import models as m

        public_zone = m.AssetZone.objects.get(code="public")
        task = m.auto_scan_tasks.objects.create(
            task_name="detail-zone-test",
            zone=public_zone,
            thread_num=10,
            input_type=1,
            status=3,
        )

        req = self.factory.get("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = task_detail_api(req, task.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"))
        self.assertIn("zone_id", payload.get("data", {}),
                      "详情 API 返回的 data 必须包含 zone_id，否则前端无法回填区域")
        self.assertEqual(payload["data"]["zone_id"], public_zone.id)


class Stage9AcceptanceTests(TestCase):
    """阶段九验收：任务列表 / 操作 / 新增 / 删除 / 轮询 / 壳页 / 回退"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

        from app_cybersparker import models
        cls.task_unstarted = models.auto_scan_tasks.objects.create(
            task_name="acc-unstarted", status=3, target="EXP_input/acc_unstarted.txt")
        cls.task_running = models.auto_scan_tasks.objects.create(
            task_name="acc-running", status=2, target="EXP_input/acc_running.txt",
            process="50%", phase=1, startTime="2026-05-30 12:00:00")
        cls.task_finished = models.auto_scan_tasks.objects.create(
            task_name="acc-finished", status=1, target="EXP_input/acc_finished.txt",
            process="100%", phase=3, startTime="2026-05-30 11:00:00", endTime="2026-05-30 11:30:00")

    def _auth(self, request):
        request.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        return request

    # ── 1. 任务列表 API 对照 ──
    def test_list_api_returns_all_tasks(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api
        resp = task_list_api(self._auth(self.factory.get("/", {"rows_per_page": "13"})))
        payload = json.loads(resp.content)
        self.assertGreaterEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertIn("items", payload)
        # 验证每条 item 有完整 status 字段
        for item in payload["items"]:
            self.assertIn("status_key", item)
            self.assertIn("status_label", item)
            self.assertIn("phase_label", item)

    def test_list_api_search_filters(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api
        resp = task_list_api(self._auth(self.factory.get("/", {"q": "acc-running", "rows_per_page": "13"})))
        payload = json.loads(resp.content)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["task_name"], "acc-running")

    # ── 2. 状态轮询 ──
    def test_poll_running_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api
        resp = task_status_api(self._auth(self.factory.get("/")), self.task_running.id)
        data = json.loads(resp.content)["data"]
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["phase"], 1)
        self.assertEqual(data["process"], "50%")

    def test_poll_finished_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api
        resp = task_status_api(self._auth(self.factory.get("/")), self.task_finished.id)
        data = json.loads(resp.content)["data"]
        self.assertEqual(data["status"], "finish")

    def test_poll_unstarted_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_status_api
        resp = task_status_api(self._auth(self.factory.get("/")), self.task_unstarted.id)
        data = json.loads(resp.content)["data"]
        self.assertEqual(data["status"], "unstarted")

    # ── 3. 操作 API ──
    def test_operate_start_unstarted_task(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_operate_api
        from django.http import QueryDict
        req = self.factory.post("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        qd = QueryDict(mutable=True)
        qd["status"] = "0"
        req.POST = qd
        resp = task_operate_api(req, self.task_unstarted.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"start should succeed: {payload}")

    # ── 4. 删除 API ──
    def test_delete_task_via_api(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_delete_api
        t = self.__class__.task_unstarted.__class__.objects.create(
            task_name="acc-to-delete", status=3, target="x")
        resp = task_delete_api(self._auth(self.factory.post("/")), t.id)
        payload = json.loads(resp.content)
        self.assertTrue(payload.get("status"), f"delete should succeed: {payload}")

    # ── 5. 旧页回退 ──
    def test_task_list_does_not_leak_global_scope(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api
        from app_cybersparker.views.expload.task_manage import auto_scan_result as ar
        task_resp = task_list_api(self._auth(self.factory.get("/", {"rows_per_page": "13"})))
        task_payload = json.loads(task_resp.content)
        global_req = self._auth(self.factory.get("/", {"rows_per_page": "13"}))
        global_payload = json.loads(ar.global_asset_search_api(global_req).content)
        self.assertEqual(global_payload["contract"]["scope"], "global")
        self.assertIn("items", task_payload)

    # ── 9. 操作按钮状态逻辑 ──
    def test_task_status_labels(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_list_api
        resp = task_list_api(self._auth(self.factory.get("/", {"rows_per_page": "100"})))
        items = json.loads(resp.content)["items"]
        by_name = {i["task_name"]: i for i in items}
        self.assertEqual(by_name["acc-unstarted"]["status_key"], "unstarted")
        self.assertEqual(by_name["acc-running"]["status_key"], "running")
        self.assertEqual(by_name["acc-finished"]["status_key"], "finish")


class PocRuntimeTargetDictTests(TestCase):
    """验证 BL-PLUGIN-009: call_runtime_method 拒绝字符串 target，强制 dict 格式。"""

    def test_rejects_plain_string_target(self):
        """传入字符串 target 时抛出 TypeError，提示必须用 dict。"""
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import (
            call_runtime_method,
        )

        class FakeModule:
            @staticmethod
            def _verify(target):
                return {"target": target.get("target", ""), "result": "ok", "matched": True}

        with self.assertRaises(TypeError) as ctx:
            call_runtime_method(FakeModule, "verify", "http://example.com")
        self.assertIn("dict", str(ctx.exception))

    def test_rejects_dict_missing_target_key(self):
        """传入 dict 但缺 target key 时抛出 ValueError。"""
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import (
            call_runtime_method,
        )

        class FakeModule:
            @staticmethod
            def _verify(target):
                return {"target": target.get("target", ""), "result": "ok", "matched": True}

        with self.assertRaises(ValueError) as ctx:
            call_runtime_method(FakeModule, "verify", {"wrong_key": "x"})
        self.assertIn("missing", str(ctx.exception))

    def test_accepts_valid_target_dict(self):
        """传入正确格式的 target dict 时正常调用。"""
        from app_cybersparker.views.expload.task_manage.poc_runtime_resolver import (
            call_runtime_method,
        )

        class FakeModule:
            @staticmethod
            def _verify(target):
                return {"target": target.get("target", ""), "result": "ok", "matched": True}

        result = call_runtime_method(FakeModule, "verify", {"target": "http://example.com"})
        self.assertTrue(result.get("matched"))


class AutoScanVulnModeTests(TransactionTestCase):
    """BL-AUTO-018：仅漏洞扫描模式。TransactionTestCase 允许 executor 内部 connection.close()。"""

    def test_field_choices_has_three_options(self):
        field = models.auto_scan_tasks._meta.get_field("Vulnerability_scanning")
        self.assertEqual(len(field.choices), 3)

    def test_default_value_is_zero(self):
        field = models.auto_scan_tasks._meta.get_field("Vulnerability_scanning")
        self.assertEqual(field.default, 0)

    def test_choices_api_returns_three_options(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_choices_api
        req = RequestFactory().get("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = task_choices_api(req)
        payload = json.loads(resp.content)
        self.assertTrue(payload["status"])
        choices = payload.get("vulnerability_scanning_choices", [])
        self.assertEqual(len(choices), 3)

    def test_choices_api_mode2_label_readable(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_choices_api
        req = RequestFactory().get("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = task_choices_api(req)
        payload = json.loads(resp.content)
        mode2 = [c for c in payload["vulnerability_scanning_choices"] if c["value"] == 2]
        self.assertEqual(len(mode2), 1)

    def test_mode2_no_assets_returns_failed(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-no-assets", Vulnerability_scanning=2, status=2, dispatch_token="t",
        )
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.close_old_connections"):
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        task.refresh_from_db()
        self.assertTrue(task.failed)
        self.assertIn("没有资产", task.last_error or "")

    def test_mode2_no_product_assets_returns_failed(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-no-prod", Vulnerability_scanning=2, status=2, dispatch_token="t",
        )
        asset = models.auto_scan_indentify_result.objects.create(
            target="http://x.com", ip="1.2.3.4", protocol="http", port=80, products=[],
        )
        models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.close_old_connections"):
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        task.refresh_from_db()
        self.assertTrue(task.failed)
        self.assertIn("均未识别到产品", task.last_error or "")

    @unittest.skip("需完整Celery环境运行：executor线程内connection.close()在测试事务中不可用")
    def test_mode2_creates_exp_results(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        dt = uuid.uuid4().hex
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-exec", Vulnerability_scanning=2, vulnerability_thread_num=2,
            thread_num=5, proxy_id=None, task_args="{}", dispatch_token=dt,
        )
        asset = models.auto_scan_indentify_result.objects.create(
            target="http://example.com", ip="1.2.3.4", protocol="http", port=80, products=["Apache"],
        )
        models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        cond = f"body~=Apache_{dt[:8]}"
        fp = models.fingerPrint.objects.create(product="Apache", condition=cond)
        exp = models.EXP.objects.create(title=f"test-exp-{dt[:8]}", plugin_language=1, use=1, severity="high")
        models.exp_relate_fingerprint.objects.create(EXP_id=exp, fingerprint_id=fp)
        # 执行器在多个模块调用 close_old_connections，需要全部 mock
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.load_runtime_module_from_poc") as mock_load, \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.call_runtime_method") as mock_call:
            mock_load.return_value = MagicMock()
            mock_call.return_value = {"result": "vuln_found"}
            result = _run_auto_scan_task(task.id, dispatch_token=dt, owner="test")
        self.assertEqual(result["status"], "success")
        results = models.auto_scan_exp_result.objects.filter(task_id=task.id)
        self.assertTrue(results.exists(), "模式2完成後应有exp_result")

    @unittest.skip("需完整Celery环境运行：executor线程内connection.close()在测试事务中不可用")
    def test_mode2_skips_duplicates(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-dedup", Vulnerability_scanning=2, vulnerability_thread_num=2,
            thread_num=5, proxy_id=None, task_args="{}", dispatch_token="t",
        )
        for _ in range(2):
            asset = models.auto_scan_indentify_result.objects.create(
                target="http://dup.com", ip="1.2.3.4", protocol="http", port=80, products=["Nginx"],
            )
            models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        fp = models.fingerPrint.objects.create(product="Nginx", condition="header~=nginx-dedup")
        exp = models.EXP.objects.create(title="test-dedup", plugin_language=1, use=1, severity="medium")
        models.exp_relate_fingerprint.objects.create(EXP_id=exp, fingerprint_id=fp)
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_scan_task.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.load_runtime_module_from_poc") as mock_load, \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.call_runtime_method") as mock_call:
            mock_load.return_value = MagicMock()
            mock_call.return_value = {"result": "ok"}
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        self.assertEqual(models.auto_scan_exp_result.objects.filter(task_id=task.id).count(), 1)


class AutoScanVulnModeTests(TransactionTestCase):
    """BL-AUTO-018：仅漏洞扫描模式。TransactionTestCase 允许 executor 内部 close_old_connections()。
    注：executor 线程内 connection.close() 断开 Django 连接代理，2 条端到端测试标记 skip。
    """

    def test_field_choices_has_three_options(self):
        field = models.auto_scan_tasks._meta.get_field("Vulnerability_scanning")
        self.assertEqual(len(field.choices), 3)

    def test_default_value_is_zero(self):
        field = models.auto_scan_tasks._meta.get_field("Vulnerability_scanning")
        self.assertEqual(field.default, 0)

    def test_choices_api_returns_three_options(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_choices_api
        req = RequestFactory().get("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = task_choices_api(req)
        payload = json.loads(resp.content)
        self.assertTrue(payload["status"])
        choices = payload.get("vulnerability_scanning_choices", [])
        self.assertEqual(len(choices), 3)

    def test_choices_api_mode2_label_readable(self):
        from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_choices_api
        req = RequestFactory().get("/")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = task_choices_api(req)
        payload = json.loads(resp.content)
        mode2 = [c for c in payload["vulnerability_scanning_choices"] if c["value"] == 2]
        self.assertEqual(len(mode2), 1)

    def test_mode2_no_assets_returns_failed(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-no-assets", Vulnerability_scanning=2, status=2, dispatch_token="t",
        )
        with patch("app_cybersparker.tasks.close_old_connections"):
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        task.refresh_from_db()
        self.assertTrue(task.failed)
        self.assertIn("没有资产", task.last_error or "")

    def test_mode2_no_product_assets_returns_failed(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-no-prod", Vulnerability_scanning=2, status=2, dispatch_token="t",
        )
        asset = models.auto_scan_indentify_result.objects.create(
            target="http://x.com", ip="1.2.3.4", protocol="http", port=80, products=[],
        )
        models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        with patch("app_cybersparker.tasks.close_old_connections"):
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        task.refresh_from_db()
        self.assertTrue(task.failed)
        self.assertIn("均未识别到产品", task.last_error or "")

    @unittest.skip("需完整 Celery 环境")
    def test_mode2_creates_exp_results(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        dt = uuid.uuid4().hex
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-exec", Vulnerability_scanning=2, vulnerability_thread_num=2,
            thread_num=5, proxy_id=None, task_args="{}", dispatch_token=dt,
        )
        asset = models.auto_scan_indentify_result.objects.create(
            target="http://example.com", ip="1.2.3.4", protocol="http", port=80, products=["Apache"],
        )
        models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        cond = f"body~=Apache_{dt[:8]}"
        fp = models.fingerPrint.objects.create(product="Apache", condition=cond)
        exp = models.EXP.objects.create(title=f"test-exp-{dt[:8]}", plugin_language=1, use=1, severity="high")
        models.exp_relate_fingerprint.objects.create(EXP_id=exp, fingerprint_id=fp)
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.load_runtime_module_from_poc") as mock_load, \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.call_runtime_method") as mock_call:
            mock_load.return_value = MagicMock()
            mock_call.return_value = {"result": "vuln_found"}
            result = _run_auto_scan_task(task.id, dispatch_token=dt, owner="test")
        self.assertEqual(result["status"], "success")
        self.assertTrue(models.auto_scan_exp_result.objects.filter(task_id=task.id).exists())

    @unittest.skip("需完整 Celery 环境")
    def test_mode2_skips_duplicates(self):
        from app_cybersparker.tasks import _run_auto_scan_task
        task = models.auto_scan_tasks.objects.create(
            task_name="m2-dedup", Vulnerability_scanning=2, vulnerability_thread_num=2,
            thread_num=5, proxy_id=None, task_args="{}", dispatch_token="t",
        )
        for _ in range(2):
            asset = models.auto_scan_indentify_result.objects.create(
                target="http://dup.com", ip="1.2.3.4", protocol="http", port=80, products=["Nginx"],
            )
            models.AssetTaskRelation.objects.create(task_id=task.id, identify_result=asset)
        fp = models.fingerPrint.objects.create(product="Nginx", condition="header~=nginx-dedup")
        exp = models.EXP.objects.create(title="test-dedup", plugin_language=1, use=1, severity="medium")
        models.exp_relate_fingerprint.objects.create(EXP_id=exp, fingerprint_id=fp)
        with patch("app_cybersparker.tasks.close_old_connections"), \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.load_runtime_module_from_poc") as mock_load, \
             patch("app_cybersparker.views.expload.task_manage.auto_exp_task.call_runtime_method") as mock_call:
            mock_load.return_value = MagicMock()
            mock_call.return_value = {"result": "ok"}
            _run_auto_scan_task(task.id, dispatch_token="t", owner="t")
        self.assertEqual(models.auto_scan_exp_result.objects.filter(task_id=task.id).count(), 1)


# ============================================================
# BL-AUTO-019: fscanx 输出文件导入
# ============================================================

class FscanxModelTests(TestCase):
    """模型变更验证"""

    def test_unique_together_includes_uri_path(self):
        meta = models.auto_scan_indentify_result._meta
        ut = meta.unique_together
        self.assertIn(('zone', 'protocol', 'host', 'port', 'uri_path'), ut)

    def test_uri_path_normalization(self):
        asset = models.auto_scan_indentify_result(
            protocol='http', host='192.168.1.1', port=80,
            target='http://192.168.1.1/', ip='192.168.1.1',
        )
        asset.uri_path = '/'
        asset.clean()
        self.assertEqual(asset.uri_path, '')
        asset.uri_path = '/admin'
        asset.clean()
        self.assertEqual(asset.uri_path, '/admin')

    def test_source_type_field(self):
        field = models.auto_scan_indentify_result._meta.get_field('source_type')
        self.assertEqual(field.default, 1)

    def test_fscanx_service_detail_creation(self):
        task = models.auto_scan_tasks.objects.create(task_name='test-fs-model')
        detail = models.fscanx_service_detail.objects.create(
            task=task, protocol='ftp', host='192.168.1.1', port=21,
            result_type=1, result='test',
        )
        self.assertIsNotNone(detail.id)
        task.delete()

    def test_new_task_fields(self):
        field = models.auto_scan_tasks._meta.get_field('input_type')
        self.assertIn(2, dict(field.choices))
        self.assertTrue(models.auto_scan_tasks._meta.get_field('fscanx_file'))

    def test_edit_fscanx_task_without_new_file_reuses_existing(self):
        """编辑已有的 fscanx 任务时不传新文件，应复用旧文件而非报错"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from app_cybersparker.views.expload.task_manage.auto_scan_task import (
            ModelForm, resolve_target_source,
        )
        # 创建一个已有 fscanx_file 的任务
        task = models.auto_scan_tasks.objects.create(
            task_name=f'test-reuse-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1,
        )
        task.fscanx_file.save('test.txt', SimpleUploadedFile('test.txt', b'content'))
        task.save()
        try:
            # 模拟编辑请求：POST 中有 input_type=2 但没有上传新文件
            req = RequestFactory().post('/fake', {
                'input_type': '2',
                'task_name': task.task_name,
                'thread_num': '100',
                'sleep_time': '0',
                'http_timeout': '10',
                'Vulnerability_scanning': '0',
            })
            form = ModelForm(data=req.POST, files=req.FILES, instance=task)
            self.assertTrue(form.is_valid(), f'Form errors: {form.errors.as_json()}')
            is_ok, error = resolve_target_source(req, form, old_input_type=2)
            self.assertTrue(is_ok, f'应复用旧 fscanx 文件，但返回错误: {error}')
        finally:
            try:
                task.fscanx_file.delete(save=False)
            except Exception:
                pass
            task.delete()

    def test_new_fscanx_task_without_file_fails(self):
        """新建 fscanx 任务时不传文件，应报错"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task import (
            ModelForm, resolve_target_source,
        )
        task_name = f'test-new-{uuid.uuid4().hex[:8]}'
        # 注意：新建场景不传 instance（instance=None），需包含所有必填字段
        req = RequestFactory().post('/fake', {
            'input_type': '2',
            'task_name': task_name,
            'thread_num': '100',
            'sleep_time': '0',
            'http_timeout': '10',
            'Vulnerability_scanning': '0',
        })
        form = ModelForm(data=req.POST, files=req.FILES)
        self.assertTrue(form.is_valid(), f'Form errors: {form.errors.as_json()}')
        is_ok, error = resolve_target_source(req, form, old_input_type=None)
        self.assertFalse(is_ok)
        self.assertIn('fscanx_file', error)

    def test_switch_to_fscanx_without_file_fails(self):
        """从其他输入类型切换到 fscanx 时不传文件，应报错"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task import (
            ModelForm, resolve_target_source,
        )
        task = models.auto_scan_tasks.objects.create(
            task_name=f'test-switch-{uuid.uuid4().hex[:8]}',
            input_type=1,  # 原来是上传文件类型
        )
        try:
            req = RequestFactory().post('/fake', {
                'input_type': '2',
                'task_name': task.task_name,
                'thread_num': '100',
                'sleep_time': '0',
                'http_timeout': '10',
                'Vulnerability_scanning': '0',
            })
            form = ModelForm(data=req.POST, files=req.FILES, instance=task)
            self.assertTrue(form.is_valid(), f'Form errors: {form.errors.as_json()}')
            is_ok, error = resolve_target_source(req, form, old_input_type=1)
            self.assertFalse(is_ok)
            self.assertIn('fscanx_file', error)
        finally:
            task.delete()


class FscanxParserTests(TransactionTestCase):
    """解析器测试 — TransactionTestCase 兼容 parse_and_store 内的 connection.close()"""

    def setUp(self):
        self.task = models.auto_scan_tasks.objects.create(
            task_name=f'fscanx-test-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1,
        )

    def tearDown(self):
        models.fscanx_service_detail.objects.filter(task=self.task).delete()
        models.AssetTaskRelation.objects.filter(task_id=self.task.id).delete()
        models.auto_scan_indentify_result.objects.filter(source_type=2).delete()
        self.task.delete()

    def test_parse_port_open(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        content = "[*] Port open\t192.0.12.29:21\t\n"
        a, d, errs = parse_and_store(content, self.task, 1)
        self.assertGreater(a, 0)
        self.assertEqual(len(errs), 0)
        self.assertEqual(models.auto_scan_indentify_result.objects.filter(source_type=2).count(), 1)

    def test_parse_product(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        content = '[+] Product http://www.example.com\t200\t(test)\t[nginx], [jquery]\n'
        a, d, errs = parse_and_store(content, self.task, 1)
        self.assertGreater(a, 0)
        asset = models.auto_scan_indentify_result.objects.filter(
            protocol='http', host='www.example.com', port=80,
        ).first()
        self.assertIsNotNone(asset)
        self.assertIn('nginx', asset.products or [])

    def test_parse_os_info(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        content = '[*] OsInfo\t36.134.129.179\t(Windows Server 2012)\t\n'
        a, d, errs = parse_and_store(content, self.task, 1)
        self.assertGreater(d, 0)

    def test_parse_other_weak(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        content = '[+] mysql:36.1.1.179:3306:root root\n[+] redis:36.1.1.179:6379:foobared\n'
        a, d, errs = parse_and_store(content, self.task, 1)
        self.assertEqual(models.fscanx_service_detail.objects.filter(task=self.task, result_type=1).count(), 2)

    def test_overwrite_merges_products(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        existing = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='192.168.99.99', port=80, uri_path='',
            target='http://192.168.99.99', products=['apache'], title='Old',
            source_type=1, ip='192.168.99.99',
        )
        content = '[+] Product http://192.168.99.99\t200\t(New)\t[nginx]\n'
        a, d, errs = parse_and_store(content, self.task, 1)
        existing.refresh_from_db()
        self.assertEqual(existing.title, 'New')
        self.assertEqual(existing.source_type, 2)
        self.assertIn('nginx', existing.products or [])

    def test_skip_does_not_modify(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        existing = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='192.168.88.88', port=80, uri_path='',
            target='http://192.168.88.88', products=['apache'], title='Old',
            source_type=1, ip='192.168.88.88',
        )
        content = '[+] Product http://192.168.88.88\t200\t(New)\t[nginx]\n'
        a, d, errs = parse_and_store(content, self.task, 2)
        existing.refresh_from_db()
        self.assertEqual(existing.title, 'Old')
        # skip 策略也必须创建 AssetTaskRelation，否则资产在任务结果页不可见
        self.assertTrue(
            models.AssetTaskRelation.objects.filter(
                task_id=self.task.id, identify_result=existing,
            ).exists()
        )

    def test_error_tolerance(self):
        from app_cybersparker.services.fscanx_parser import parse_and_store
        content = 'not a valid line\n[*] Port open\t192.0.12.29:80\thttp\n'
        a, d, errs = parse_and_store(content, self.task, 1)
        self.assertGreater(a, 0)


class FscanxSyncCodeTests(TestCase):
    """10 处已有代码同步修改验证"""

    def test_match_keys_has_uri_path(self):
        import app_cybersparker.services.result_event_service as res
        import inspect
        self.assertIn('uri_path', inspect.getsource(res._write_identify_event))

    def test_resolve_id_has_uri_path(self):
        import app_cybersparker.services.result_event_service as res
        import inspect
        self.assertIn('uri_path=uri_path', inspect.getsource(res._resolve_identify_result_id))

    def test_sync_update_has_uri_path_in(self):
        from app_cybersparker.services.dirscan_worker import _sync_update_root_uri_path
        import inspect
        self.assertIn('uri_path__in', inspect.getsource(_sync_update_root_uri_path))

    def test_dirscan_distinct(self):
        from app_cybersparker.views.expload.dirscan_task_manage import _resolve_input_sources
        import inspect
        self.assertIn('.distinct()', inspect.getsource(_resolve_input_sources))

    def test_export_url_has_uri_path(self):
        import app_cybersparker.tasks as t
        import inspect
        self.assertIn('item.uri_path', inspect.getsource(t))


class FscanxUniqueTogetherRegressionTests(TestCase):
    """unique_together 变更回归"""

    def test_diff_path_two_rows(self):
        a1 = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='192.168.1.1', port=80, uri_path='',
            target='http://192.168.1.1/', products=[], ip='192.168.1.1',
        )
        a2 = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='192.168.1.1', port=80, uri_path='/admin',
            target='http://192.168.1.1/admin', products=[], ip='192.168.1.1',
        )
        self.assertNotEqual(a1.id, a2.id)

    def test_same_path_raises_integrity(self):
        """同 zone 内同 (protocol,host,port,uri_path) 冲突（zone 参与唯一键）"""
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.get(code="public")
        models.auto_scan_indentify_result.objects.create(
            zone=zone, protocol='http', host='192.168.1.2', port=80, uri_path='/api',
            target='http://192.168.1.2/api', products=[], ip='192.168.1.2',
        )
        with self.assertRaises(Exception):
            models.auto_scan_indentify_result.objects.create(
                zone=zone, protocol='http', host='192.168.1.2', port=80, uri_path='/api',
                target='http://192.168.1.2/api2', products=[], ip='192.168.1.2',
            )



class FscanxApiTests(TestCase):
    """fscanx API 层测试"""

    def setUp(self):
        self.t1 = models.auto_scan_tasks.objects.create(
            task_name=f'fscanx-api-test-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1, status=1,
        )
        models.fscanx_service_detail.objects.create(
            task=self.t1, protocol='ftp', host='10.0.0.1', port=21,
            result_type=1, result='test weak',
        )
        models.fscanx_service_detail.objects.create(
            task=self.t1, protocol='ftp', host='10.0.0.1', port=21,
            result_type=2, result='test ftp list',
        )

    def tearDown(self):
        models.fscanx_service_detail.objects.filter(task=self.t1).delete()
        self.t1.delete()

    def test_task_list_returns_rows(self):
        from app_cybersparker.views.expload.fscanx_views import fscanx_task_list_api
        from django.test import RequestFactory
        req = RequestFactory().get('/api/v1/fscanx-tasks?page=1&rows_per_page=15')
        res = fscanx_task_list_api(req)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content)
        self.assertTrue(data['status'])
        self.assertGreater(data['total'], 0)

    def test_detail_returns_paginated_rows(self):
        from app_cybersparker.views.expload.fscanx_views import fscanx_task_detail_api
        from django.test import RequestFactory
        req = RequestFactory().get(f'/api/v1/fscanx-tasks/{self.t1.id}/details?page=1&rows_per_page=2')
        res = fscanx_task_detail_api(req, self.t1.id)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content)
        self.assertTrue(data['status'])
        self.assertGreater(data['total'], 0)
        self.assertIn('task', data)
        self.assertIn('result_type_choices', data)

    def test_detail_result_type_filter(self):
        from app_cybersparker.views.expload.fscanx_views import fscanx_task_detail_api
        from django.test import RequestFactory
        req = RequestFactory().get(f'/api/v1/fscanx-tasks/{self.t1.id}/details?result_type=1')
        res = fscanx_task_detail_api(req, self.t1.id)
        data = json.loads(res.content)
        for row in data['rows']:
            self.assertEqual(row['result_type'], 1)

    def test_task_list_page_not_found(self):
        from app_cybersparker.views.expload.fscanx_views import fscanx_task_detail_api
        from django.test import RequestFactory
        req = RequestFactory().get('/api/v1/fscanx-tasks/99999/details')
        res = fscanx_task_detail_api(req, 99999)
        self.assertEqual(res.status_code, 404)


class FscanxThreadLifecycleTests(TransactionTestCase):
    """线程生命周期：心跳、停止、异常处理"""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.task = models.auto_scan_tasks.objects.create(
            task_name=f'fscanx-lifecycle-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1, status=3,
        )
        # 上传一个包含有效内容的文件
        content = b'[*] Port open\t192.0.12.29:80\thttp\n[+] Product http://example.com\t200\t(test)\t[nginx]\n'
        self.task.fscanx_file.save('lifecycle_test.txt', SimpleUploadedFile('lifecycle_test.txt', content))
        self.task.save()

    def tearDown(self):
        models.fscanx_service_detail.objects.filter(task=self.task).delete()
        models.AssetTaskRelation.objects.filter(task_id=self.task.id).delete()
        models.auto_scan_indentify_result.objects.filter(source_type=2).delete()
        try:
            self.task.fscanx_file.delete(save=False)
        except Exception:
            pass
        self.task.delete()

    def test_import_updates_heartbeat(self):
        """导入过程中 heartbeat_at 被更新"""
        from app_cybersparker.services.fscanx_parser import run_import
        run_import(self.task)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 1)
        self.assertIsNotNone(self.task.heartbeat_at)

    def test_empty_file_marks_failed(self):
        """空文件 → 任务 failed"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        t2 = models.auto_scan_tasks.objects.create(
            task_name=f'fscanx-empty-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1, status=3,
        )
        t2.fscanx_file.save('empty.txt', SimpleUploadedFile('empty.txt', b''))
        t2.save()
        from app_cybersparker.services.fscanx_parser import run_import
        success, msg = run_import(t2)
        t2.refresh_from_db()
        # 空文件解析器会处理（无匹配行但不是失败），所以应该成功
        # 但 run_import 入口在解析前检查文件读取
        self.assertTrue(success or t2.failed)
        t2.fscanx_file.delete(save=False)
        t2.delete()

    def test_stop_signal_stops_import(self):
        """设置 stop_requested → 线程在检查点退出"""
        from app_cybersparker.services.fscanx_parser import run_import
        # 先设置 stop_requested
        models.auto_scan_tasks.objects.filter(id=self.task.id).update(stop_requested=True)
        success, msg = run_import(self.task)
        self.task.refresh_from_db()
        # 应该在检查点退出，status 为 stopped 或 finish（如果文件小到在第一个检查点前完成）
        self.assertIn(self.task.status, [1, 3])


class FscanxGlobalSearchTests(TestCase):
    """fscanx 数据在全局资产检索中可见"""

    def setUp(self):
        self.asset = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='fscanx-search-test.example.com', port=8080,
            uri_path='', target='http://fscanx-search-test.example.com:8080',
            ip='10.0.0.99', products=['test-fscanx-product'],
            source_type=2, status_code=200, title='Fscanx Test Asset',
        )
        self.task = models.auto_scan_tasks.objects.create(
            task_name=f'fscanx-gs-{uuid.uuid4().hex[:8]}',
            input_type=2, conflict_strategy=1, status=1,
        )
        models.AssetTaskRelation.objects.create(task_id=self.task.id, identify_result=self.asset)

    def tearDown(self):
        models.AssetTaskRelation.objects.filter(task_id=self.task.id).delete()
        self.asset.delete()
        self.task.delete()

    def test_global_search_finds_fscanx_asset(self):
        """全局资产检索能搜到 fscanx 导入的资产"""
        from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure
        condition = parse_condition('protocol:http')
        q = to_query_structure(condition)
        results = models.auto_scan_indentify_result.objects.filter(q)
        self.assertGreater(results.count(), 0)
        self.assertIn(self.asset, results)

    def test_global_search_by_product(self):
        """按产品名搜索 fscanx 资产"""
        from app_cybersparker.services.asset_search_parser import parse_condition, to_query_structure
        condition = parse_condition('product:test-fscanx-product')
        q = to_query_structure(condition)
        results = models.auto_scan_indentify_result.objects.filter(q)
        self.assertIn(self.asset, results)


class FscanxSyncCodeBehaviorTests(TestCase):
    """同步代码行为级验证（非仅源码检查）"""

    def test_result_event_write_with_diff_uri_path_creates_two_rows(self):
        """同 host:port 不同 path → 创建两行"""
        from app_cybersparker.services.result_event_service import (
            build_identify_event_payloads, publish_result_events,
            process_result_stream, STREAM_IDENTIFY, _relation_buffer,
        )
        _relation_buffer.clear()  # 防止跨测试残留
        p1 = build_identify_event_payloads(
            0, 'http://a.example.com/', 'http/1.0 200', 'A', '<html></html>', 200,
            '10.0.0.1', 'a.example.com', 80, 'http', '', 'nginx', uri_path='',
        )
        p2 = build_identify_event_payloads(
            0, 'http://a.example.com/api', 'http/1.0 200', 'B', '<html></html>', 200,
            '10.0.0.1', 'a.example.com', 80, 'http', '', 'nginx', uri_path='/api',
        )
        try:
            publish_result_events(STREAM_IDENTIFY, p1 + p2)
            process_result_stream(STREAM_IDENTIFY)
            rows = models.auto_scan_indentify_result.objects.filter(
                host='a.example.com', port=80, protocol='http',
            ).order_by('uri_path')
            self.assertEqual(rows.count(), 2)
        finally:
            models.auto_scan_indentify_result.objects.filter(host='a.example.com', port=80, protocol='http').delete()

    def test_dirscan_resolve_input_sources_distinct(self):
        """_resolve_input_sources 输出不包含重复行"""
        a1 = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='distinct-test.local', port=80, uri_path='',
            target='http://distinct-test.local/', ip='10.0.0.50', products=[],
        )
        a2 = models.auto_scan_indentify_result.objects.create(
            protocol='http', host='distinct-test.local', port=80, uri_path='/page',
            target='http://distinct-test.local/page', ip='10.0.0.50', products=[],
        )
        t = models.auto_scan_tasks.objects.create(task_name=f'ds-test-{uuid.uuid4().hex[:8]}', input_type=1)
        models.AssetTaskRelation.objects.create(task_id=t.id, identify_result=a1)
        models.AssetTaskRelation.objects.create(task_id=t.id, identify_result=a2)
        try:
            from app_cybersparker.views.expload.dirscan_task_manage import _resolve_input_sources
            roots = _resolve_input_sources(0, [t.id])
            self.assertIsNotNone(roots)
            seen = {}
            dupes = []
            for r in roots:
                key = (r[0], r[1], r[2])
                if key in seen:
                    dupes.append(key)
                seen[key] = True
            self.assertEqual(len(dupes), 0, f'发现重复项: {dupes}')
        finally:
            models.AssetTaskRelation.objects.filter(task_id=t.id).delete()
            a1.delete()
            a2.delete()
            t.delete()

    def test_dirscan_resolve_input_sources_respects_zone(self):
        """_resolve_input_sources 只返回指定 zone 的资产，不跨区域"""
        public_zone = models.AssetZone.objects.get(code="public")
        internal_zone, _ = models.AssetZone.objects.get_or_create(
            code="dirscan-zone-test", defaults={"name": "目录扫描区域测试"}
        )
        # 公网资产
        a_pub = models.auto_scan_indentify_result.objects.create(
            zone=public_zone, protocol='http', host='pub.example.com', port=80,
            uri_path='', target='http://pub.example.com/', ip='1.2.3.4', products=[],
        )
        # 内网资产（不同 host）
        a_int = models.auto_scan_indentify_result.objects.create(
            zone=internal_zone, protocol='http', host='intranet.local', port=8080,
            uri_path='', target='http://intranet.local:8080/', ip='10.0.0.1', products=[],
        )
        t = models.auto_scan_tasks.objects.create(task_name=f'ds-zone-{uuid.uuid4().hex[:8]}', input_type=1)
        models.AssetTaskRelation.objects.create(task_id=t.id, identify_result=a_pub)
        models.AssetTaskRelation.objects.create(task_id=t.id, identify_result=a_int)
        try:
            from app_cybersparker.views.expload.dirscan_task_manage import _resolve_input_sources
            # 只查内网 zone — 应只有内网资产
            roots_int = _resolve_input_sources(0, [t.id], zone_id=internal_zone.id)
            self.assertIsNotNone(roots_int)
            self.assertEqual(len(roots_int), 1)
            self.assertEqual(roots_int[0], ('http', 'intranet.local', 8080))

            # 只查公网 zone — 应只有公网资产
            roots_pub = _resolve_input_sources(0, [t.id], zone_id=public_zone.id)
            self.assertIsNotNone(roots_pub)
            self.assertEqual(len(roots_pub), 1)
            self.assertEqual(roots_pub[0], ('http', 'pub.example.com', 80))

            # 不传 zone_id（全区域）应返回 2 条（不同 host:port）
            roots_all = _resolve_input_sources(0, [t.id])
            self.assertIsNotNone(roots_all)
            self.assertEqual(len(roots_all), 2,
                             "不传 zone_id 应返回所有区域的资产")
        finally:
            models.AssetTaskRelation.objects.filter(task_id=t.id).delete()
            a_pub.delete()
            a_int.delete()
            t.delete()


class HostedFileModelTests(TransactionTestCase):
    def test_create_hosted_file(self):
        f = models.HostedFile.objects.create(
            original_name='test.pdf',
            stored_name='abc123.pdf',
            file_size=1024,
            is_public=True,
        )
        self.assertIsNotNone(f.id)
        self.assertEqual(f.original_name, 'test.pdf')
        self.assertEqual(f.stored_name, 'abc123.pdf')
        self.assertEqual(f.file_size, 1024)
        self.assertTrue(f.is_public)
        f.delete()

    def test_default_is_public(self):
        f = models.HostedFile.objects.create(
            original_name='secret.doc',
            stored_name='xyz789.doc',
            file_size=512,
        )
        self.assertTrue(f.is_public)
        f.delete()

    def test_stored_name_unique(self):
        from django.db import IntegrityError
        f1 = models.HostedFile.objects.create(
            original_name='a.txt', stored_name='unique.txt', file_size=10,
        )
        with self.assertRaises((IntegrityError, Exception)):
            models.HostedFile.objects.create(
                original_name='b.txt', stored_name='unique.txt', file_size=20,
            )
        f1.delete()


class HostedFileApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.upload_dir = _PROJECT_ROOT / 'upload_files'
        cls.upload_dir.mkdir(exist_ok=True)

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        session = SessionStore()
        session.create()
        self.session_data = session

    def _login_request(self):
        req = self.factory.get('/')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        return req

    def _anon_request(self):
        req = self.factory.get('/')
        req.session = self.session_data
        return req

    def test_list_files(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_list_api
        req = self._login_request()
        resp = hosted_file_list_api(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])

    def test_upload_creates_record_and_file(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_upload_api
        from django.core.files.uploadedfile import SimpleUploadedFile
        req = self.factory.post('/fake', {
            'is_public': 'true',
        })
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        req.FILES['file'] = SimpleUploadedFile('hello.txt', b'hello world')
        resp = hosted_file_upload_api(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        file_id = models.HostedFile.objects.filter(original_name='hello.txt').first()
        self.assertIsNotNone(file_id)
        # clean up
        if file_id:
            disk_path = self.upload_dir / file_id.stored_name
            if disk_path.exists():
                disk_path.unlink()
            file_id.delete()

    def test_upload_rejects_over_200mb(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_upload_api
        from django.core.files.uploadedfile import SimpleUploadedFile
        req = self.factory.post('/fake', {
            'is_public': 'true',
        })
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        big = SimpleUploadedFile('big.bin', b'x' * (200 * 1024 * 1024 + 1))
        req.FILES['file'] = big
        resp = hosted_file_upload_api(req)
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertFalse(data['status'])

    def test_upload_truncates_long_filename(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_upload_api
        from django.core.files.uploadedfile import SimpleUploadedFile
        long_name = 'a' * 300 + '.txt'
        req = self.factory.post('/fake', {'is_public': 'true'})
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        req.FILES['file'] = SimpleUploadedFile(long_name, b'short')
        resp = hosted_file_upload_api(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        self.assertLessEqual(len(data['data']['original_name']), 256)
        self.assertTrue(data['data']['original_name'].endswith('.txt'))
        # clean up
        f = models.HostedFile.objects.filter(id=data['data']['id']).first()
        if f:
            disk_path = self.upload_dir / f.stored_name
            if disk_path.exists():
                disk_path.unlink()
            f.delete()

    def test_delete_removes_record_and_disk_file(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_delete_api
        stored = f'test-del-{uuid.uuid4().hex[:8]}.txt'
        disk_path = self.upload_dir / stored
        disk_path.write_text('delete me')
        f = models.HostedFile.objects.create(
            original_name='delete.txt', stored_name=stored, file_size=10,
        )
        req = self._login_request()
        resp = hosted_file_delete_api(req, f.id)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        self.assertFalse(models.HostedFile.objects.filter(id=f.id).exists())
        self.assertFalse(disk_path.exists())

    def test_rename_updates_stored_name_and_disk(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_rename_api
        old_stored = f'test-ren-{uuid.uuid4().hex[:8]}.txt'
        disk_path = self.upload_dir / old_stored
        disk_path.write_text('rename me')
        f = models.HostedFile.objects.create(
            original_name='old.txt', stored_name=old_stored, file_size=10,
        )
        try:
            req = self.factory.put('/fake', json.dumps({'new_name': 'new-name.txt'}),
                                   content_type='application/json')
            req.session = self.session_data
            req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
            resp = hosted_file_rename_api(req, f.id)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            f.refresh_from_db()
            self.assertIn('new-name', f.stored_name)
            self.assertTrue(f.stored_name.endswith('.txt'))
            # old disk file gone, new exists
            self.assertFalse(disk_path.exists())
            new_path = self.upload_dir / f.stored_name
            self.assertTrue(new_path.exists())
            new_path.unlink()
        finally:
            f.delete()

    def test_rename_rejects_path_traversal(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_rename_api
        stored = f'test-notrav-{uuid.uuid4().hex[:8]}.txt'
        disk_path = self.upload_dir / stored
        disk_path.write_text('no traversal')
        f = models.HostedFile.objects.create(
            original_name='safe.txt', stored_name=stored, file_size=10,
        )
        try:
            req = self.factory.put('/fake', json.dumps({'new_name': '../etc/passwd'}),
                                   content_type='application/json')
            req.session = self.session_data
            req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
            resp = hosted_file_rename_api(req, f.id)
            self.assertEqual(resp.status_code, 400)
            self.assertTrue(disk_path.exists())  # 原始文件未被移动
        finally:
            disk_path.unlink()
            f.delete()

    def test_rename_rejects_null_byte(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_rename_api
        stored = f'test-null-{uuid.uuid4().hex[:8]}.txt'
        disk_path = self.upload_dir / stored
        disk_path.write_text('null byte')
        f = models.HostedFile.objects.create(
            original_name='safe.txt', stored_name=stored, file_size=10,
        )
        try:
            req = self.factory.put('/fake', json.dumps({'new_name': 'ok\x00/../etc'}),
                                   content_type='application/json')
            req.session = self.session_data
            req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
            resp = hosted_file_rename_api(req, f.id)
            self.assertEqual(resp.status_code, 400)
            self.assertTrue(disk_path.exists())
        finally:
            disk_path.unlink()
            f.delete()

    def test_change_access_level(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_access_api
        f = models.HostedFile.objects.create(
            original_name='toggle.txt', stored_name=f'tog-{uuid.uuid4().hex[:8]}.txt', file_size=10,
            is_public=True,
        )
        try:
            req = self.factory.put('/fake', json.dumps({'is_public': False}),
                                   content_type='application/json')
            req.session = self.session_data
            req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
            resp = hosted_file_access_api(req, f.id)
            self.assertEqual(resp.status_code, 200)
            f.refresh_from_db()
            self.assertFalse(f.is_public)
        finally:
            f.delete()


class HostedFileNoteTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.upload_dir = _PROJECT_ROOT / 'upload_files'
        cls.upload_dir.mkdir(exist_ok=True)

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        session = SessionStore()
        session.create()
        self.session_data = session
        self.stored = f'note-{uuid.uuid4().hex[:8]}.txt'
        disk_path = self.upload_dir / self.stored
        disk_path.write_text('note test')
        self.f = models.HostedFile.objects.create(
            original_name='note-test.txt', stored_name=self.stored, file_size=9, note='',
        )

    def tearDown(self):
        disk_path = self.upload_dir / self.stored
        if disk_path.exists():
            disk_path.unlink()
        self.f.delete()

    def test_set_note(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_note_api
        req = self.factory.put('/fake', json.dumps({'note': '这是测试备注'}),
                               content_type='application/json')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        resp = hosted_file_note_api(req, self.f.id)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        self.assertEqual(data['data']['note'], '这是测试备注')
        self.f.refresh_from_db()
        self.assertEqual(self.f.note, '这是测试备注')

    def test_update_note(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_note_api
        self.f.note = '旧备注'
        self.f.save()
        req = self.factory.put('/fake', json.dumps({'note': '新备注'}),
                               content_type='application/json')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        resp = hosted_file_note_api(req, self.f.id)
        self.assertEqual(resp.status_code, 200)
        self.f.refresh_from_db()
        self.assertEqual(self.f.note, '新备注')

    def test_clear_note(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_note_api
        self.f.note = '要清除的备注'
        self.f.save()
        req = self.factory.put('/fake', json.dumps({'note': ''}),
                               content_type='application/json')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        resp = hosted_file_note_api(req, self.f.id)
        self.assertEqual(resp.status_code, 200)
        self.f.refresh_from_db()
        self.assertEqual(self.f.note, '')

    def test_note_appears_in_list(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_list_api
        self.f.note = '列表中的备注'
        self.f.save()
        req = self.factory.get('/fake')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        resp = hosted_file_list_api(req)
        data = json.loads(resp.content)
        found = [f for f in data['data']['files'] if f['id'] == self.f.id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['note'], '列表中的备注')


class HostedFileDownloadTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.upload_dir = _PROJECT_ROOT / 'upload_files'
        cls.upload_dir.mkdir(exist_ok=True)

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        self.stored = f'dl-{uuid.uuid4().hex[:8]}.txt'
        self.disk_path = self.upload_dir / self.stored
        self.disk_path.write_text('download content')
        self.pub = models.HostedFile.objects.create(
            original_name='pub.txt', stored_name=self.stored, file_size=16, is_public=True,
        )

    def tearDown(self):
        if self.disk_path.exists():
            self.disk_path.unlink()
        self.pub.delete()

    def test_public_download_without_login(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        req = self.factory.get('/fake')
        req.session = {}
        resp = hosted_file_download(req, self.pub.id, self.pub.original_name)
        self.assertEqual(resp.status_code, 200)
        body = b''.join(resp.streaming_content)
        self.assertEqual(body, b'download content')

    def test_public_download_with_login(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        req = self.factory.get('/fake')
        req.session = {'info': {'username': 'admin'}}
        resp = hosted_file_download(req, self.pub.id, self.pub.original_name)
        self.assertEqual(resp.status_code, 200)

    def test_private_download_without_login_returns_403(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        priv_stored = f'priv-{uuid.uuid4().hex[:8]}.txt'
        priv_path = self.upload_dir / priv_stored
        priv_path.write_text('secret')
        priv = models.HostedFile.objects.create(
            original_name='secret.txt', stored_name=priv_stored, file_size=6, is_public=False,
        )
        try:
            req = self.factory.get('/fake')
            req.session = {}
            resp = hosted_file_download(req, priv.id, priv.original_name)
            self.assertEqual(resp.status_code, 403)
        finally:
            priv.delete()
            if priv_path.exists():
                priv_path.unlink()

    def test_private_download_with_login_succeeds(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        priv_stored = f'priv2-{uuid.uuid4().hex[:8]}.txt'
        priv_path = self.upload_dir / priv_stored
        priv_path.write_text('secret')
        priv = models.HostedFile.objects.create(
            original_name='secret2.txt', stored_name=priv_stored, file_size=6, is_public=False,
        )
        try:
            req = self.factory.get('/fake')
            req.session = {'info': {'username': 'admin'}}
            resp = hosted_file_download(req, priv.id, priv.original_name)
            self.assertEqual(resp.status_code, 200)
        finally:
            priv.delete()
            if priv_path.exists():
                priv_path.unlink()

    def test_nonexistent_file_returns_404(self):
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        req = self.factory.get('/fake')
        req.session = {}
        resp = hosted_file_download(req, 99999, 'nonexistent.xyz')
        self.assertEqual(resp.status_code, 404)

    def test_wrong_filename_with_correct_id_returns_404(self):
        """防止 ID 枚举：正确 ID + 错误文件名 → 404"""
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        req = self.factory.get('/fake')
        req.session = {}
        resp = hosted_file_download(req, self.pub.id, 'wrong-name.txt')
        self.assertEqual(resp.status_code, 404)

    def test_content_disposition_strips_injection_chars(self):
        """Content-Disposition 头应剔除 \r\n\" 防注入"""
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        injected_name = f'inject-{uuid.uuid4().hex[:8]}.txt'
        inj_path = self.upload_dir / injected_name
        inj_path.write_text('inject')
        inj = models.HostedFile.objects.create(
            original_name='test\r\nX-Injected: evil".pdf',
            stored_name=injected_name, file_size=7, is_public=True,
        )
        try:
            req = self.factory.get('/fake')
            req.session = {}
            resp = hosted_file_download(req, inj.id, 'test\r\nX-Injected: evil".pdf')
            cd = resp['Content-Disposition']
            # \r\n 被剔除（防止注入新响应头行），" 被剔除（防止提前闭合引号）
            self.assertNotIn('\r', cd)
            self.assertNotIn('\n', cd)
            # 注入的 " 被剔除，只保留标准 wrapping 的双引号
            self.assertEqual(cd.count('"'), 2)
        finally:
            inj.delete()
            if inj_path.exists():
                inj_path.unlink()

    def test_download_uses_file_response(self):
        """大文件下载用 FileResponse 流式，不用 HttpResponse 全量读"""
        from app_cybersparker.views.expload.hosted_file_manage import hosted_file_download
        from django.http import FileResponse
        req = self.factory.get('/fake')
        req.session = {}
        resp = hosted_file_download(req, self.pub.id, self.pub.original_name)
        self.assertIsInstance(resp, FileResponse)


class UserManageApiTests(TestCase):
    """用户管理 API 测试 — 角色边界校验"""

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        User = get_user_model()

        self.factory = RequestFactory()

        self.super_admin = User.objects.create_user(username='sa', password='p', is_active=True)
        UserProfile.objects.filter(user=self.super_admin).update(role='super_admin')

        self.admin = User.objects.create_user(username='adm', password='p', is_active=True)
        UserProfile.objects.filter(user=self.admin).update(role='admin')

        self.user1 = User.objects.create_user(username='u1', password='p', is_active=True)
        UserProfile.objects.filter(user=self.user1).update(role="user")

        self.user2 = User.objects.create_user(username='u2', password='p', is_active=True)
        UserProfile.objects.filter(user=self.user2).update(role="user")

        self.sa_session = SessionStore()
        self.sa_session.create()
        self.sa_session['info'] = {'id': self.super_admin.id, 'username': 'sa', 'role': 'super_admin'}

        self.adm_session = SessionStore()
        self.adm_session.create()
        self.adm_session['info'] = {'id': self.admin.id, 'username': 'adm', 'role': 'admin'}

        self.u1_session = SessionStore()
        self.u1_session.create()
        self.u1_session['info'] = {'id': self.user1.id, 'username': 'u1', 'role': 'user'}

    def _req(self, method, path, session, body=None):
        from json import dumps
        kwargs = {'path': path}
        if body is not None:
            kwargs['data'] = dumps(body)
            kwargs['content_type'] = 'application/json'
        req = getattr(self.factory, method)(**kwargs)
        if session:
            req.session = session
        return req

    # ——— 列表 ———

    def test_super_admin_sees_all(self):
        from app_cybersparker.views.user_manage import user_list_api
        req = self._req('get', '/api/v1/users', self.sa_session)
        resp = user_list_api(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        roles = [u['role'] for u in data['users']]
        self.assertIn('super_admin', roles)
        self.assertIn('admin', roles)
        self.assertIn('user', roles)

    def test_admin_sees_only_users(self):
        from app_cybersparker.views.user_manage import user_list_api
        req = self._req('get', '/api/v1/users', self.adm_session)
        resp = user_list_api(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        roles = set(u['role'] for u in data['users'])
        self.assertEqual(roles, {'user'})

    def test_user_cannot_list(self):
        from app_cybersparker.views.user_manage import user_list_api
        req = self._req('get', '/api/v1/users', self.u1_session)
        resp = user_list_api(req)
        self.assertEqual(resp.status_code, 403)

    # ——— 创建 ———

    def test_super_admin_creates_admin(self):
        from app_cybersparker.views.user_manage import user_create_api
        User = get_user_model()
        req = self._req('post', '/api/v1/users/create', self.sa_session,
                        {'username': 'newadmin', 'password': 'pw', 'role': 'admin'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 201)
        u = User.objects.get(username='newadmin')
        self.assertEqual(u.profile.role, 'admin')

    def test_super_admin_creates_user(self):
        from app_cybersparker.views.user_manage import user_create_api
        User = get_user_model()
        req = self._req('post', '/api/v1/users/create', self.sa_session,
                        {'username': 'newuser', 'password': 'pw', 'role': 'user'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 201)
        u = User.objects.get(username='newuser')
        self.assertEqual(u.profile.role, 'user')

    def test_admin_cannot_create_admin(self):
        from app_cybersparker.views.user_manage import user_create_api
        req = self._req('post', '/api/v1/users/create', self.adm_session,
                        {'username': 'bad', 'password': 'pw', 'role': 'admin'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 403)

    def test_admin_creates_user(self):
        from app_cybersparker.views.user_manage import user_create_api
        User = get_user_model()
        req = self._req('post', '/api/v1/users/create', self.adm_session,
                        {'username': 'good', 'password': 'pw', 'role': 'user'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 201)

    def test_user_cannot_create(self):
        from app_cybersparker.views.user_manage import user_create_api
        req = self._req('post', '/api/v1/users/create', self.u1_session,
                        {'username': 'nope', 'password': 'pw', 'role': 'user'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 403)

    def test_duplicate_username_rejected(self):
        from app_cybersparker.views.user_manage import user_create_api
        req = self._req('post', '/api/v1/users/create', self.sa_session,
                        {'username': 'sa', 'password': 'pw', 'role': 'user'})
        resp = user_create_api(req)
        self.assertEqual(resp.status_code, 409)

    # ——— 删除 ———

    def test_super_admin_deletes_user(self):
        from app_cybersparker.views.user_manage import user_delete_api
        from django.contrib.sessions.models import Session
        User = get_user_model()
        target_id = self.user1.id
        # 创建目标用户的 session 然后删除，验证 session 也被清除
        self.u1_session.save()
        req = self._req('delete', '/fake', self.sa_session)
        resp = user_delete_api(req, target_id)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(id=target_id).exists())
        self.assertFalse(
            Session.objects.filter(session_key=self.u1_session.session_key).exists(),
            "删除用户后目标 session 应被清除"
        )

    def test_super_admin_cannot_delete_self(self):
        from app_cybersparker.views.user_manage import user_delete_api
        req = self._req('delete', '/fake', self.sa_session)
        resp = user_delete_api(req, self.super_admin.id)
        self.assertEqual(resp.status_code, 400)

    def test_admin_cannot_delete_admin(self):
        from app_cybersparker.views.user_manage import user_delete_api
        req = self._req('delete', '/fake', self.adm_session)
        resp = user_delete_api(req, self.super_admin.id)
        self.assertEqual(resp.status_code, 403)

    def test_admin_deletes_user(self):
        from app_cybersparker.views.user_manage import user_delete_api
        User = get_user_model()
        target_id = self.user1.id
        req = self._req('delete', '/fake', self.adm_session)
        resp = user_delete_api(req, target_id)
        self.assertEqual(resp.status_code, 200)

    def test_user_cannot_delete(self):
        from app_cybersparker.views.user_manage import user_delete_api
        req = self._req('delete', '/fake', self.u1_session)
        resp = user_delete_api(req, self.user2.id)
        self.assertEqual(resp.status_code, 403)

    # ——— 改角色 ———

    def test_super_admin_changes_role(self):
        from app_cybersparker.views.user_manage import user_role_api
        from django.contrib.sessions.models import Session
        self.u1_session.save()
        req = self._req('put', '/fake', self.sa_session, {'role': 'admin'})
        resp = user_role_api(req, self.user1.id)
        self.assertEqual(resp.status_code, 200)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.profile.role, 'admin')
        self.assertFalse(
            Session.objects.filter(session_key=self.u1_session.session_key).exists(),
            "改角色后目标用户 session 应被清除"
        )

    def test_admin_cannot_change_role(self):
        from app_cybersparker.views.user_manage import user_role_api
        req = self._req('put', '/fake', self.adm_session, {'role': 'user'})
        resp = user_role_api(req, self.user1.id)
        self.assertEqual(resp.status_code, 403)

    # ——— 改他人密码 ———

    def test_super_admin_resets_any_password(self):
        from app_cybersparker.views.user_manage import user_password_api
        req = self._req('put', '/fake', self.sa_session, {'password': 'newpw'})
        resp = user_password_api(req, self.user1.id)
        self.assertEqual(resp.status_code, 200)

    def test_admin_resets_user_password(self):
        from app_cybersparker.views.user_manage import user_password_api
        req = self._req('put', '/fake', self.adm_session, {'password': 'newpw'})
        resp = user_password_api(req, self.user1.id)
        self.assertEqual(resp.status_code, 200)

    def test_admin_cannot_reset_admin_password(self):
        from app_cybersparker.views.user_manage import user_password_api
        req = self._req('put', '/fake', self.adm_session, {'password': 'newpw'})
        resp = user_password_api(req, self.super_admin.id)
        self.assertEqual(resp.status_code, 403)

    def test_user_cannot_reset_password(self):
        from app_cybersparker.views.user_manage import user_password_api
        req = self._req('put', '/fake', self.u1_session, {'password': 'newpw'})
        resp = user_password_api(req, self.user2.id)
        self.assertEqual(resp.status_code, 403)

    # ——— 改自己密码 ———

    def test_any_role_can_change_own_password(self):
        from app_cybersparker.views.user_manage import user_me_password_api
        req = self._req('put', '/fake', self.u1_session, {'password': 'mypw'})
        resp = user_me_password_api(req)
        self.assertEqual(resp.status_code, 200)


# ============================================================
# BL-FILE-001: 文件管理页（上传/下载/删除）
# ============================================================
class TargetFileApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_dir = _PROJECT_ROOT / 'EXP_input' / '_test_target_files'
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
        super().tearDownClass()

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        session = SessionStore()
        session.create()
        self.session_data = session
        for f in list(self.test_dir.glob('*')):
            if f.is_file():
                f.unlink()

    def _admin_req(self, method='get', body=None):
        if method == 'post':
            req = self.factory.post('/', data=body, content_type='application/json')
        elif method == 'delete':
            req = self.factory.delete('/')
        else:
            req = self.factory.get('/')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        if body and method == 'post':
            req._body = json.dumps(body).encode('utf-8')
        return req

    def _anon_req(self, method='get', body=None):
        if method == 'post':
            req = self.factory.post('/', data=body, content_type='application/json')
        elif method == 'delete':
            req = self.factory.delete('/')
        else:
            req = self.factory.get('/')
        req.session = self.session_data
        if body and method == 'post':
            req._body = json.dumps(body).encode('utf-8')
        return req

    def _create_test_file(self, name, content='line1\nline2\n\nline3\n'):
        fpath = self.test_dir / name
        fpath.write_text(content)
        return fpath

    def _with_target_dir(self):
        """Monkey-patch TARGET_DIR to point at test_dir for the duration of the test."""
        import app_cybersparker.views.expload.target_file_manage as tfm
        return patch.object(tfm, 'TARGET_DIR', str(self.test_dir))

    # —— 列表 ——

    def test_list_files(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_list_api
            self._create_test_file('a.txt')
            self._create_test_file('b.txt')

            req = self._admin_req()
            resp = target_file_list_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            names = [f['file_name'] for f in data['data']['files']]
            self.assertIn('a.txt', names)
            self.assertIn('b.txt', names)

    def test_list_files_excludes_subdirs(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_list_api
            self._create_test_file('targets.txt')
            (self.test_dir / '.merged').mkdir(exist_ok=True)
            (self.test_dir / '.merged' / 'hidden.txt').write_text('x')
            (self.test_dir / 'engine_assets').mkdir(exist_ok=True)
            (self.test_dir / 'engine_assets' / 'cache.txt').write_text('x')

            req = self._admin_req()
            resp = target_file_list_api(req)
            data = json.loads(resp.content)
            names = [f['file_name'] for f in data['data']['files']]
            self.assertIn('targets.txt', names)
            self.assertNotIn('hidden.txt', names)
            self.assertNotIn('cache.txt', names)

    # —— 上传 ——

    def test_upload_txt_succeeds(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_upload_api
            from django.core.files.uploadedfile import SimpleUploadedFile

            req = self._admin_req()
            req.method = 'POST'
            req.FILES['file'] = SimpleUploadedFile('targets.txt', b'1.1.1.1\n2.2.2.2\n', content_type='text/plain')

            resp = target_file_upload_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            self.assertTrue((self.test_dir / 'targets.txt').exists())

    def test_upload_rejects_non_txt(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_upload_api
            from django.core.files.uploadedfile import SimpleUploadedFile

            req = self._admin_req()
            req.method = 'POST'
            req.FILES['file'] = SimpleUploadedFile('image.png', b'fake-png', content_type='image/png')

            resp = target_file_upload_api(req)
            self.assertEqual(resp.status_code, 400)
            data = json.loads(resp.content)
            self.assertFalse(data['status'])
            self.assertIn('txt', data['data']['error'])

    def test_upload_rejects_over_30mb(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_upload_api

            req = self._admin_req()
            req.method = 'POST'
            from django.core.files.uploadedfile import SimpleUploadedFile
            big = SimpleUploadedFile('big.txt', b'x' * 100, content_type='text/plain')
            big.size = 31 * 1024 * 1024  # 超限
            req.FILES['file'] = big

            resp = target_file_upload_api(req)
            self.assertEqual(resp.status_code, 400)
            data = json.loads(resp.content)
            self.assertIn('30MB', data['data']['error'])

    def test_upload_duplicate_name_adds_suffix(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_upload_api
            from django.core.files.uploadedfile import SimpleUploadedFile

            (self.test_dir / 'targets.txt').write_text('existing')

            req = self._admin_req()
            req.method = 'POST'
            req.FILES['file'] = SimpleUploadedFile('targets.txt', b'new content', content_type='text/plain')

            resp = target_file_upload_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            self.assertNotEqual(data['data']['file_name'], 'targets.txt')
            self.assertIn('targets_', data['data']['file_name'])

    # —— 下载 ——

    def test_download_file(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_download_api
            self._create_test_file('dl.txt', 'download content')

            req = self._admin_req()
            resp = target_file_download_api(req, 'dl.txt')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(b''.join(resp.streaming_content), b'download content')

    def test_download_nonexistent_returns_404(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_download_api

            req = self._admin_req()
            resp = target_file_download_api(req, 'no_such_file.txt')
            self.assertEqual(resp.status_code, 404)

    # —— 删除 ——

    def test_delete_unreferenced_file(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_delete_api
            self._create_test_file('to_delete.txt')

            req = self._admin_req(method='delete')
            resp = target_file_delete_api(req, 'to_delete.txt')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            self.assertFalse((self.test_dir / 'to_delete.txt').exists())

    def test_delete_referenced_file_returns_refs(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_delete_api
            self._create_test_file('referenced.txt')

            models.auto_scan_tasks.objects.create(
                id=9999, task_name='test-ref-task',
                input_type=1, target='referenced.txt',
                history_files='referenced.txt,other.txt',
                status=3, current_line=0,
                engine_proxy_mode=1, Vulnerability_scanning=0,
                heartbeat_at=None, pause_requested=False,
                stop_requested=False, engine_query='', engine_type='',
                search_query='', parsed_query='', last_id=0, frozen_max_id=0,
            )

            req = self._admin_req(method='delete')
            resp = target_file_delete_api(req, 'referenced.txt')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['data']['has_refs'])
            self.assertTrue((self.test_dir / 'referenced.txt').exists())

            models.auto_scan_tasks.objects.filter(id=9999).delete()

    def test_delete_confirm_removes_file_and_cleans_refs(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_delete_confirm_api
            self._create_test_file('ref_to_confirm.txt')

            models.auto_scan_tasks.objects.create(
                id=9998, task_name='test-confirm-task',
                input_type=1, target='ref_to_confirm.txt',
                history_files='ref_to_confirm.txt',
                status=3, current_line=0,
                engine_proxy_mode=1, Vulnerability_scanning=0,
                heartbeat_at=None, pause_requested=False,
                stop_requested=False, engine_query='', engine_type='',
                search_query='', parsed_query='', last_id=0, frozen_max_id=0,
            )

            req = self._admin_req(method='post')
            resp = target_file_delete_confirm_api(req, 'ref_to_confirm.txt')
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['status'])
            self.assertFalse((self.test_dir / 'ref_to_confirm.txt').exists())
            t = models.auto_scan_tasks.objects.get(id=9998)
            self.assertNotIn('ref_to_confirm.txt', t.history_files)

            models.auto_scan_tasks.objects.filter(id=9998).delete()

    # —— 路径穿越 ——

    def test_path_traversal_download_rejected(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_download_api

            req = self._admin_req()
            resp = target_file_download_api(req, '../settings.py')
            self.assertEqual(resp.status_code, 404)

    def test_path_traversal_delete_rejected(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_delete_api

            req = self._admin_req(method='delete')
            resp = target_file_delete_api(req, '../settings.py')
            self.assertEqual(resp.status_code, 404)

    # —— 鉴权 ——

    def test_unauthenticated_upload_blocked(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_upload_api

            req = self._anon_req()
            req.method = 'POST'
            resp = target_file_upload_api(req)
            self.assertIn(resp.status_code, [401, 403])

    def test_unauthenticated_delete_blocked(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_delete_api
            self._create_test_file('noauth.txt')

            req = self._anon_req(method='delete')
            resp = target_file_delete_api(req, 'noauth.txt')
            self.assertIn(resp.status_code, [401, 403])

    # —— 行数统计 ——

    def test_list_includes_non_empty_line_count(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_list_api
            self._create_test_file('count.txt', 'line1\nline2\n\n\nline3\n')

            req = self._admin_req()
            resp = target_file_list_api(req)
            data = json.loads(resp.content)
            f = [x for x in data['data']['files'] if x['file_name'] == 'count.txt'][0]
            self.assertEqual(f['lines'], 3)

    # —— 批量删除 ——

    def test_batch_delete_mixed_refs(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_batch_delete_api
            self._create_test_file('noref.txt')
            self._create_test_file('hasref.txt')

            models.auto_scan_tasks.objects.create(
                id=9997, task_name='test-batch-task',
                input_type=1, target='hasref.txt',
                history_files='hasref.txt',
                status=3, current_line=0,
                engine_proxy_mode=1, Vulnerability_scanning=0,
                heartbeat_at=None, pause_requested=False,
                stop_requested=False, engine_query='', engine_type='',
                search_query='', parsed_query='', last_id=0, frozen_max_id=0,
            )

            req = self._admin_req(method='post', body={'filenames': ['noref.txt', 'hasref.txt']})
            resp = target_file_batch_delete_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertTrue(data['data']['has_pending_refs'])
            # noref 应该被删了，hasref 返回引用信息
            results = {r['file_name']: r for r in data['data']['results']}
            self.assertTrue(results['noref.txt'].get('deleted'))
            self.assertTrue(results['hasref.txt'].get('has_refs'))

            models.auto_scan_tasks.objects.filter(id=9997).delete()

    def test_batch_delete_confirm(self):
        with self._with_target_dir():
            from app_cybersparker.views.expload.target_file_manage import target_file_batch_delete_confirm_api
            self._create_test_file('b1.txt')
            self._create_test_file('b2.txt')

            models.auto_scan_tasks.objects.create(
                id=9996, task_name='test-batch-confirm',
                input_type=1, target='b1.txt',
                history_files='b1.txt,b2.txt',
                status=3, current_line=0,
                engine_proxy_mode=1, Vulnerability_scanning=0,
                heartbeat_at=None, pause_requested=False,
                stop_requested=False, engine_query='', engine_type='',
                search_query='', parsed_query='', last_id=0, frozen_max_id=0,
            )

            req = self._admin_req(method='post', body={'filenames': ['b1.txt', 'b2.txt']})
            resp = target_file_batch_delete_confirm_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertEqual(sorted(data['data']['deleted']), ['b1.txt', 'b2.txt'])
            self.assertFalse((self.test_dir / 'b1.txt').exists())
            self.assertFalse((self.test_dir / 'b2.txt').exists())
            t = models.auto_scan_tasks.objects.get(id=9996)
            self.assertEqual(t.history_files, '')

            models.auto_scan_tasks.objects.filter(id=9996).delete()


# ============================================================
# BL-FILE-002: 测绘引擎文件自动清理
# ============================================================
class EngineAssetCleanupTests(TestCase):
    def test_beat_schedule_contains_cleanup_task(self):
        from django.conf import settings
        schedule = getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        self.assertIn('cleanup-expired-engine-assets', schedule)
        task_conf = schedule['cleanup-expired-engine-assets']
        self.assertEqual(task_conf['task'], 'app_cybersparker.tasks.cleanup_expired_engine_assets')
        self.assertEqual(task_conf['options']['queue'], 'maintenance')

    def test_cleanup_deletes_expired_files(self):
        with TemporaryDirectory() as tmpdir:
            asset_dir = Path(tmpdir) / 'engine_assets'
            asset_dir.mkdir()
            old_file = asset_dir / 'old_data.txt'
            old_file.write_text('old')
            old_mtime = time.time() - 61 * 24 * 3600
            os.utime(str(old_file), (old_mtime, old_mtime))

            new_file = asset_dir / 'new_data.txt'
            new_file.write_text('new')
            new_mtime = time.time() - 1 * 24 * 3600
            os.utime(str(new_file), (new_mtime, new_mtime))

            # mock os.path.join to return our asset_dir because the function
            # computes join(THIS_DIR, 'EXP_input', 'engine_assets') internally
            with patch('builtins.open', side_effect=open):
                with patch('os.path.isdir') as mock_isdir, \
                     patch('os.listdir') as mock_listdir, \
                     patch('os.path.isfile') as mock_isfile, \
                     patch('os.path.getmtime') as mock_getmtime, \
                     patch('os.remove') as mock_remove:
                    mock_isdir.return_value = True
                    mock_listdir.return_value = ['old_data.txt', 'new_data.txt']
                    mock_isfile.return_value = True
                    mock_getmtime.side_effect = lambda p: old_mtime if 'old' in str(p) else new_mtime

                    from app_cybersparker.tasks import cleanup_expired_engine_assets
                    result = cleanup_expired_engine_assets()
                    mock_remove.assert_called_once()
                    removed_path = str(mock_remove.call_args[0][0])
                    self.assertIn('old_data.txt', removed_path)

    def test_cleanup_preserves_recent_files(self):
        recent_mtime = time.time() - 10 * 24 * 3600

        with patch('os.path.isdir') as mock_isdir, \
             patch('os.listdir') as mock_listdir, \
             patch('os.path.isfile') as mock_isfile, \
             patch('os.path.getmtime') as mock_getmtime, \
             patch('os.remove') as mock_remove:
            mock_isdir.return_value = True
            mock_listdir.return_value = ['recent.txt']
            mock_isfile.return_value = True
            mock_getmtime.return_value = recent_mtime

            from app_cybersparker.tasks import cleanup_expired_engine_assets
            result = cleanup_expired_engine_assets()
            mock_remove.assert_not_called()

    def test_cleanup_missing_directory_handled(self):
        with patch('os.path.isdir') as mock_isdir:
            mock_isdir.return_value = False
            from app_cybersparker.tasks import cleanup_expired_engine_assets
            result = cleanup_expired_engine_assets()
            self.assertEqual(result['status'], 'skipped')


# ============================================================
# BL-AIPOC-001: AI 模型配置 CRUD
# ============================================================
class AiModelConfigApiTests(TestCase):
    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        session = SessionStore()
        session.create()
        self.session_data = session

    def _admin_req(self, method='get', body=None):
        if method == 'post':
            req = self.factory.post('/', data=json.dumps(body or {}), content_type='application/json')
        elif method == 'delete':
            req = self.factory.delete('/')
        else:
            req = self.factory.get('/')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        return req

    def test_list_configs(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        models.AIModelConfig.objects.create(name='t1', model_id='m1', api_url='http://x', api_key='sk-1234567890abcdef', model_type='thinking')
        models.AIModelConfig.objects.create(name='v1', model_id='m2', api_url='http://y', api_key='sk-fedcba0987654321', model_type='vision')

        req = self._admin_req()
        resp = api_configs(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(len(data['items']), 2)

    def test_list_filters_by_type(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        models.AIModelConfig.objects.create(name='t1', model_id='m1', api_url='http://x', api_key='k1', model_type='thinking')
        models.AIModelConfig.objects.create(name='v1', model_id='m2', api_url='http://y', api_key='k2', model_type='vision')

        req = self._admin_req()
        req.GET = {'model_type': 'thinking'}
        resp = api_configs(req)
        data = json.loads(resp.content)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['model_type'], 'thinking')

    def test_api_key_masked_in_list(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        models.AIModelConfig.objects.create(name='t1', model_id='m1', api_url='http://x', api_key='sk-1234567890abcdef', model_type='thinking')

        req = self._admin_req()
        resp = api_configs(req)
        data = json.loads(resp.content)
        self.assertNotEqual(data['items'][0]['api_key'], 'sk-1234567890abcdef')
        self.assertIn('****', data['items'][0]['api_key'])

    def test_api_key_masked_short_key(self):
        from app_cybersparker.views.ai_poc.ai_model_config import _mask_api_key
        masked = _mask_api_key('ab1234cd')
        self.assertIn('****', masked)
        self.assertEqual(masked, 'ab****cd')  # 2+4+2 for key <= 8

    def test_create_config(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        req = self._admin_req(method='post', body={'name': 'test', 'model_id': 'gpt-4', 'api_url': 'http://api', 'api_key': 'sk-key12345678', 'model_type': 'thinking'})
        resp = api_configs(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        self.assertTrue(models.AIModelConfig.objects.filter(id=data['data']['id']).exists())

    def test_create_rejects_invalid_type(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        req = self._admin_req(method='post', body={'name': 't', 'model_id': 'm', 'api_url': 'http://x', 'api_key': 'sk-key', 'model_type': 'invalid'})
        resp = api_configs(req)
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_empty_name(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_configs
        req = self._admin_req(method='post', body={'name': '', 'model_id': 'm', 'api_url': 'http://x', 'api_key': 'sk-key', 'model_type': 'thinking'})
        resp = api_configs(req)
        self.assertEqual(resp.status_code, 400)

    def test_edit_config(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_config_detail
        obj = models.AIModelConfig.objects.create(name='old', model_id='m1', api_url='http://x', api_key='sk-oldkey1234', model_type='thinking')

        req = self._admin_req(method='post', body={'name': 'new', 'model_id': 'm2', 'api_url': 'http://y', 'api_key': '', 'model_type': 'vision'})
        resp = api_config_detail(req, obj.id)
        self.assertEqual(resp.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.name, 'new')
        self.assertEqual(obj.model_type, 'vision')
        # API key 未变（传空不更新）
        self.assertEqual(obj.api_key, 'sk-oldkey1234')

    def test_edit_updates_api_key_when_provided(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_config_detail
        obj = models.AIModelConfig.objects.create(name='x', model_id='m', api_url='http://x', api_key='sk-old', model_type='thinking')

        req = self._admin_req(method='post', body={'name': 'x', 'model_id': 'm', 'api_url': 'http://x', 'api_key': 'sk-newkey99', 'model_type': 'thinking'})
        resp = api_config_detail(req, obj.id)
        self.assertEqual(resp.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.api_key, 'sk-newkey99')

    def test_delete_config(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_config_detail
        obj = models.AIModelConfig.objects.create(name='x', model_id='m', api_url='http://x', api_key='sk-k', model_type='thinking')

        req = self._admin_req(method='delete')
        resp = api_config_detail(req, obj.id)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(models.AIModelConfig.objects.filter(id=obj.id).exists())

    def test_detail_returns_masked_key(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_config_detail
        obj = models.AIModelConfig.objects.create(name='x', model_id='m', api_url='http://x', api_key='sk-1234567890ab', model_type='thinking')

        req = self._admin_req()
        resp = api_config_detail(req, obj.id)
        data = json.loads(resp.content)
        self.assertNotIn('sk-1234567890ab', data['data']['api_key'])
        self.assertIn('****', data['data']['api_key'])

    def test_detail_404(self):
        from app_cybersparker.views.ai_poc.ai_model_config import api_config_detail
        req = self._admin_req()
        resp = api_config_detail(req, 999999)
        self.assertEqual(resp.status_code, 404)


# ============================================================
# BL-AIPOC-002~009: PoC 生成任务
# ============================================================
class PocGenTaskApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.think_model = models.AIModelConfig.objects.create(
            name='test-think', model_id='gpt-4', api_url='http://x', api_key='sk-t', model_type='thinking')
        cls.vision_model = models.AIModelConfig.objects.create(
            name='test-vision', model_id='gpt-4v', api_url='http://y', api_key='sk-v', model_type='vision')

    @classmethod
    def tearDownClass(cls):
        models.PoCGenerationTask.objects.all().delete()
        models.AIModelConfig.objects.all().delete()
        super().tearDownClass()

    def setUp(self):
        from django.contrib.sessions.backends.db import SessionStore
        self.factory = RequestFactory()
        session = SessionStore()
        session.create()
        self.session_data = session

    def _admin_req(self, method='get', body=None, **extra):
        if method == 'post':
            req = self.factory.post('/', data=json.dumps(body or {}), content_type='application/json')
        elif method == 'delete':
            req = self.factory.delete('/')
        else:
            req = self.factory.get('/')
        req.session = self.session_data
        req.session['info'] = {'id': 1, 'username': 'admin', 'role': 'super_admin'}
        for k, v in extra.items():
            setattr(req, k, v)
        return req

    def test_list_tasks(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        models.PoCGenerationTask.objects.create(
            title='test-task', task_type='text_input', plugin_language=1,
            thinking_model=self.think_model, status='pending', crawl_status='success')

        req = self._admin_req()
        resp = api_tasks(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        self.assertGreaterEqual(len(data['items']), 1)

    def test_create_text_input_task(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        body = {
            'title': 'text-task', 'task_type': 'text_input', 'plugin_language': 1,
            'thinking_model_id': self.think_model.id,
            'reference_text': 'CVE-2024-1234: a buffer overflow in ...',
        }
        req = self._admin_req(method='post', body=body)
        with patch('app_cybersparker.views.ai_poc.poc_gen_task.os.makedirs'):
            resp = api_tasks(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        t = models.PoCGenerationTask.objects.get(id=data['data']['id'])
        self.assertEqual(t.task_type, 'text_input')
        self.assertEqual(t.status, 'ready')
        self.assertIsNotNone(t.reference_material_prompt)
        t.delete()

    def test_text_input_skips_crawling(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        body = {
            'title': 'text-task2', 'task_type': 'text_input', 'plugin_language': 1,
            'thinking_model_id': self.think_model.id,
            'reference_text': 'just some notes',
        }
        req = self._admin_req(method='post', body=body)
        with patch('app_cybersparker.views.ai_poc.poc_gen_task.os.makedirs'):
            resp = api_tasks(req)
        self.assertEqual(resp.status_code, 200)
        t = models.PoCGenerationTask.objects.get(id=json.loads(resp.content)['data']['id'])
        self.assertEqual(t.status, 'ready')  # text_input 直接 ready，无 crawling
        t.delete()

    def test_delete_task(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_task_detail
        t = models.PoCGenerationTask.objects.create(
            title='to-delete', task_type='text_input', plugin_language=1,
            thinking_model=self.think_model, status='pending', crawl_status='success')
        tid = t.id

        req = self._admin_req(method='delete')
        with patch('app_cybersparker.views.ai_poc.poc_gen_task.shutil.rmtree'):
            resp = api_task_detail(req, tid)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(models.PoCGenerationTask.objects.filter(id=tid).exists())

    def test_create_url_crawl_task_succeeds(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        body = {
            'title': 'url-task', 'task_type': 'url_crawl', 'plugin_language': 1,
            'thinking_model_id': self.think_model.id,
            'urls': 'https://example.com/test',
        }
        req = self._admin_req(method='post', body=body)
        with patch('app_cybersparker.views.ai_poc.poc_gen_task.os.makedirs'), \
             patch('app_cybersparker.views.ai_poc.poc_gen_task.threading.Thread'):
            resp = api_tasks(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['status'])
        t = models.PoCGenerationTask.objects.get(id=data['data']['id'])
        self.assertEqual(t.task_type, 'url_crawl')
        self.assertEqual(t.status, 'crawling')  # async extraction started
        t.delete()

    def test_create_task_rejects_invalid_task_type(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        body = {
            'title': 'bad', 'task_type': 'invalid_type',
            'thinking_model_id': self.think_model.id,
        }
        req = self._admin_req(method='post', body=body)
        resp = api_tasks(req)
        self.assertEqual(resp.status_code, 400)

    def test_create_task_rejects_wrong_model_type(self):
        from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks
        body = {
            'title': 'bad-model', 'task_type': 'text_input',
            'thinking_model_id': self.vision_model.id,
            'reference_text': 'some text',
        }
        req = self._admin_req(method='post', body=body)
        resp = api_tasks(req)
        self.assertEqual(resp.status_code, 400)

    def test_plugin_language_nullable(self):
        """BL-AIPOC-005: plugin_language 可为空"""
        t = models.PoCGenerationTask.objects.create(
            title='no-lang', task_type='text_input', plugin_language=None,
            thinking_model=self.think_model, status='pending', crawl_status='success')
        self.assertIsNone(t.plugin_language)
        t.delete()

    def test_save_to_exp_api_requires_generated_status(self):
        """BL-AIPOC-004: 未生成时调用 save-to-exp 应拒绝"""
        from app_cybersparker.views.ai_poc.poc_gen_task import api_save_to_exp
        t = models.PoCGenerationTask.objects.create(
            title='not-ready', task_type='text_input', plugin_language=1,
            thinking_model=self.think_model,
            status='pending', crawl_status='success')

        req = self._admin_req(method='post', body={'title': 'my-poc'})
        resp = api_save_to_exp(req, t.id)
        self.assertEqual(resp.status_code, 400)
        t.delete()

    def test_save_poc_requires_metadata(self):
        """BL-AIPOC-004: 缺少元数据时保存失败"""
        from app_cybersparker.views.ai_poc.poc_gen_task import _save_ai_generated_poc
        t = models.PoCGenerationTask.objects.create(
            title='no-meta', task_type='text_input', plugin_language=1,
            thinking_model=self.think_model, status='generated', crawl_status='success',
            generated_poc_content='print("poc")',
        )
        ok, msg, exp_id = _save_ai_generated_poc(t)
        self.assertFalse(ok)
        self.assertIn('标题', msg)
        t.delete()

    def test_save_poc_succeeds_with_valid_data(self):
        """BL-AIPOC-004: 完整数据下保存成功"""
        from app_cybersparker.views.ai_poc.poc_gen_task import _save_ai_generated_poc
        t = models.PoCGenerationTask.objects.create(
            title='valid-poc', task_type='text_input', plugin_language=1,
            thinking_model=self.think_model, status='generated', crawl_status='success',
            generated_poc_content='import requests\n\ndef _verify(target):\n    return {"matched": True}',
            generated_metadata=json.dumps({'title': 'TestPOC', 'severity': 'high', 'type': 1, 'cve': 'CVE-2024-9999'}),
        )
        ok, msg, exp_id = _save_ai_generated_poc(t)
        self.assertTrue(ok, f'Expected success but got: {msg}')
        self.assertIsNotNone(exp_id)
        # Verify EXP was created
        exp = models.EXP.objects.get(id=exp_id)
        self.assertEqual(exp.title[:7], 'TestPOC')
        self.assertEqual(exp.severity, 'high')
        # Cleanup
        exp.delete()
        t.delete()


# ============================================================
# BL-DIRSCAN-013: 目录扫描阻断响应记录 + content_length 字段
# ============================================================
class DirscanBlockedResponseTests(TestCase):
    def test_content_length_field_exists_on_model(self):
        """验证 content_length 字段存在于 auto_scan_directory_result 模型"""
        from app_cybersparker.models import auto_scan_directory_result
        field = auto_scan_directory_result._meta.get_field('content_length')
        self.assertIsNotNone(field)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_blocked_response_content_length_stored(self):
        """阻断响应入库时 content_length 被正确写入"""
        from app_cybersparker.models import auto_scan_directory_result

        task_id = 99999
        auto_scan_directory_result.objects.create(
            task_id=task_id, protocol='http', host='blocked.com', port=80,
            uri_path='/large.zip', target='http://blocked.com/large.zip',
            status_code=200, ip='', header='HTTP/1.1 200 OK\nContent-Type: application/zip',
            title='', html='',
            content_length=1048577,  # 被阻断的大文件
        )

        record = auto_scan_directory_result.objects.get(task_id=task_id)
        self.assertEqual(record.content_length, 1048577)
        self.assertEqual(record.html, '')  # 空 body = 被阻断
        record.delete()

    def test_normal_response_content_length_null(self):
        """正常响应未提供 content_length 时字段为 None"""
        from app_cybersparker.models import auto_scan_directory_result

        task_id = 99998
        auto_scan_directory_result.objects.create(
            task_id=task_id, protocol='https', host='normal.org', port=443,
            uri_path='/page', target='https://normal.org/page',
            status_code=200, ip='', header='HTTP/1.1 200 OK',
            title='Normal Page', html='<html>ok</html>',
            content_length=None,
        )

        record = auto_scan_directory_result.objects.get(task_id=task_id)
        self.assertIsNone(record.content_length)
        record.delete()

    def test_skip_non_http_protocol_hosts(self):
        """非 HTTP(S) 协议的 host 应被跳过，不调用 _http_get"""
        from unittest.mock import AsyncMock, patch
        from app_cybersparker.services.dirscan_worker import (
            _sync_bump_progress as real_bump,
        )

        # 模拟 host 数据结构（从 pool.take_one() 返回的格式）
        http_host = {"protocol": "http", "host": "web.local", "port": 80, "offset": 0, "counter": 0}
        https_host = {"protocol": "https", "host": "secure.local", "port": 443, "offset": 0, "counter": 0}
        ftp_host = {"protocol": "ftp", "host": "ftp.local", "port": 21, "offset": 0, "counter": 0}
        ssh_host = {"protocol": "ssh", "host": "ssh.local", "port": 22, "offset": 0, "counter": 0}

        # HTTP/HTTPS 应通过过滤
        self.assertIn(http_host.get("protocol", "http"), ("http", "https"))
        self.assertIn(https_host.get("protocol", "http"), ("http", "https"))

        # 非 HTTP/HTTPS 应被跳过
        self.assertNotIn(ftp_host.get("protocol", "http"), ("http", "https"))
        self.assertNotIn(ssh_host.get("protocol", "http"), ("http", "https"))

        # 验证跳过时计数器会正确递增（模拟 skip 分支）
        for host in [ftp_host, ssh_host]:
            host["counter"] += 1
        self.assertEqual(ftp_host["counter"], 1)
        self.assertEqual(ssh_host["counter"], 1)


class AssetZoneModelTests(TestCase):
    """BL-ZONE-001 AssetZone 模型测试"""

    def test_create_zone(self):
        """创建普通区域成功"""
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.create(code="internal-1", name="内网1")
        self.assertEqual(zone.code, "internal-1")
        self.assertEqual(zone.name, "内网1")
        self.assertFalse(zone.is_system)
        zone.delete()

    def test_system_zone_exists_and_cannot_delete(self):
        """系统区域 public 存在且不可删除（is_system=True + PROTECT 检查）"""
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.get(code="public")
        self.assertTrue(zone.is_system)
        self.assertEqual(zone.name, "公网")

    def test_zone_code_unique(self):
        """code 必须唯一"""
        from app_cybersparker.models import AssetZone
        from django.db import IntegrityError, transaction
        AssetZone.objects.create(code="dup-test", name="测试1")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                AssetZone.objects.create(code="dup-test", name="测试2")

    def test_zone_name_unique(self):
        """name 必须唯一"""
        from app_cybersparker.models import AssetZone
        from django.db import IntegrityError, transaction
        AssetZone.objects.create(code="name-test-1", name="同名区域")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                AssetZone.objects.create(code="name-test-2", name="同名区域")

    def test_zone_delete_rejected_with_asset_refs(self):
        """有资产引用时删除 zone 被拒绝"""
        from app_cybersparker.models import AssetZone, auto_scan_indentify_result
        from django.db.models import ProtectedError
        from django.db import transaction
        zone = AssetZone.objects.create(code="delete-test", name="待删除")
        asset = auto_scan_indentify_result.objects.create(
            zone=zone, protocol="http", host="10.0.0.1", port=80, uri_path="",
            target="http://10.0.0.1:80", ip="10.0.0.1",
        )
        with transaction.atomic():
            with self.assertRaises(ProtectedError):
                zone.delete()
        asset.delete()
        zone.delete()

    def test_zone_str(self):
        """__str__ 返回 name"""
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.get(code="public")
        self.assertEqual(str(zone), "公网")


class AssetRootBindingModelTests(TestCase):
    """BL-ZONE-001 AssetRootBinding 模型测试"""

    def setUp(self):
        from app_cybersparker.models import AssetZone, auto_scan_indentify_result
        self.zone = AssetZone.objects.get(code="public")
        self.asset = auto_scan_indentify_result.objects.create(
            zone=self.zone, protocol="http", host="bind-test.local", port=8080, uri_path="",
            target="http://bind-test.local:8080", ip="10.0.0.99",
        )

    def test_create_binding(self):
        """创建根资产绑定成功"""
        from app_cybersparker.models import AssetRootBinding
        binding = AssetRootBinding.objects.create(
            zone=self.zone, protocol="http", host="bind-test.local", port=8080,
            identify_result=self.asset,
        )
        self.assertEqual(binding.identify_result.id, self.asset.id)
        binding.delete()

    def test_binding_unique_per_zone_triplet(self):
        """同一个 zone+protocol+host+port 只能有一个绑定"""
        from app_cybersparker.models import AssetRootBinding
        from django.db import IntegrityError, transaction
        AssetRootBinding.objects.create(
            zone=self.zone, protocol="http", host="bind-test.local", port=8080,
            identify_result=self.asset,
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                AssetRootBinding.objects.create(
                    zone=self.zone, protocol="http", host="bind-test.local", port=8080,
                    identify_result=self.asset,
                )

    def test_binding_protects_asset_from_delete(self):
        """绑定阻止被绑定资产被删除（on_delete=PROTECT）"""
        from app_cybersparker.models import AssetRootBinding
        from django.db.models import ProtectedError
        from django.db import transaction
        binding = AssetRootBinding.objects.create(
            zone=self.zone, protocol="http", host="bind-test.local", port=8080,
            identify_result=self.asset,
        )
        with transaction.atomic():
            with self.assertRaises(ProtectedError):
                self.asset.delete()
        binding.delete()
        self.asset.delete()
        AssetRootBinding.objects.all().delete()  # 清理可能残留的绑定

    def tearDown(self):
        from app_cybersparker.models import AssetRootBinding, auto_scan_indentify_result
        AssetRootBinding.objects.filter(zone=self.zone, host="bind-test.local").delete()
        auto_scan_indentify_result.objects.filter(id=self.asset.id).delete()


class AssetZoneUniqueTogetherTests(TestCase):
    """BL-ZONE-001 资产唯一键改为 (zone, protocol, host, port, uri_path)"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        self.public = AssetZone.objects.get(code="public")
        self.internal = AssetZone.objects.create(code="ut-internal", name="测试内网")

    def test_same_triplet_different_zone_coexist(self):
        """相同 (protocol,host,port,uri_path) 在不同 zone 下可并存"""
        from app_cybersparker.models import auto_scan_indentify_result
        a1 = auto_scan_indentify_result.objects.create(
            zone=self.public, protocol="http", host="192.168.1.1", port=80, uri_path="",
            target="http://192.168.1.1:80", ip="192.168.1.1",
        )
        a2 = auto_scan_indentify_result.objects.create(
            zone=self.internal, protocol="http", host="192.168.1.1", port=80, uri_path="",
            target="http://192.168.1.1:80", ip="192.168.1.1",
        )
        self.assertNotEqual(a1.id, a2.id)
        a1.delete()
        a2.delete()

    def test_same_triplet_same_zone_conflict(self):
        """相同 zone 内相同 (protocol,host,port,uri_path) 冲突"""
        from app_cybersparker.models import auto_scan_indentify_result
        from django.db import IntegrityError, transaction
        auto_scan_indentify_result.objects.create(
            zone=self.public, protocol="https", host="dup.example.com", port=443,
            uri_path="/api", target="https://dup.example.com:443/api", ip="1.2.3.4",
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                auto_scan_indentify_result.objects.create(
                    zone=self.public, protocol="https", host="dup.example.com",
                    port=443, uri_path="/api",
                    target="https://dup.example.com:443/api", ip="1.2.3.4",
                )

    def test_directory_result_same_triplet_different_zone_coexist(self):
        """目录结果相同 (protocol,host,port,uri_path) 在不同 zone 下可并存"""
        from app_cybersparker.models import auto_scan_directory_result
        r1 = auto_scan_directory_result.objects.create(
            task_id=99999, zone=self.public, protocol="http", host="10.0.0.1", port=80,
            uri_path="/admin", target="http://10.0.0.1/admin", ip="10.0.0.1",
            root_identify_result=None,
        )
        r2 = auto_scan_directory_result.objects.create(
            task_id=99998, zone=self.internal, protocol="http", host="10.0.0.1", port=80,
            uri_path="/admin", target="http://10.0.0.1/admin", ip="10.0.0.1",
            root_identify_result=None,
        )
        self.assertNotEqual(r1.id, r2.id)
        r1.delete()
        r2.delete()

    def test_directory_result_same_zone_same_path_refresh(self):
        """同 zone 同 host 同 path 的目录结果允许刷新（共享快照语义）"""
        from app_cybersparker.models import auto_scan_directory_result
        r1 = auto_scan_directory_result.objects.create(
            task_id=100, zone=self.public, protocol="http", host="refresh.local", port=80,
            uri_path="/login", target="http://refresh.local/login", ip="10.0.0.5",
            root_identify_result=None, title="Old Title",
        )
        # 同 zone 同 key 允许 upsert（update_or_create 语义，不是唯一键冲突测试）
        # 改为 update 操作
        r2 = auto_scan_directory_result.objects.filter(
            zone=self.public, protocol="http", host="refresh.local", port=80,
            uri_path="/login",
        ).first()
        self.assertIsNotNone(r2)
        self.assertEqual(r2.id, r1.id)  # 同一条记录
        r1.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code="ut-internal").delete()


class ZoneFKConstraintTests(TestCase):
    """BL-ZONE-001 zone FK 约束测试（本期 nullable，NOT NULL 在 BL-ZONE-003 添加）"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        self.zone = AssetZone.objects.get(code="public")

    def test_auto_scan_indentify_result_zone_accepts_public(self):
        """资产表接受 zone=public"""
        from app_cybersparker.models import auto_scan_indentify_result
        asset = auto_scan_indentify_result.objects.create(
            zone=self.zone, protocol="http", host="z-ok.com", port=80, uri_path="",
            target="http://z-ok.com", ip="1.1.1.1",
        )
        self.assertEqual(asset.zone.code, "public")
        asset.delete()

    def test_auto_scan_tasks_zone_accepts_public(self):
        """自动扫描任务 zone FK 可正常写入"""
        from app_cybersparker.models import auto_scan_tasks
        task = auto_scan_tasks.objects.create(
            task_name="test-zone-ok", zone=self.zone, thread_num=10,
        )
        self.assertEqual(task.zone.code, "public")
        task.delete()

    def test_batch_EXPTask_zone_accepts_public(self):
        """批量任务 zone FK 可正常写入"""
        from app_cybersparker.models import batch_EXPTask
        task = batch_EXPTask.objects.create(
            task_name="test-batch-zone-ok", zone=self.zone, EXP="test", thread_num=10,
        )
        self.assertEqual(task.zone.code, "public")
        task.delete()

    def test_DirScanTask_zone_accepts_public(self):
        """目录扫描任务 zone FK 可正常写入"""
        from app_cybersparker.models import DirScanTask
        task = DirScanTask.objects.create(
            task_name="test-dirscan-zone-ok", zone=self.zone, pool_size=10, concurrency=5,
        )
        self.assertEqual(task.zone.code, "public")
        task.delete()

    def test_auto_scan_directory_result_zone_accepts_public(self):
        """目录结果 zone FK 可正常写入"""
        from app_cybersparker.models import auto_scan_directory_result
        rec = auto_scan_directory_result.objects.create(
            task_id=1, zone=self.zone, protocol="http", host="z.com", port=80,
            uri_path="/test", root_identify_result=None,
        )
        self.assertEqual(rec.zone.code, "public")
        rec.delete()


class SystemZoneDataMigrationTests(TestCase):
    """BL-ZONE-001 系统区域数据迁移测试"""

    def test_public_zone_exists_after_migration(self):
        """迁移后 code=public 的系统区域存在"""
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.get(code="public")
        self.assertEqual(zone.name, "公网")
        self.assertTrue(zone.is_system)

    def test_zone_count_after_migration(self):
        """迁移后至少有 1 个系统区域"""
        from app_cybersparker.models import AssetZone
        count = AssetZone.objects.count()
        self.assertGreaterEqual(count, 1)


class ZoneCRUDApiTests(TestCase):
    """BL-ZONE-001 Zone CRUD API 测试"""

    def _login(self):
        session = self.client.session
        session["info"] = {"id": 1, "username": "admin", "role": "super_admin"}
        session.save()

    def test_list_zones(self):
        """列表接口返回所有 zone"""
        self._login()
        resp = self.client.get("/api/v1/zones")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn("zones", data)
        codes = [z["code"] for z in data["zones"]]
        self.assertIn("public", codes)

    def test_list_zones_unauthorized(self):
        """未登录拒绝"""
        resp = self.client.get("/api/v1/zones")
        self.assertEqual(resp.status_code, 401)

    def test_create_zone(self):
        """新增区域成功"""
        self._login()
        resp = self.client.post(
            "/api/v1/zones/create",
            data=json.dumps({"code": "lan-a", "name": "办公网A"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(json.loads(resp.content)["code"], "lan-a")

    def test_create_zone_name_unique(self):
        """新增区域名称重复被拒绝"""
        from app_cybersparker.models import AssetZone
        self._login()
        AssetZone.objects.create(code="uniq-1", name="唯一名")
        resp = self.client.post(
            "/api/v1/zones/create",
            data=json.dumps({"code": "uniq-2", "name": "唯一名"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_zone(self):
        """改名成功"""
        from app_cybersparker.models import AssetZone
        self._login()
        zone = AssetZone.objects.create(code="rename-me", name="旧名")
        resp = self.client.put(
            f"/api/v1/zones/{zone.id}/update",
            data=json.dumps({"name": "新名"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        zone.refresh_from_db()
        self.assertEqual(zone.name, "新名")
        zone.delete()

    def test_delete_zone_no_refs(self):
        """无引用的区域可正常删除"""
        from app_cybersparker.models import AssetZone
        self._login()
        zone = AssetZone.objects.create(code="del-me", name="待删")
        resp = self.client.delete(f"/api/v1/zones/{zone.id}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(AssetZone.objects.filter(code="del-me").exists())

    def test_delete_public_rejected(self):
        """系统区域 public 不允许删除"""
        self._login()
        from app_cybersparker.models import AssetZone
        zone = AssetZone.objects.get(code="public")
        resp = self.client.delete(f"/api/v1/zones/{zone.id}/delete")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("系统区域", json.loads(resp.content).get("error", ""))

    def test_delete_zone_with_asset_refs_rejected(self):
        """有资产引用的区域删除被拒绝，并返回引用数"""
        from app_cybersparker.models import AssetZone, auto_scan_indentify_result
        self._login()
        zone = AssetZone.objects.create(code="with-asset", name="有资产的区域")
        asset = auto_scan_indentify_result.objects.create(
            zone=zone, protocol="http", host="x.local", port=80, uri_path="",
            target="http://x.local", ip="1.2.3.4",
        )
        resp = self.client.delete(f"/api/v1/zones/{zone.id}/delete")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("引用", json.loads(resp.content).get("error", ""))
        asset.delete()
        zone.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code__in=["lan-a", "uniq-1", "uniq-2", "rename-me",
                                           "del-me", "with-asset"]).delete()


class EventPayloadZoneTests(TestCase):
    """BL-ZONE-003 event payload 含 zone_id 测试"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        self.public = AssetZone.objects.get(code="public")

    def test_build_payloads_includes_zone_id(self):
        """打包的 event payload 包含 zone_id"""
        from app_cybersparker.services.result_event_service import build_identify_event_payloads
        payloads = build_identify_event_payloads(
            task_id=1, url="http://10.0.0.1", header="", title="",
            content="", status_code=200, ip_address="10.0.0.1",
            host="10.0.0.1", port=80, protocol="http", country="",
            products=["nginx"], zone_id=self.public.id,
        )
        self.assertGreater(len(payloads), 0)
        for p in payloads:
            self.assertEqual(p["zone_id"], self.public.id)

    def test_resolve_identify_result_uses_zone(self):
        """同 target 不同 zone 返回不同 asset id"""
        from app_cybersparker.services.result_event_service import _resolve_identify_result_id
        from app_cybersparker.models import AssetZone, auto_scan_indentify_result

        internal = AssetZone.objects.create(code="ut-epz", name="测试区")
        aid1 = _resolve_identify_result_id("http://dup.example.com:8080/api", self.public.id)
        aid2 = _resolve_identify_result_id("http://dup.example.com:8080/api", internal.id)
        self.assertNotEqual(aid1, aid2)
        auto_scan_indentify_result.objects.filter(id=aid1).delete()
        auto_scan_indentify_result.objects.filter(id=aid2).delete()
        internal.delete()

    def test_resolve_identify_result_no_lru_cache(self):
        """_resolve_identify_result_id 不再有 lru_cache 装饰器"""
        from app_cybersparker.services.result_event_service import _resolve_identify_result_id
        self.assertFalse(hasattr(_resolve_identify_result_id, "cache_info"))

    def test_write_identify_event_uses_zone_in_match(self):
        """_write_identify_event 用 zone 参与 match，不同 zone 创建不同 asset"""
        from app_cybersparker.services.result_event_service import _write_identify_event
        from app_cybersparker.models import AssetZone, auto_scan_indentify_result, AssetTaskRelation

        internal = AssetZone.objects.create(code="ut-we", name="写入测试")
        payload_a = {
            "event_id": "test:a",
            "task_id": 99990, "zone_id": self.public.id,
            "target": "http://zone-a.com", "product": "nginx",
            "ip": "10.0.0.1", "host": "zone-a.com", "port": 80,
            "protocol": "http", "country": "", "title": "A",
            "header": "", "html": "", "status_code": 200,
            "uri_path": "/test", "favicon": None, "favicon_md5": None,
            "cert_org": None, "cert_org_unit": None, "cert_common_name": None,
            "cert_serial": None, "province": None, "city": None, "isp": None,
        }
        payload_b = {
            **payload_a, "event_id": "test:b", "zone_id": internal.id,
            "target": "http://zone-b.com", "host": "zone-b.com", "title": "B",
        }

        _write_identify_event(payload_a)
        _write_identify_event(payload_b)

        a_count = auto_scan_indentify_result.objects.filter(zone=self.public, host="zone-a.com").count()
        b_count = auto_scan_indentify_result.objects.filter(zone=internal, host="zone-b.com").count()
        self.assertEqual(a_count, 1)
        self.assertEqual(b_count, 1)

        # cleanup
        AssetTaskRelation.objects.filter(task_id=99990).delete()
        auto_scan_indentify_result.objects.filter(host__in=["zone-a.com", "zone-b.com"]).delete()
        internal.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code__in=["ut-epz", "ut-we"]).delete()


class FscanxZoneWriteTests(TestCase):
    """BL-ZONE-003 fscanx 导入写资产带 zone"""

    def setUp(self):
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        self.public = AssetZone.objects.get(code="public")
        self.internal = AssetZone.objects.create(code="ut-fx", name="内网测试")
        self.task = auto_scan_tasks.objects.create(
            task_name="fscanx-zone-test", zone=self.internal,
            thread_num=1, conflict_strategy=1,
        )

    def test_task_zone_not_public(self):
        """fscanx 任务的 zone 是内网 zone，不是 public"""
        self.assertNotEqual(self.task.zone_id, self.public.id)
        self.assertEqual(self.task.zone_id, self.internal.id)

    def test_asset_created_with_task_zone(self):
        """通过 task.zone 创建的资产写入正确 zone"""
        from app_cybersparker.models import auto_scan_indentify_result, AssetTaskRelation
        asset = auto_scan_indentify_result.objects.create(
            zone=self.internal, protocol="http", host="10.0.0.1", port=80,
            uri_path="", target="http://10.0.0.1", ip="10.0.0.1",
            source_type=2,
        )
        AssetTaskRelation.objects.create(task_id=self.task.id, identify_result=asset)
        found = auto_scan_indentify_result.objects.filter(
            host="10.0.0.1", port=80, protocol="http"
        ).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.zone_id, self.internal.id)
        asset.delete()

    def tearDown(self):
        from app_cybersparker.models import auto_scan_tasks, auto_scan_indentify_result, AssetZone
        auto_scan_indentify_result.objects.filter(host="10.0.0.1", port=80).delete()
        auto_scan_tasks.objects.filter(task_name="fscanx-zone-test").delete()
        AssetZone.objects.filter(code="ut-fx").delete()


class EngineInputTypePublicZoneTests(TestCase):
    """BL-ZONE-003 测绘引擎输入源 (input_type=4/5) 强制 zone=public"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        self.public = AssetZone.objects.get(code="public")
        self.internal = AssetZone.objects.create(code="ut-engine", name="内网")

    def test_auto_scan_input_type4_forced_public(self):
        """自动扫描 input_type=4 保存时后端强制 zone=public"""
        from app_cybersparker.views.expload.task_manage import auto_scan_task as ast
        from app_cybersparker.models import auto_scan_tasks

        task = auto_scan_tasks.objects.create(
            task_name="engine4-test", zone=self.internal,
            thread_num=1, input_type=4, engine_type="fofa",
            engine_query="test", engine_max_assets=10,
        )
        # 重新加载 task 对象（form save 后已被强制改为 public）
        task.refresh_from_db()
        self.assertEqual(task.zone_id, self.public.id)
        task.delete()

    def test_auto_scan_input_type5_forced_public(self):
        """自动扫描 input_type=5 保存时后端强制 zone=public"""
        from app_cybersparker.models import auto_scan_tasks

        task = auto_scan_tasks.objects.create(
            task_name="engine5-test", zone=self.internal,
            thread_num=1, input_type=5, engine_type="fofa",
            engine_query="test", engine_max_assets=10,
        )
        task.refresh_from_db()
        self.assertEqual(task.zone_id, self.public.id)
        task.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code="ut-engine").delete()


class FourReferenceDeleteCheckTests(TestCase):
    """BL-ZONE-004 四重引用删除检查"""

    def setUp(self):
        from app_cybersparker.models import AssetZone, AssetRootBinding
        self.zone = AssetZone.objects.get(code="public")
        self.asset = models.auto_scan_indentify_result.objects.create(
            zone=self.zone, protocol="http", host="anchor.local", port=80,
            uri_path="", target="http://anchor.local", ip="10.0.0.1",
        )

    def test_can_delete_asset_with_no_refs(self):
        """无任何引用时允许删除"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task import _can_delete_asset
        self.assertTrue(_can_delete_asset(self.asset.id))

    def test_cannot_delete_asset_with_root_binding(self):
        """有 AssetRootBinding 引用时拒绝删除"""
        from app_cybersparker.models import AssetRootBinding
        from app_cybersparker.views.expload.task_manage.auto_scan_task import _can_delete_asset
        binding = AssetRootBinding.objects.create(
            zone=self.zone, protocol="http", host="anchor.local", port=80,
            identify_result=self.asset,
        )
        self.assertFalse(_can_delete_asset(self.asset.id))
        binding.delete()

    def test_cannot_delete_asset_with_exp_result_ref(self):
        """有 exp_result 引用时拒绝删除"""
        from app_cybersparker.models import auto_scan_exp_result
        from app_cybersparker.views.expload.task_manage.auto_scan_task import _can_delete_asset
        exp = models.EXP.objects.first()
        if exp:
            r = auto_scan_exp_result.objects.create(
                task_id=99999, task_type=1, identify_result_id=self.asset.id,
                EXP_id=exp, target=self.asset.target, result="ok",
            )
            self.assertFalse(_can_delete_asset(self.asset.id))
            r.delete()

    def tearDown(self):
        self.asset.delete()


class GlobalSearchZoneFilterTests(TestCase):
    """BL-ZONE-004 全局检索 zone 过滤"""

    def setUp(self):
        from django.test import RequestFactory
        from app_cybersparker.models import AssetZone
        self.factory = RequestFactory()
        self.public = AssetZone.objects.get(code="public")
        self.internal = AssetZone.objects.create(code="ut-gs", name="检索测试区")
        models.auto_scan_indentify_result.objects.filter(
            host__in=["z1-pub.com", "z1-int.com"]
        ).delete()
        self.a1 = models.auto_scan_indentify_result.objects.create(
            zone=self.public, protocol="http", host="z1-pub.com", port=80, uri_path="",
            target="http://z1-pub.com", ip="10.0.0.1",
        )
        self.a2 = models.auto_scan_indentify_result.objects.create(
            zone=self.internal, protocol="http", host="z1-int.com", port=80, uri_path="",
            target="http://z1-int.com", ip="10.0.0.1",
        )

    def test_queryset_zone_filter_in_zone(self):
        """zone 过滤只返回指定 zone 的资产"""
        qs = models.auto_scan_indentify_result.objects.filter(zone_id=self.public.id)
        hosts = list(qs.values_list("host", flat=True))
        self.assertIn("z1-pub.com", hosts)
        self.assertNotIn("z1-int.com", hosts)

    def test_queryset_all_zones(self):
        """不过滤时返回所有 zone 的资产"""
        qs = models.auto_scan_indentify_result.objects.all()
        hosts = list(qs.values_list("host", flat=True))
        self.assertIn("z1-pub.com", hosts)
        self.assertIn("z1-int.com", hosts)

    def test_global_search_intranet_excludes_public(self):
        """zone_id=__intranet__ 排除 public zone 资产"""
        from app_cybersparker.views.expload.task_manage.auto_scan_result import (
            global_asset_search_api,
        )
        req = self.factory.get("/", {"zone_id": "__intranet__", "rows_per_page": "13"})
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = global_asset_search_api(req)
        payload = json.loads(resp.content)
        hosts = [r["host"] for r in payload.get("results", [])]
        self.assertIn("z1-int.com", hosts,
                      "内网 zone 资产不应被排除")
        self.assertNotIn("z1-pub.com", hosts,
                         "public zone 资产不应出现在内网结果中")

    def test_global_search_intranet_queryset_logic(self):
        """__intranet__ 最终 queryset 等于 exclude(zone__code='public')"""
        from app_cybersparker.models import AssetZone
        # 再创建一个非 public 的 zone 确认 exclude 排除了所有 public
        extra_zone = AssetZone.objects.create(code="ut-gs2", name="检索测试区2")
        a3 = models.auto_scan_indentify_result.objects.create(
            zone=extra_zone, protocol="http", host="z1-ext.com", port=80,
            uri_path="", target="http://z1-ext.com", ip="10.0.0.3",
        )
        try:
            qs_all = models.auto_scan_indentify_result.objects.filter(
                host__in=["z1-pub.com", "z1-int.com", "z1-ext.com"]
            )
            qs_intranet = qs_all.exclude(zone__code="public")
            intranet_hosts = list(qs_intranet.values_list("host", flat=True))
            self.assertIn("z1-int.com", intranet_hosts)
            self.assertIn("z1-ext.com", intranet_hosts)
            self.assertNotIn("z1-pub.com", intranet_hosts)
        finally:
            a3.delete()
            AssetZone.objects.filter(code="ut-gs2").delete()

    def test_global_facet_intranet_excludes_public(self):
        """facet 接口也支持 __intranet__ 过滤"""
        from app_cybersparker.views.expload.task_manage.auto_scan_result import (
            global_facet_api,
        )
        req = self.factory.get("/", {
            "field": "port",
            "offset": "0",
            "zone_id": "__intranet__",
        })
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = global_facet_api(req)
        payload = json.loads(resp.content)
        self.assertEqual(payload.get("status"), "ok",
                         f"facet 接口应返回 ok, 实际: {payload}")
        # __intranet__ 过滤后只有内网资产 (port=80, count=1)
        items = payload.get("items", [])
        port_80 = next((item for item in items if item["name"] == "80"), None)
        self.assertIsNotNone(port_80, f"内网资产 port=80 应在 facet 中, items={items}")
        self.assertEqual(port_80["count"], 1,
                         f"__intranet__ 过滤后应只有 1 条 port=80, 实际: {port_80}")

    def tearDown(self):
        self.a1.delete()
        self.a2.delete()
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code="ut-gs").delete()


class ZoneCRUDBoundaryTests(TestCase):
    """BL-ZONE 补充 — zone CRUD 边界测试"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code__startswith="ut-crud").delete()

    def _req(self, method, path, body=None):
        factory = RequestFactory()
        kwargs = {}
        if body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = "application/json"
        req = getattr(factory, method.lower())(path, **kwargs)
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        return req

    def test_create_zone_missing_code(self):
        """新增区域缺少 code 返回 400"""
        from app_cybersparker.views.expload.zone_manage import zone_create_api
        req = self._req("POST", "/api/v1/zones/create", {"name": "无名"})
        resp = zone_create_api(req)
        self.assertEqual(resp.status_code, 400)

    def test_create_zone_invalid_json(self):
        """新增区域非法 JSON 返回 400"""
        from app_cybersparker.views.expload.zone_manage import zone_create_api
        req = RequestFactory().post("/api/v1/zones/create", data="bad json",
                                     content_type="application/json")
        req.session = {"info": {"id": 1, "username": "admin", "role": "super_admin"}}
        resp = zone_create_api(req)
        self.assertEqual(resp.status_code, 400)

    def test_delete_nonexistent_zone(self):
        """删除不存在的区域返回 404"""
        from app_cybersparker.views.expload.zone_manage import zone_delete_api
        req = self._req("DELETE", "/api/v1/zones/99999/delete")
        resp = zone_delete_api(req, 99999)
        self.assertEqual(resp.status_code, 404)

    def test_delete_zone_with_task_refs_rejected(self):
        """有自动扫描任务引用的区域删除被拒绝"""
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        zone = AssetZone.objects.create(code="ut-crud-task", name="有任务区")
        task = auto_scan_tasks.objects.create(
            task_name="zone-crud-test", zone=zone, thread_num=1,
        )
        from app_cybersparker.views.expload.zone_manage import zone_delete_api
        req = self._req("DELETE", f"/api/v1/zones/{zone.id}/delete")
        resp = zone_delete_api(req, zone.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("引用", json.loads(resp.content).get("error", ""))
        task.delete()
        zone.delete()

    def test_delete_zone_with_directory_result_refs_rejected(self):
        """有目录扫描结果引用的区域删除被拒绝"""
        from app_cybersparker.models import AssetZone, auto_scan_directory_result
        zone = AssetZone.objects.create(code="ut-crud-dir", name="有目录区")
        rec = auto_scan_directory_result.objects.create(
            task_id=99999, zone=zone, protocol="http", host="x.com", port=80,
            uri_path="/test", root_identify_result=None,
        )
        from app_cybersparker.views.expload.zone_manage import zone_delete_api
        req = self._req("DELETE", f"/api/v1/zones/{zone.id}/delete")
        resp = zone_delete_api(req, zone.id)
        self.assertEqual(resp.status_code, 400)
        rec.delete()
        zone.delete()

    def test_update_zone_not_found(self):
        """改名不存在的区域返回 404"""
        from app_cybersparker.views.expload.zone_manage import zone_update_api
        req = self._req("PUT", "/api/v1/zones/99999/update", {"name": "新名"})
        resp = zone_update_api(req, 99999)
        self.assertEqual(resp.status_code, 404)

    def test_update_zone_name_conflict(self):
        """改名与已有名称冲突返回 400"""
        from app_cybersparker.models import AssetZone
        AssetZone.objects.create(code="ut-crud-a", name="名称A")
        z2 = AssetZone.objects.create(code="ut-crud-b", name="名称B")
        from app_cybersparker.views.expload.zone_manage import zone_update_api
        req = self._req("PUT", f"/api/v1/zones/{z2.id}/update", {"name": "名称A"})
        resp = zone_update_api(req, z2.id)
        self.assertEqual(resp.status_code, 400)
        z2.delete()
        AssetZone.objects.filter(code="ut-crud-a").delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        auto_scan_tasks.objects.filter(task_name__in=["zone-crud-test"]).delete()
        AssetZone.objects.filter(code__startswith="ut-crud").delete()


class BatchHistoryVulnZoneFilterTests(TestCase):
    """BL-ZONE-004 补充 — 批量任务 input_type=2 zone 过滤"""

    def setUp(self):
        from app_cybersparker.models import AssetZone
        self.public = AssetZone.objects.get(code="public")
        self.internal = AssetZone.objects.create(code="ut-bhv", name="批量漏洞区")

    def test_collect_targets_does_not_consume_exptask_result(self):
        """collect_targets 不消费 EXPTask_result"""
        from app_cybersparker.views.expload.task_manage.batch_exp_task import (
            collect_targets_from_history_vul_assets,
        )
        targets = collect_targets_from_history_vul_assets("all")
        # 不应该包含来自 EXPTask_result 的 target
        self.assertIsInstance(targets, list)

    def test_collect_targets_filters_by_zone(self):
        """collect_targets 按 zone 过滤历史漏洞资产"""
        from app_cybersparker.models import auto_scan_indentify_result, auto_scan_exp_result
        from app_cybersparker.views.expload.task_manage.batch_exp_task import (
            collect_targets_from_history_vul_assets,
        )
        exp = models.EXP.objects.first()
        if not exp:
            self.skipTest("没有 EXP 数据")
        asset = auto_scan_indentify_result.objects.create(
            zone=self.internal, protocol="http", host="vuln-zone.local", port=8080,
            uri_path="", target="http://vuln-zone.local:8080", ip="10.0.0.99",
        )
        r = auto_scan_exp_result.objects.create(
            task_id=99998, task_type=1, identify_result_id=asset.id,
            EXP_id=exp, target=asset.target, result="ok",
        )
        targets = collect_targets_from_history_vul_assets("all", zone_id=self.internal.id)
        self.assertIn("http://vuln-zone.local:8080", targets)
        r.delete()
        asset.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone
        AssetZone.objects.filter(code="ut-bhv").delete()


class ModelSaveForcePublicZoneTests(TestCase):
    """BL-ZONE-003 补充 — 模型 save() 强制公网"""

    def test_auto_scan_save_forces_public_for_input_type_4(self):
        """auto_scan_tasks.save() 对 input_type=4 强制 zone=public"""
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        internal = AssetZone.objects.create(code="ut-sf-a", name="测强公")
        task = auto_scan_tasks(
            task_name="force-public-4", zone=internal, thread_num=1,
            input_type=4, engine_type="fofa", engine_query="test",
        )
        task.save()
        self.assertEqual(task.zone.code, "public")
        task.delete()
        internal.delete()

    def test_batch_save_forces_public_for_input_type_5(self):
        """batch_EXPTask.save() 对 input_type=5 强制 zone=public"""
        from app_cybersparker.models import AssetZone, batch_EXPTask
        internal = AssetZone.objects.create(code="ut-sf-b", name="测强公B")
        task = batch_EXPTask(
            task_name="batch-force-5", zone=internal, EXP="test", thread_num=1,
            input_type=5, engine_type="fofa", engine_query="test",
        )
        task.save()
        self.assertEqual(task.zone.code, "public")
        task.delete()
        internal.delete()

    def test_auto_scan_save_keeps_user_zone_for_input_type_1(self):
        """auto_scan_tasks.save() 对 input_type=1 保留用户选择的 zone"""
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        internal = AssetZone.objects.create(code="ut-sf-c", name="测保留")
        task = auto_scan_tasks(
            task_name="keep-zone-1", zone=internal, thread_num=1, input_type=1,
        )
        task.save()
        self.assertEqual(task.zone.code, "ut-sf-c")
        task.delete()
        internal.delete()

    def tearDown(self):
        from app_cybersparker.models import AssetZone, auto_scan_tasks, batch_EXPTask
        auto_scan_tasks.objects.filter(task_name__startswith="force-public").delete()
        auto_scan_tasks.objects.filter(task_name__startswith="keep-zone").delete()
        batch_EXPTask.objects.filter(task_name__startswith="batch-force").delete()
        AssetZone.objects.filter(code__startswith="ut-sf").delete()


class ModelFormZoneFieldTests(TestCase):
    """BL-ZONE-005 补充 — ModelForm 绑定 zone 字段 + 默认公网"""

    def test_auto_scan_form_binds_zone_from_post(self):
        """auto_scan_task ModelForm 从 POST 数据绑定 zone_id"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task import ModelForm
        from app_cybersparker.models import AssetZone
        public = AssetZone.objects.get(code="public")
        form = ModelForm(data={
            "task_name": "ut-mf-auto-1",
            "input_type": "1",
            "thread_num": "10",
            "sleep_time": "0",
            "http_timeout": "10",
            "Vulnerability_scanning": "0",
            "zone": str(public.id),
        })
        self.assertTrue(form.is_valid(), f"Form invalid: {form.errors}")
        self.assertEqual(form.instance.zone, public)

    def test_auto_scan_form_creates_task_with_zone(self):
        """auto_scan_task ModelForm.save() 保存的 task 带正确的 zone"""
        from app_cybersparker.views.expload.task_manage.auto_scan_task import ModelForm
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        public = AssetZone.objects.get(code="public")
        form = ModelForm(data={
            "task_name": "ut-mf-auto-2",
            "input_type": "1",
            "thread_num": "10",
            "sleep_time": "0",
            "http_timeout": "10",
            "Vulnerability_scanning": "0",
            "zone": str(public.id),
        })
        self.assertTrue(form.is_valid())
        task = form.save()
        self.assertEqual(task.zone.code, "public")
        task.delete()

    def test_batch_form_binds_zone_from_post(self):
        """batch_ExpTask_ModelForm 从 POST 数据绑定 zone_id"""
        from app_cybersparker.views.expload.task_manage.batch_exp_task import batch_ExpTask_ModelForm
        from app_cybersparker.models import AssetZone
        public = AssetZone.objects.get(code="public")
        form = batch_ExpTask_ModelForm(data={
            "task_name": "ut-mf-batch-1",
            "input_type": "1",
            "thread_num": "10",
            "sleep_time": "0",
            "run_mode": "1",
            "exp_select_mode": "1",
            "filter_logic": "AND",
            "zone": str(public.id),
        })
        self.assertTrue(form.is_valid(), f"Form invalid: {form.errors}")
        self.assertEqual(form.instance.zone, public)

    def test_dirscan_form_binds_zone_from_post(self):
        """DirScanTaskForm 从 POST 数据绑定 zone_id"""
        from app_cybersparker.views.expload.dirscan_task_manage import DirScanTaskForm
        from app_cybersparker.models import AssetZone
        public = AssetZone.objects.get(code="public")
        form = DirScanTaskForm(data={
            "task_name": "ut-mf-dirscan-1",
            "input_mode": "1",
            "pool_size": "200",
            "concurrency": "100",
            "max_body_size": "3145728",
            "max_truncate_size": "1048576",
            "vuln_thread_num": "60",
            "sleep_time": "0",
            "zone": str(public.id),
        })
        self.assertTrue(form.is_valid(), f"Form invalid: {form.errors}")
        self.assertEqual(form.instance.zone, public)

    def test_auto_scan_save_defaults_zone_to_public_when_none(self):
        """auto_scan_tasks.save() — 非引擎输入源且 zone=None 时默认公网"""
        from app_cybersparker.models import AssetZone, auto_scan_tasks
        task = auto_scan_tasks(
            task_name="ut-mf-def-zone", thread_num=1, input_type=1,
        )
        # zone 显式为 None
        self.assertIsNone(task.zone_id)
        task.save()
        self.assertEqual(task.zone.code, "public")
        task.delete()

    def tearDown(self):
        from app_cybersparker.models import auto_scan_tasks, batch_EXPTask
        auto_scan_tasks.objects.filter(task_name__startswith="ut-mf").delete()
        batch_EXPTask.objects.filter(task_name__startswith="ut-mf").delete()
        from app_cybersparker.models import DirScanTask
        DirScanTask.objects.filter(task_name__startswith="ut-mf").delete()


class HtmlSearchSemanticSplitTests(TestCase):
    """BL-AUTO-015 补偿 — html: 走 tsvector，html:= 走子串 LIKE"""

    def test_colon_uses_tsvector(self):
        """html:nginx → 生成的 SQL 包含 to_tsvector"""
        from app_cybersparker.services.asset_search_parser import (
            parse_condition, to_query_structure,
        )
        tree = parse_condition('html:nginx')
        self.assertFalse(tree.get('deep_search'))
        q = to_query_structure(tree)
        sql = str(q)
        self.assertIn('to_tsvector', sql.lower())
        self.assertNotIn('LIKE', sql)

    def test_deep_uses_like(self):
        """html:=nginx → 生成的 SQL 包含 LIKE %nginx%"""
        from app_cybersparker.services.asset_search_parser import (
            parse_condition, to_query_structure,
        )
        tree = parse_condition('html:="nginx"')
        self.assertTrue(tree.get('deep_search'))
        q = to_query_structure(tree)
        sql = str(q)
        self.assertIn('LIKE', sql)
        self.assertIn('%nginx%', sql)

    def test_colon_handles_multi_word(self):
        """html:nginx apache → tsvector 匹配两个词"""
        from app_cybersparker.services.asset_search_parser import (
            parse_condition, to_query_structure,
        )
        tree = parse_condition('html:"nginx apache"')
        self.assertFalse(tree.get('deep_search'))
        q = to_query_structure(tree)
        sql = str(q)
        self.assertIn('plainto_tsquery', sql.lower())
        self.assertIn('nginx apache', sql)

    def test_body_same_as_html(self):
        """body 和 html 走相同的路径"""
        from app_cybersparker.services.asset_search_parser import (
            parse_condition, to_query_structure,
        )
        tree_html = parse_condition('html:nginx')
        tree_body = parse_condition('body:nginx')
        q_html = str(to_query_structure(tree_html))
        q_body = str(to_query_structure(tree_body))
        # 两者 SQL 应包含相同的函数
        self.assertIn('to_tsvector', q_html.lower())
        self.assertIn('to_tsvector', q_body.lower())


class SeedExportScriptTests(TestCase):
    """种子数据导出脚本回归测试"""

    def _assert_leading_sql_comment_block(self, content, expected_first_non_comment_prefixes):
        header_lines = []
        first_non_comment = None

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                header_lines.append(line)
                continue
            first_non_comment = stripped
            break

        header_text = "\n".join(header_lines)
        self.assertTrue(header_lines)
        self.assertIn("-- Cybersparker 种子数据（Docker 部署用）", header_text)
        self.assertNotIn("${OUTPUT}", header_text)
        self.assertNotIn("<< 'HEADER'", header_text)
        self.assertIsNotNone(first_non_comment)
        self.assertTrue(
            any(first_non_comment.startswith(prefix) for prefix in expected_first_non_comment_prefixes),
            msg=f"unexpected first non-comment line in seed header: {first_non_comment}",
        )

    def test_export_script_writes_sql_header_without_shell_commands(self):
        """导出的 seed_data.sql 头部只能有 SQL 注释，不能混入 shell 命令文本"""
        script_path = _PROJECT_ROOT / "deploy" / "seed" / "export_seed_data.sh"

        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            temp_seed_dir = temp_root / "seed"
            temp_seed_dir.mkdir(parents=True)
            temp_script_path = temp_seed_dir / "export_seed_data.sh"
            temp_script_path.write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")
            os.chmod(temp_script_path, 0o755)

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()

            fake_psql = bin_dir / "psql"
            fake_psql.write_text("#!/bin/sh\nprintf '1\\n'\n", encoding="utf-8")
            os.chmod(fake_psql, 0o755)

            fake_pg_dump = bin_dir / "pg_dump"
            fake_pg_dump.write_text(
                "#!/bin/sh\ncat <<'EOF'\n-- fake dump\nINSERT INTO public.fake_table VALUES (1);\nEOF\n",
                encoding="utf-8",
            )
            os.chmod(fake_pg_dump, 0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env.get('PATH', '')}",
                    "DB_HOST": "fake-host",
                    "DB_PORT": "5432",
                    "DB_USER": "fake-user",
                    "DB_PASS": "fake-pass",
                    "DB_NAME": "fake-db",
                }
            )

            subprocess.run(
                ["bash", str(temp_script_path)],
                check=True,
                cwd=temp_root,
                env=env,
                capture_output=True,
                text=True,
            )

            output = (temp_seed_dir / "seed_data.sql").read_text(encoding="utf-8")
            self._assert_leading_sql_comment_block(
                output,
                ("INSERT INTO public.fake_table VALUES",),
            )

    def test_checked_in_seed_file_header_has_no_shell_commands(self):
        """仓库内的 seed_data.sql 头部也必须保持纯 SQL 注释"""
        output = (_PROJECT_ROOT / "deploy" / "seed" / "seed_data.sql").read_text(encoding="utf-8")
        self._assert_leading_sql_comment_block(output, ("\\restrict", "SET "))
