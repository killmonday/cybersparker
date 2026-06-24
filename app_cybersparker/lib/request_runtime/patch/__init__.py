import urllib3

from app_cybersparker.lib.request_runtime.exceptions import RequestRuntimeIncompleteRead
from app_cybersparker.lib.request_runtime.patch.remove_ssl_verify import remove_ssl_verify
from app_cybersparker.lib.request_runtime.patch.remove_warnings import disable_requests_warnings
from app_cybersparker.lib.request_runtime.patch.hook_request import patch_session
from app_cybersparker.lib.request_runtime.patch.add_httpraw import patch_addraw
from app_cybersparker.lib.request_runtime.patch.hook_request_redirect import patch_redirect
from app_cybersparker.lib.request_runtime.patch.hook_urllib3_parse_url import patch_urllib3_parse_url
from app_cybersparker.lib.request_runtime.patch.unquote_request_uri import unquote_request_uri
from app_cybersparker.lib.request_runtime.patch.add_ssl_legacy_renegotiation import patch as patch_ssl_legacy


_PATCHED = False


def _update_chunk_length(self):
    if self.chunk_left is not None:
        return
    line = self._fp.fp.readline()
    line = line.split(b";", 1)[0]
    if not line:
        self.chunk_left = 0
        return
    try:
        self.chunk_left = int(line, 16)
    except ValueError:
        self.close()
        raise RequestRuntimeIncompleteRead(line)


def patch_all_once():
    global _PATCHED
    if _PATCHED:
        return

    patch_urllib3_parse_url()
    unquote_request_uri()
    urllib3.response.HTTPResponse._update_chunk_length = _update_chunk_length
    disable_requests_warnings()
    remove_ssl_verify()
    patch_ssl_legacy()
    patch_session()
    patch_addraw()
    patch_redirect()

    _PATCHED = True
