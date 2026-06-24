"""纯真 IP 数据库 (qqwry.dat) 高性能解析器。

参考 Go 实现，支持 IPv4 二分查找、重定向模式、GBK 解码。
"""

import struct
from pathlib import Path
from typing import Optional, Tuple


_QQWRY_INSTANCE: Optional["QQwry"] = None

REDIRECT_MODE_1 = 0x01
REDIRECT_MODE_2 = 0x02

# ISP 关键词
_ISP_KEYWORDS = [
    "电信", "联通", "移动", "铁通", "教育网", "鹏博士", "科技网",
    "长城宽带", "歌华有线", "方正宽带", "宽带通", "天威视讯",
    "有线通", "华数", "广电", "电信通", "光环新网",
    "世纪互联", "互联港湾", "中电华通", "中联通",
    "中信网络", "CNISP", "中国电信", "中国联通", "中国移动",
]


def _bytes3_to_uint32(data: bytes) -> int:
    return data[0] | (data[1] << 8) | (data[2] << 16)


def _ip_to_uint32(ip: str) -> int:
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"invalid IPv4: {ip}")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def _uint32_to_ip(n: int) -> str:
    return f"{(n >> 24) & 0xff}.{(n >> 16) & 0xff}.{(n >> 8) & 0xff}.{n & 0xff}"


class _Reader:
    """内部读取器，跟踪索引位置。"""

    __slots__ = ("_data", "_i", "_last")

    def __init__(self, data: bytes):
        self._data = data
        self._i = 0
        self._last = 0

    def seek_abs(self, offset: int) -> None:
        self._last = self._i
        self._i = offset

    def seek_back(self) -> None:
        self._i = self._last

    def _read_byte(self) -> int:
        b = self._data[self._i]
        self._last = self._i
        self._i += 1
        return b

    def read_mode(self) -> int:
        return self._read_byte()

    def read_offset(self, follow: bool = True) -> int:
        buf = self._data[self._i : self._i + 3]
        self._last = self._i
        self._i += 3
        offset = _bytes3_to_uint32(buf)
        if follow:
            self._last = self._i
            self._i = offset
        return offset

    def read_string(self, seek: bool = True) -> str:
        end = self._data.index(0, self._i)
        raw = self._data[self._i : end]
        if seek:
            self._last = self._i
            self._i = end + 1
        try:
            return raw.decode("gbk")
        except (UnicodeDecodeError, LookupError):
            return raw.decode("gbk", errors="replace")

    def parse(self, offset: int) -> Tuple[str, str]:
        """解析指定偏移量的记录，返回 (country_raw, area_raw)。"""
        if offset != 0:
            self.seek_abs(offset)

        mode = self.read_mode()
        if mode == REDIRECT_MODE_1:
            self.read_offset(True)
            return self.parse(0)
        elif mode == REDIRECT_MODE_2:
            country = self._parse_red_mode2()
            area = self._read_area()
            return country, area
        else:
            self.seek_back()
            country = self.read_string(True)
            area = self._read_area()
            return country, area

    def _parse_red_mode2(self) -> str:
        self.read_offset(True)
        s = self.read_string(False)
        self.seek_back()
        return s

    def _read_area(self) -> str:
        mode = self.read_mode()
        if mode in (REDIRECT_MODE_1, REDIRECT_MODE_2):
            offset = self.read_offset(True)
            if offset == 0:
                return ""
        else:
            self.seek_back()
        return self.read_string(False)


class QQwry:
    """纯真 IP 数据库。"""

    __slots__ = ("_data", "_start", "_end", "_entry_len")

    def __init__(self, filepath: str):
        data = Path(filepath).read_bytes()
        if len(data) < 8:
            raise ValueError("qqwry.dat 文件不完整（小于 8 字节）")

        header = data[:8]
        start = struct.unpack("<I", header[:4])[0]
        end = struct.unpack("<I", header[4:])[0]

        if start >= end or len(data) < end + 7:
            raise ValueError("qqwry.dat 索引区损坏")

        self._data = data
        self._start = start
        self._end = end
        self._entry_len = 7  # 4 bytes IP + 3 bytes offset

    @property
    def record_count(self) -> int:
        return (self._end - self._start) // self._entry_len + 1

    def search_index(self, ip_uint32: int) -> int:
        """二分查找 IP，返回记录数据区的偏移量。"""
        entry_len = self._entry_len
        l, r = self._start, self._end
        data = self._data

        while True:
            mid = ((r - l) // entry_len // 2) * entry_len + l
            buf = data[mid : mid + entry_len]
            ipc = struct.unpack("<I", buf[:4])[0]

            if r - l == entry_len:
                buf_r = data[r : r + entry_len]
                ip_r = struct.unpack("<I", buf_r[:4])[0]
                if ip_uint32 >= ip_r:
                    buf = buf_r
                return _bytes3_to_uint32(buf[4:7])

            if ipc > ip_uint32:
                r = mid
            elif ipc < ip_uint32:
                l = mid
            else:
                return _bytes3_to_uint32(buf[4:7])

    def lookup(self, ip: str) -> Tuple[str, str]:
        """返回 (country_raw, area_raw) 均已做 GBK 解码和 CZ88.NET 清理。"""
        ip_uint32 = _ip_to_uint32(ip)
        offset = self.search_index(ip_uint32)
        if offset == 0:
            return ("", "")
        reader = _Reader(self._data)
        country, area = reader.parse(offset + 4)
        country = _clean(country)
        area = _clean(area)
        return country, area


def _clean(s: str) -> str:
    return s.replace("CZ88.NET", "").strip().replace("\x00", "")


def _parse_geo(country_raw: str, area_raw: str) -> dict:
    """从纯真 country/area 字段解析出国、省/直辖市、市、运营商。"""
    country = ""
    province = ""
    city = ""
    isp = ""

    parts = [p.strip() for p in country_raw.replace("—", "–").split("–") if p.strip()]

    if parts:
        country = parts[0]
        if len(parts) >= 2:
            province = parts[1]
        if len(parts) >= 3:
            city = parts[2]
        if len(parts) >= 4:
            city = "–".join(parts[2:])

    # 从 area_raw 和未匹配到的 country parts 中提取 ISP
    candidates = [area_raw]
    if not province and len(parts) > 1:
        candidates.append(country_raw)
    for keyword in _ISP_KEYWORDS:
        for candidate in candidates:
            if keyword in candidate:
                if not isp or len(keyword) > len(isp):
                    isp = keyword
    if not isp:
        # 如果 area 是单短词且像运营商就用它
        short_area = area_raw.strip()
        if len(short_area) <= 8 and short_area:
            isp = short_area

    return {
        "country": country or "",
        "province": province or "",
        "city": city or "",
        "isp": isp or "",
    }


def get_qqwry(filepath: str = None) -> Optional[QQwry]:
    """获取全局单例 QQwry。"""
    global _QQWRY_INSTANCE
    if _QQWRY_INSTANCE is None:
        import cybersparker.settings as sett

        path = filepath or (sett.THIS_DIR + "/../db/qqwry.dat")
        try:
            _QQWRY_INSTANCE = QQwry(path)
        except (FileNotFoundError, ValueError) as e:
            import logging

            logging.getLogger(__name__).warning("qqwry.dat 加载失败: %s", e)
            return None
    return _QQWRY_INSTANCE


def query_ip_geo(ip: str) -> dict:
    """查询单个 IP 的地理位置。返回 dict with country, province, city, isp。"""
    db = get_qqwry()
    if db is None:
        return {"country": "", "province": "", "city": "", "isp": ""}
    try:
        country, area = db.lookup(ip)
    except (ValueError, struct.error, IndexError):
        return {"country": "", "province": "", "city": "", "isp": ""}
    if not country and not area:
        return {"country": "", "province": "", "city": "", "isp": ""}
    return _parse_geo(country, area)
