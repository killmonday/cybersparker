import requests

def _verify(target):
    url = target["target"]
    url = f"{url}/appGet.cgi?hook=get_cfg_clientlist()"
    headers = {
        "User-Agent": "asusrouter--",
        "Referer": f"{url}/"
    }
    cookies = {
        "asus_token": "\x00Invalid",
        "clickedItem_tab": "0"
    }
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=10, verify=False)
        if resp.status_code == 200 and "get_cfg_clientlist" in resp.text:
            return {"target": url, "result": f"管理界面未授权访问：{resp.text[:300]}"}
    except Exception:
        pass
    return None