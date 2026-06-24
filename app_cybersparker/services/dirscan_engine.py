import json
import random

import xxhash

from app_cybersparker import models


_redis_client = None


def _redis():
    import redis
    from django.conf import settings

    global _redis_client
    if _redis_client is not None:
        return _redis_client
    broker_url = getattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    _redis_client = redis.Redis.from_url(broker_url)
    return _redis_client


def _progress_key(task_id, protocol, host, port):
    return f"dirscan:{task_id}:{protocol}:{host}:{port}:progress"


def _hash_key(task_id, protocol, host, port):
    return f"dirscan:{task_id}:{protocol}:{host}:{port}:hash"


def _file_pos_key(task_id):
    return f"dirscan:{task_id}:file_pos"


def load_paths(task_id):
    """加载任务所选字典的去重合并路径列表（内存 ~1MB）。"""
    task = models.DirScanTask.objects.get(id=task_id)
    all_paths = set()
    for d in task.dicts.all():
        for p in (d.paths or []):
            all_paths.add(p)
    return list(all_paths)


def read_shuffle_file_line(filepath, file_pos):
    """从 shuffle 文件指定行读一行，返回 (protocol, host, port) 或 None。"""
    try:
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i == file_pos:
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        return tuple(parts[:3])
                    return None
        return None
    except FileNotFoundError:
        return None


def compute_ttl(num_assets, num_paths, avg_request_sec=0.1):
    """动态计算 Redis key TTL（秒）。

    TTL = max(预估总耗时 × 3, 7200)
    """
    est_seconds = num_assets * num_paths * avg_request_sec
    return max(int(est_seconds * 3), 7200)


def save_progress(task_id, protocol, host, port, offset, counter, ttl):
    """将单个 host 的扫描进度写入 Redis。"""
    r = _redis()
    key = _progress_key(task_id, protocol, host, port)
    r.set(key, json.dumps({"offset": offset, "counter": counter}), ex=ttl)


def load_progress(task_id, protocol, host, port):
    """从 Redis 读取单个 host 的扫描进度。"""
    r = _redis()
    key = _progress_key(task_id, protocol, host, port)
    data = r.get(key)
    if data:
        return json.loads(data)
    return None


def delete_progress(task_id, protocol, host, port):
    """删除单个 host 的进度和哈希集合。"""
    r = _redis()
    r.delete(_progress_key(task_id, protocol, host, port))
    r.delete(_hash_key(task_id, protocol, host, port))


def body_hash_exists(task_id, protocol, host, port, h):
    """检查同 (host, port) 下是否已存在相同哈希。"""
    r = _redis()
    return r.sismember(_hash_key(task_id, protocol, host, port), h)


def body_hash_add(task_id, protocol, host, port, h, ttl):
    """将 body 哈希添加到 Redis Set 去重集合。"""
    r = _redis()
    key = _hash_key(task_id, protocol, host, port)
    r.sadd(key, h)
    r.expire(key, ttl)


def save_file_pos(task_id, pos, ttl):
    """保存文件读取位置到 Redis（热缓存）。"""
    r = _redis()
    r.set(_file_pos_key(task_id), pos, ex=ttl)
    models.DirScanTask.objects.filter(id=task_id).update(file_pos=pos)


def compute_body_hash(body_bytes):
    """对 body 前 4096 字节做 xxh3_128 哈希，返回 hex 字符串。"""
    return xxhash.xxh3_128(body_bytes[:4096]).hexdigest()


def cleanup_task_redis(task_id):
    """清理指定任务的所有 Redis key（独立函数，无 pool 依赖）。

    用于 worker 不在运行时的清理场景：暂停→停止、重跑、僵尸回收。
    幂等：key 不存在时 DELETE 是 no-op。
    """
    r = _redis()
    pattern = f"dirscan:{task_id}:*"
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=pattern, count=100)
        if keys:
            r.delete(*keys)
        if cursor == 0:
            break
    r.delete(_file_pos_key(task_id))


class DirScanPool:
    """活跃池：最多 POOL_SIZE 个 host，随机调度扫描。"""

    def __init__(self, task_id, pool_size, paths, ttl):
        self.task_id = task_id
        self.pool_size = pool_size
        self.paths = paths
        self.path_count = len(paths)
        self.ttl = ttl
        self.pool = []  # list of {"protocol":, "host":, "port":, "offset":, "counter":}
        self.file_done = False

    def fill(self, filepath, file_pos):
        """从文件补充池中空缺的 host。返回更新后的 file_pos。"""
        pos = file_pos
        while len(self.pool) < self.pool_size and not self.file_done:
            row = read_shuffle_file_line(filepath, pos)
            if row is None:
                self.file_done = True
                break
            protocol, host, port = row
            port = int(port)
            # 检查资产是否仍存在
            exists = models.auto_scan_indentify_result.objects.filter(
                protocol=protocol, host=host, port=port
            ).exists()
            if not exists:
                pos += 1
                continue
            offset = random.randint(0, self.path_count - 1)
            self.pool.append({
                "protocol": protocol,
                "host": host,
                "port": port,
                "offset": offset,
                "counter": 0,
            })
            pos += 1
        return pos

    def has_work(self):
        return len(self.pool) > 0

    def take_one(self):
        """随机取一个 host，返回 (host_info, path)。池空时返回 (None, None)。"""
        if not self.pool:
            return None, None
        idx = random.randint(0, len(self.pool) - 1)
        host = self.pool.pop(idx)
        path_idx = (host["offset"] + host["counter"]) % self.path_count
        path = self.paths[path_idx]
        return host, path

    def return_one(self, host):
        """host 未扫完，放回池中。"""
        if host["counter"] < self.path_count:
            self.pool.append(host)
            return True
        return False

    def cleanup_host(self, host):
        """host 扫完，清理 Redis 进度和哈希集合。"""
        delete_progress(
            self.task_id, host["protocol"], host["host"], host["port"]
        )

    def cleanup_all(self):
        """扫描完成，清理所有 Redis key。"""
        cleanup_task_redis(self.task_id)

    def recover(self):
        """恢复：从 Redis 加载未完成 host 的进度到池中。"""
        r = _redis()
        pattern = f"dirscan:{self.task_id}:*:progress"
        recovered = set()
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=pattern, count=100)
            for key in keys:
                # key format: dirscan:{task_id}:{protocol}:{host}:{port}:progress
                parts = key.split(b":")
                if len(parts) >= 5:
                    protocol = parts[2].decode()
                    host = parts[3].decode()
                    port = int(parts[4].decode())
                    ident = (protocol, host, port)
                    if ident in recovered:
                        continue
                    recovered.add(ident)
                    prog = load_progress(self.task_id, protocol, host, port)
                    if prog:
                        self.pool.append({
                            "protocol": protocol,
                            "host": host,
                            "port": port,
                            "offset": prog["offset"],
                            "counter": prog["counter"],
                        })
            if cursor == 0:
                break
        # 池已满则提前停止恢复
        while len(self.pool) > self.pool_size:
            self.pool.pop()
        return len(self.pool)
