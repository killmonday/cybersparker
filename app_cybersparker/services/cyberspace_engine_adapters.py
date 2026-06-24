import base64
import requests


ENGINE_PAGE_SIZE = 500


class BaseEngineAdapter:
    # 常见的服务名 → 协议名映射（大部分服务名直接就是协议名）
    _KNOWN_SERVICES = {
        "ssh", "ftp", "telnet", "smtp", "dns", "rdp", "smb",
        "mysql", "mssql", "redis", "mongodb", "postgresql", "postgres",
        "oracle", "ldap", "ntp", "snmp", "pop3", "imap", "sip",
        "vnc", "rsync", "nfs", "elasticsearch", "couchdb", "memcached",
        "cassandra", "http", "https",
    }

    @classmethod
    def _resolve_protocol(cls, service_name, ssl_flag=None):
        """将引擎返回的 service 名转为协议名。未知服务回退 http/https。"""
        svc = str(service_name or "").strip().lower()
        if svc in cls._KNOWN_SERVICES:
            return svc
        if svc.startswith("https") or svc == "ssl/http":
            return "https"
        if svc in ("http-proxy", "www", "http-alt"):
            return "http"
        if ssl_flag:
            return "https"
        return "http"

    @classmethod
    def _protocol_from_port(cls, port_int, ssl_flag=None):
        """根据端口号反查协议名。用于 Shodan 等不返回服务名的引擎。"""
        from app_cybersparker.views.expload.task_manage.auto_exp_task import _NON_HTTP_DEFAULT_PORTS
        for proto, default_port in _NON_HTTP_DEFAULT_PORTS.items():
            if port_int == default_port:
                return proto
        return "https" if ssl_flag else "http"

    def build_proxies(self, proxy_url):
        if not proxy_url:
            return {}
        return {"http": proxy_url, "https": proxy_url}

    def request(self, method, url, headers=None, params=None, data=None, json_data=None, proxies=None, timeout=120):
        response = requests.request(
            method=method,
            url=url,
            headers=headers or {},
            params=params,
            data=data,
            json=json_data,
            proxies=proxies or {},
            timeout=timeout,
            verify=False,
        )
        return response

    def _iter_values(self, *values):
        for value in values:
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    text = str(item or "").strip()
                    if text:
                        yield text
            else:
                text = str(value or "").strip()
                if text:
                    yield text

    def _add_port(self, host, port):
        host_text = str(host or "").strip()
        port_text = str(port or "").strip()
        if not host_text or not port_text:
            return host_text
        if "://" in host_text:
            scheme, rest = host_text.split("://", 1)
            if rest.startswith("["):
                return host_text if "]:" in rest else f"{scheme}://{rest}:{port_text}"
            return host_text if ":" in rest else f"{scheme}://{rest}:{port_text}"
        if host_text.startswith("["):
            return host_text if "]:" in host_text else f"{host_text}:{port_text}"
        return host_text if ":" in host_text else f"{host_text}:{port_text}"

    def _ensure_scheme(self, target, protocol):
        text = str(target or "").strip()
        if not text:
            return ""
        if text.startswith("http://") or text.startswith("https://"):
            return text
        if "://" in text:
            return text
        return f"{protocol}://{text}"

    def _build_preferred_target(self, protocol="http", port="", urls=None, hosts=None, ips=None):
        protocol_text = str(protocol or "http").strip() or "http"
        port_text = str(port or "").strip()
        for url in self._iter_values(*(urls or [])):
            url_with_port = self._add_port(url, port_text)
            return self._ensure_scheme(url_with_port, protocol_text)
        for host in self._iter_values(*(hosts or [])):
            host_with_port = self._add_port(host, port_text)
            return self._ensure_scheme(host_with_port, protocol_text)
        for ip in self._iter_values(*(ips or [])):
            ip_with_port = self._add_port(ip, port_text)
            return self._ensure_scheme(ip_with_port, protocol_text)
        return ""

    def search(self, query, page, page_size, config, proxies):
        raise NotImplementedError

    def extract_targets(self, resp):
        raise NotImplementedError


class FofaAdapter(BaseEngineAdapter):
    def search(self, query, page, page_size, config, proxies):
        base = str(config.api_base_url or "").rstrip("/")
        query_b64 = base64.b64encode(query.encode("utf-8")).decode("utf-8")
        params = {
            "email": str(config.account_email or ""),
            "key": str(config.api_key or ""),
            "qbase64": query_b64,
            "page": page,
            "size": page_size,
            "fields": "host,ip,port,protocol",
        }
        return self.request("GET", f"{base}/api/v1/search/all", params=params, proxies=proxies)

    def extract_targets(self, resp):
        data = resp.json() if resp.content else {}
        if not data.get("error") and isinstance(data.get("results"), list):
            targets = []
            for row in data.get("results", []):
                if not isinstance(row, list):
                    continue
                host = str(row[0] or "").strip() if len(row) > 0 else ""
                ip = str(row[1] or "").strip() if len(row) > 1 else ""
                port = str(row[2] or "").strip() if len(row) > 2 else ""
                protocol = str(row[3] or "http").strip() if len(row) > 3 else "http"
                target = self._build_preferred_target(protocol=protocol, port=port, hosts=[host], ips=[ip])
                if target:
                    targets.append(target)
            return targets
        return []


class ZoomEyeAdapter(BaseEngineAdapter):
    def search(self, query, page, page_size, config, proxies):
        base = str(config.api_base_url or "").rstrip("/")
        headers = {"API-KEY": str(config.api_key or "")}
        params = {"query": query, "page": page, "page_size": page_size}
        return self.request("GET", f"{base}/host/search", headers=headers, params=params, proxies=proxies)

    def extract_targets(self, resp):
        data = resp.json() if resp.content else {}
        matches = data.get("matches", []) if isinstance(data, dict) else []
        targets = []
        for item in matches:
            if not isinstance(item, dict):
                continue
            portinfo = item.get("portinfo") if isinstance(item.get("portinfo"), dict) else {}
            ip = str(item.get("ip") or "").strip()
            port = portinfo.get("port")
            service = portinfo.get("service") or ""
            protocol = self._resolve_protocol(service)
            target = self._build_preferred_target(
                protocol=protocol,
                port=port,
                urls=[item.get("site")],
                hosts=[item.get("domain"), item.get("hostname"), portinfo.get("host"), item.get("hostnames"), item.get("domains")],
                ips=[ip],
            )
            if target:
                targets.append(target)
        return targets


class QuakeAdapter(BaseEngineAdapter):
    def search(self, query, page, page_size, config, proxies):
        base = str(config.api_base_url or "").rstrip("/")
        headers = {"X-QuakeToken": str(config.api_key or ""), "Content-Type": "application/json"}
        payload = {"query": query, "start": (page - 1) * page_size, "size": page_size}
        print(f"[quake-adapter] request payload={{'query': {query!r}, 'start': {(page - 1) * page_size}, 'size': {page_size}}}")
        return self.request("POST", f"{base}/api/v3/search/quake_service", headers=headers, json_data=payload, proxies=proxies)

    def extract_targets(self, resp):
        data = resp.json() if resp.content else {}
        rows = data.get("data", []) if isinstance(data, dict) else []
        print(f"[quake-adapter] response rows={len(rows)} keys={sorted(data.keys()) if isinstance(data, dict) else []}")
        targets = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            service_dict = item.get("service") if isinstance(item.get("service"), dict) else {}
            http_dict = service_dict.get("http") if isinstance(service_dict.get("http"), dict) else {}
            ip = str(item.get("ip") or "").strip()
            port = str(item.get("port") or "").strip()
            service = str(service_dict.get("name") or "").lower()
            protocol = self._resolve_protocol(service)
            target = self._build_preferred_target(
                protocol=protocol,
                port=port,
                urls=[item.get("url"), http_dict.get("url")],
                hosts=[item.get("domain"), item.get("hostname"), item.get("host"), http_dict.get("host"), http_dict.get("hosts")],
                ips=[ip],
            )
            if target:
                targets.append(target)
        return targets


class HunterAdapter(BaseEngineAdapter):
    def search(self, query, page, page_size, config, proxies):
        base = str(config.api_base_url or "").rstrip("/")
        query_b64 = base64.urlsafe_b64encode(query.encode("utf-8")).decode("utf-8")
        params = {
            "api-key": str(config.api_key or ""),
            "search": query_b64,
            "page": page,
            "page_size": page_size,
        }
        return self.request("GET", f"{base}/openApi/search", params=params, proxies=proxies)

    def extract_targets(self, resp):
        data = resp.json() if resp.content else {}
        arr = []
        if isinstance(data, dict):
            arr = data.get("data", {}).get("arr", []) if isinstance(data.get("data"), dict) else []
        targets = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            protocol = self._resolve_protocol(item.get("protocol") or "http")
            target = self._build_preferred_target(
                protocol=protocol,
                port=item.get("port"),
                urls=[item.get("url")],
                hosts=[item.get("domain"), item.get("host"), item.get("hostname")],
                ips=[item.get("ip")],
            )
            if target:
                targets.append(target)
        return targets


class ShodanAdapter(BaseEngineAdapter):
    def search(self, query, page, page_size, config, proxies):
        base = str(config.api_base_url or "").rstrip("/")
        params = {
            "key": str(config.api_key or ""),
            "query": query,
            "page": page,
            "minify": "true",
        }
        return self.request("GET", f"{base}/shodan/host/search", params=params, proxies=proxies)

    def extract_targets(self, resp):
        data = resp.json() if resp.content else {}
        matches = data.get("matches", []) if isinstance(data, dict) else []
        targets = []
        for item in matches:
            if not isinstance(item, dict):
                continue
            ip = str(item.get("ip_str") or "").strip()
            port = str(item.get("port") or "").strip()
            transport = str(item.get("transport") or "tcp").lower()
            ssl_flag = bool(str(item.get("ssl") or ""))
            protocol = self._protocol_from_port(int(port) if port else 0, ssl_flag=ssl_flag)
            if transport == "udp":
                target = self._build_preferred_target(protocol=protocol, port=port, hosts=[item.get("hostnames"), item.get("domains")], ips=[ip])
                if target:
                    targets.append(target.replace(f"{protocol}://", "") + "/udp")
                continue
            target = self._build_preferred_target(
                protocol=protocol,
                port=port,
                urls=[item.get("http", {}).get("location") if isinstance(item.get("http"), dict) else None],
                hosts=[item.get("hostnames"), item.get("domains")],
                ips=[ip],
            )
            if target:
                targets.append(target)
        return targets


ADAPTER_MAP = {
    "fofa": FofaAdapter,
    "zoomeye": ZoomEyeAdapter,
    "quake": QuakeAdapter,
    "hunter": HunterAdapter,
    "shodan": ShodanAdapter,
}


def get_adapter(engine_type):
    engine = str(engine_type or "").strip().lower()
    adapter_cls = ADAPTER_MAP.get(engine)
    if not adapter_cls:
        raise ValueError("unsupported engine type")
    return adapter_cls()
