import requests
import urllib3
from requests.exceptions import InvalidURL
from urllib.parse import quote

UNRESERVED_SET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" + "0123456789-._~"
)


def unquote_unreserved(uri):
    parts = uri.split("%")
    for i in range(1, len(parts)):
        h = parts[i][0:2]
        if len(h) == 2 and h.isalnum():
            try:
                c = chr(int(h, 16))
            except ValueError:
                raise InvalidURL("Invalid percent-escape sequence: '%s'" % h)

            if c in UNRESERVED_SET:
                parts[i] = c + parts[i][2:]
            else:
                parts[i] = "%" + parts[i]
        else:
            parts[i] = "%" + parts[i]
    return "".join(parts)


def patched_requote_uri(uri):
    safe_with_percent = "!\"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~"
    safe_without_percent = "!\"#$&\'()*+,-./:;<=>?@[\\]^_`{|}~"
    try:
        return quote(unquote_unreserved(uri), safe=safe_with_percent)
    except InvalidURL:
        return quote(uri, safe=safe_without_percent)


def patched_encode_target(target):
    return target


def unquote_request_uri():
    try:
        requests.utils.requote_uri.__code__ = patched_requote_uri.__code__
    except Exception:
        pass

    try:
        urllib3.util.url._encode_target.__code__ = patched_encode_target.__code__
    except Exception:
        pass
