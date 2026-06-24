import requests
from requests.sessions import Session
import json
from requests.structures import CaseInsensitiveDict
# requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'DEFAULT@SECLEVEL=1'


def extract_dict(text, sep, sep2="="):
    return CaseInsensitiveDict([l.split(sep2, 1) for l in text.split(sep)])


def httpraw(raw: str, ssl: bool = False, **kwargs):
    raw = raw.strip()
    raws = list(map(lambda x: x.strip(), raw.splitlines()))
    try:
        method, path, protocol = raws[0].split(" ")
    except Exception:
        raise Exception("Protocol format error")

    post = None
    _json = None
    if method.upper() == "POST":
        index = 0
        for i in raws:
            index += 1
            if i.strip() == "":
                break
        if len(raws) == index:
            raise Exception
        tmp_headers = raws[1:index - 1]
        tmp_headers = extract_dict("\n".join(tmp_headers), "\n", ": ")
        post_data = "\n".join(raws[index:])
        try:
            json.loads(post_data)
            _json = post_data
        except ValueError:
            post = post_data
    else:
        tmp_headers = extract_dict("\n".join(raws[1:]), "\n", ": ")

    netloc = "http" if not ssl else "https"
    host = tmp_headers.get("Host", None)
    if host is None:
        raise Exception("Host is None")
    del tmp_headers["Host"]
    url = "{0}://{1}".format(netloc, host + path)

    kwargs.setdefault("allow_redirects", True)
    kwargs.setdefault("data", post)
    kwargs.setdefault("headers", tmp_headers)
    kwargs.setdefault("json", _json)

    with Session() as session:
        return session.request(method=method, url=url, **kwargs)


def patch_addraw():
    requests.httpraw = httpraw
