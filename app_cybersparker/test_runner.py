"""
安全 test runner：在测试期间临时切回 Django 原生 PostgreSQL 后端，
避免 dj_db_conn_pool 连接池不跟随 test DB 切换导致主库被清空。

对 manage.py test 完全透明，不需要额外参数或环境变量。
"""

import logging

from django.conf import settings
from django.db import connections
from django.test.runner import DiscoverRunner

logger = logging.getLogger(__name__)

SAFE_TEST_ENGINE = "django.db.backends.postgresql"
ORIGINAL_ENGINE_KEY = "_original_engine"


class SafeTestRunner(DiscoverRunner):
    """DiscoverRunner 子类：测试生命周期内强制使用原生 PG 后端。"""

    def setup_databases(self, **kwargs):
        _swap_to_safe_engine()
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        try:
            return super().teardown_databases(old_config, **kwargs)
        finally:
            _restore_engine()


def _swap_to_safe_engine():
    """测试前：把 ENGINE 临时换成安全后端，并丢弃旧连接 wrapper。"""
    for alias in list(settings.DATABASES.keys()):
        db_settings = settings.DATABASES[alias]
        current_engine = db_settings.get("ENGINE", "")
        if current_engine != SAFE_TEST_ENGINE:
            db_settings[ORIGINAL_ENGINE_KEY] = current_engine
            db_settings["ENGINE"] = SAFE_TEST_ENGINE

        _close_and_drop_connection(alias)

        if current_engine != SAFE_TEST_ENGINE:
            logger.debug(
                "SafeTestRunner: %r 后端由 %s 临时切换为 %s",
                alias, current_engine, SAFE_TEST_ENGINE,
            )


def _close_and_drop_connection(alias):
    """关闭并删除 Django 已缓存的连接 wrapper。"""
    if alias in connections:
        conn = connections[alias]
        try:
            conn.close()
        except Exception:
            pass
        try:
            del connections[alias]
        except Exception:
            pass
    _dispose_pool_if_exists(alias)


def _dispose_pool_if_exists(alias):
    """销毁 dj_db_conn_pool 为 alias 创建的 SQLAlchemy 连接池。"""
    try:
        from dj_db_conn_pool.core import pool_container
        if pool_container.has(alias):
            pool_container.get(alias).dispose()
            pool_container.pop(alias, None)
    except Exception:
        pass


def _restore_engine():
    """测试后：恢复原始 ENGINE 并清理后端连接。"""
    for alias, db_settings in settings.DATABASES.items():
        original = db_settings.pop(ORIGINAL_ENGINE_KEY, None)
        if original is None:
            continue
        db_settings["ENGINE"] = original
        _close_and_drop_connection(alias)
        logger.debug("SafeTestRunner: %r 已恢复原始后端 %s", alias, original)
