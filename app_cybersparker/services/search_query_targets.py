"""Keyset 分页遍历 — 从检索语句匹配的资产中逐批产 URL。

仅用于 auto_scan_tasks 和 batch_EXPTask（DirScanTask 走 shuffle_file）。
"""
from django.db import close_old_connections, connection

from app_cybersparker import models
from app_cybersparker.services.asset_search_parser import to_query_structure


def iter_search_query_targets(parsed_query, frozen_max_id, last_id=0, batch_size=1000, zone_id=None):
    """Keyset 分页遍历匹配资产的 target URL。每次 yield (row_id, target)。

    防御：frozen_max_id <= 0 或无 parsed_query 时直接返回空。
    每批后 close_old_connections + connection.close()。
    """
    if not parsed_query or not frozen_max_id or frozen_max_id <= 0:
        return

    from django.db.models import Q
    q = to_query_structure(parsed_query)
    # 限定 zone，防止执行阶段跨区域串数据
    if zone_id:
        q = Q(zone_id=zone_id) & q
    current_last_id = last_id or 0

    while True:
        close_old_connections()
        try:
            rows = models.auto_scan_indentify_result.objects \
                .filter(q, id__lte=frozen_max_id, id__gt=current_last_id) \
                .order_by('id') \
                .values_list('id', 'target')[:batch_size]
            rows = list(rows)
        finally:
            connection.close()

        if not rows:
            break

        for row_id, target in rows:
            yield row_id, target
            current_last_id = row_id
