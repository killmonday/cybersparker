from __future__ import absolute_import
from collections import namedtuple
import urllib3
import urllib3.util


class HTTPError(Exception):
    pass


class LocationValueError(ValueError, HTTPError):
    pass


class LocationParseError(LocationValueError):
    def __init__(self, location):
        message = "Failed to parse: %s" % location
        HTTPError.__init__(self, message)
        self.location = location


url_attrs = ["scheme", "auth", "host", "port", "path", "query", "fragment"]
NORMALIZABLE_SCHEMES = ("http", "https", None)


class Url(namedtuple("Url", url_attrs)):
    __slots__ = ()

    def __new__(
        cls,
        scheme=None,
        auth=None,
        host=None,
        port=None,
        path=None,
        query=None,
        fragment=None,
    ):
        if path and not path.startswith("/"):
            path = "/" + path
        if scheme:
            scheme = scheme.lower()
        if host and scheme in NORMALIZABLE_SCHEMES:
            host = host.lower()
        return super(Url, cls).__new__(cls, scheme, auth, host, port, path, query, fragment)

    @property
    def hostname(self):
        return self.host

    @property
    def request_uri(self):
        uri = self.path or "/"
        if self.query is not None:
            uri += "?" + self.query
        return uri

    @property
    def netloc(self):
        if self.port:
            return "%s:%d" % (self.host, self.port)
        return self.host

    @property
    def url(self):
        scheme, auth, host, port, path, query, fragment = self
        url = ""
        if scheme is not None:
            url += scheme + "://"
        if auth is not None:
            url += auth + "@"
        if host is not None:
            url += host
        if port is not None:
            url += ":" + str(port)
        if path is not None:
            url += path
        if query is not None:
            url += "?" + query
        if fragment is not None:
            url += "#" + fragment
        return url

    def __str__(self):
        return self.url


def patched_parse_url(url):
    def split_first(s, delims):
        min_idx = None
        min_delim = None
        for d in delims:
            idx = s.find(d)
            if idx < 0:
                continue
            if min_idx is None or idx < min_idx:
                min_idx = idx
                min_delim = d
        if min_idx is None or min_idx < 0:
            return s, "", None
        return s[:min_idx], s[min_idx + 1 :], min_delim

    if not url:
        return Url()

    scheme = None
    auth = None
    host = None
    port = None
    path = None
    fragment = None
    query = None

    if "://" in url:
        scheme, url = url.split("://", 1)

    url, path_, delim = split_first(url, ["/", "?", "#"])
    if delim:
        path = delim + path_

    if "@" in url:
        auth, url = url.rsplit("@", 1)

    if url and url[0] == "[":
        host, url = url.split("]", 1)
        host += "]"

    if ":" in url:
        _host, port = url.split(":", 1)
        if not host:
            host = _host
        if port:
            if not port.isdigit():
                raise LocationParseError(url)
            try:
                port = int(port)
            except ValueError:
                raise LocationParseError(url)
        else:
            port = None
    elif not host and url:
        host = url

    if not path:
        return Url(scheme, auth, host, port, path, query, fragment)

    if "#" in path:
        path, fragment = path.split("#", 1)
    if "?" in path:
        path, query = path.split("?", 1)

    return Url(scheme, auth, host, port, path, query, fragment)


def patch_urllib3_parse_url():
    try:
        urllib3.util.parse_url.__code__ = patched_parse_url.__code__
    except Exception:
        pass
