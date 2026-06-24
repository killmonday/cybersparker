"""
Monkey-patch: 让所有 HTTP 库的 SSL context 以最大兼容模式运行。

Web 探测场景不需要 TLS 安全性——拿到页面内容最重要。
此 patch 在 context 创建时统一：
  - 追加 OP_LEGACY_SERVER_CONNECT (0x4)：允许连接不支持 secure renegotiation 的服务器
  - 追加 OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION (0x40000)：允许旧式重新协商
  - set_ciphers('DEFAULT:@SECLEVEL=0')：关闭 DH/RSA/CA 等密钥强度检查

覆盖 ssl.create_default_context、ssl._create_default_https_context、
urllib3.util.ssl_.create_urllib3_context。
"""

import ssl

_LEGACY_FLAGS = 0x4 | 0x40000


def _apply_max_compat(ctx):
    ctx.options |= _LEGACY_FLAGS
    # SECLEVEL=0: 关闭所有密钥强度检查（DH_KEY_TOO_SMALL 等）
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
    except Exception:
        pass
    return ctx


def patch():
    # 1. Python 标准库
    _orig_create_default_context = ssl.create_default_context
    _orig_create_default_https = ssl._create_default_https_context

    def _wrap_default_context(*args, **kwargs):
        return _apply_max_compat(_orig_create_default_context(*args, **kwargs))

    def _wrap_default_https(*args, **kwargs):
        return _apply_max_compat(_orig_create_default_https(*args, **kwargs))

    ssl.create_default_context = _wrap_default_context
    ssl._create_default_https_context = _wrap_default_https

    # 2. urllib3 — connection.py 有 local import，需要同时 patch 两个模块
    try:
        import urllib3.util.ssl_
        _orig_urllib3 = urllib3.util.ssl_.create_urllib3_context

        def _wrap_urllib3(*args, **kwargs):
            return _apply_max_compat(_orig_urllib3(*args, **kwargs))

        urllib3.util.ssl_.create_urllib3_context = _wrap_urllib3

        import urllib3.connection
        urllib3.connection.create_urllib3_context = _wrap_urllib3  # type: ignore[attr-defined]
    except ImportError:
        pass
