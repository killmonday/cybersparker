import codecs
import csv
from datetime import datetime
import io
import json
import logging
import time
import traceback
from django.shortcuts import render
from django.urls import reverse
from app_cybersparker import models
from django.db import connection
from django.db.models import F, Q
from django.db.models.expressions import RawSQL

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import HttpResponse, JsonResponse
import cybersparker.settings as sett
from django.utils.safestring import mark_safe


logger = logging.getLogger(__name__)

pwd = sett.THIS_DIR
FACET_PAGE_SIZE = 40
FAVICON_PAGE_SIZE = 20
from app_cybersparker.permissions import deny_user
from app_cybersparker.services.asset_search_parser import (
    parse_condition,
    to_query_structure,
    _has_deep_search,
    CERT_SEARCH_FIELDS,
)

# 中文国名 → ISO 2-letter code（用于国旗 CSS sprite）
_COUNTRY_CODE_MAP = {
    '中国': 'cn',
}
def _country_code(country):
    if not country:
        return ''
    c = country.strip()
    if c in _COUNTRY_CODE_MAP:
        return _COUNTRY_CODE_MAP[c]
    return c.lower()

def error_log(e_info,tips,time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open (error_log_path,"a+") as f:
            f.write(f"[expload {tips}] {time} : " +  e_info + "\n")
            f.close()
    except:
        pass

RESULT_JSON_CONTRACT_VERSION = 'result-search-v1'
RESULT_SEARCH_PARAM = 'search_data'
RESULT_PAGINATION_PARAMS = ['cursor', 'dir', 'jump', 'rows_per_page']
RESULT_FACET_PARAMS = ['field', 'search_data', 'offset']
RESULT_JSON_ITEM_FIELDS = [
    'id',
    'ip',
    'host',
    'protocol',
    'port',
    'title',
    'status_code',
    'country',
    'country_code',
    'target',
    'product',
    'creatime',
    'header',
    'favicon_md5',
    'favicon',
    'cert_org',
    'cert_org_unit',
    'cert_common_name',
    'cert_serial',
    'province',
    'city',
    'isp',
    'uri_path',
    'related_vulns',
]


def _serialize_identify_result_item(item, related_vulns):
    return {
        'id': item.id,
        'ip': item.ip,
        'host': item.host or '',
        'protocol': item.protocol,
        'port': item.port,
        'title': item.title or '',
        'status_code': item.status_code,
        'country': item.country,
        'country_code': _country_code(item.country or ''),
        'target': item.target,
        'product': item.products or [],
        'creatime': item.creatime.strftime('%Y-%m-%d %H:%M:%S') if item.creatime else '',
        'header': item.header or '',
        'favicon_md5': item.favicon_md5 or '',
        'favicon': item.favicon or '',
        'cert_org': item.cert_org or '',
        'cert_org_unit': item.cert_org_unit or '',
        'cert_common_name': item.cert_common_name or '',
        'cert_serial': item.cert_serial or '',
        'province': item.province or '',
        'city': item.city or '',
        'isp': item.isp or '',
        'uri_path': item.uri_path or '',
        'related_vulns': related_vulns,
    }


def _build_identify_results_contract(scope, facet_endpoint):
    vuln_result_path = reverse('api_identify_result_vuln', kwargs={'result_id': 0}).replace('/0/', '/{result_id}/')
    html_source_path = reverse('api_identify_result_html', kwargs={'result_id': 0}).replace('/0/', '/{result_id}/')
    port_overview_more_path = reverse('api_port_overview')
    return {
        'scope': scope,
        'search_param': RESULT_SEARCH_PARAM,
        'pagination_params': RESULT_PAGINATION_PARAMS,
        'facet_params': RESULT_FACET_PARAMS,
        'result_fields': RESULT_JSON_ITEM_FIELDS,
        'facet_endpoint': facet_endpoint,
        'detail_endpoints': {
            'vuln_result': vuln_result_path,
            'html_source': html_source_path,
            'port_overview_more': f'{port_overview_more_path}?ip={{ip}}&target={{target}}',
        },
    }


def _build_identify_results_payload(*, items, related_vulns_map, page_object, favicon_facet, deep_search_mode, scope, facet_endpoint, search_string, task_id=None, task_name=''):
    exact_total = getattr(page_object, 'exact_total', None)
    estimated_total = page_object.estimated_total if page_object.estimated_total > 0 else (exact_total or 0)
    results = [
        _serialize_identify_result_item(item, related_vulns_map.get(item.id, []))
        for item in items
    ]
    pagination = {
        'has_next': page_object.has_next,
        'has_prev': page_object.has_prev,
        'next_cursor': getattr(page_object, 'next_cursor', ''),
        'prev_cursor': getattr(page_object, 'prev_cursor', ''),
        'page_size': page_object.page_size,
        'estimated_total': estimated_total,
        'exact_total': exact_total,
    }
    query = {
        'scope': scope,
        'search_param': RESULT_SEARCH_PARAM,
        'search_data': search_string,
    }
    if task_id is not None:
        query['task_id'] = task_id
    favicon_payload = {
        'items': favicon_facet['items'],
        'has_more': favicon_facet['has_more'],
        'next_offset': favicon_facet['next_offset'],
        'count_label': favicon_facet['count_label'],
        'page_size': FAVICON_PAGE_SIZE,
        'deferred': deep_search_mode,
    }
    return {
        'status': 'ok',
        'results': results,
        **pagination,
        'favicon_items': favicon_payload['items'],
        'favicon_has_more': favicon_payload['has_more'],
        'favicon_next_offset': favicon_payload['next_offset'],
        'favicon_total': favicon_payload['count_label'],
        'favicon_deferred': favicon_payload['deferred'],
        'contract_version': RESULT_JSON_CONTRACT_VERSION,
        'contract': _build_identify_results_contract(scope, facet_endpoint),
        'query': query,
        'pagination': pagination,
        'favicon_facet': favicon_payload,
        'task_name': task_name,
    }


class ExploadModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['poc']
    class Meta:
        model = models.auto_scan_indentify_result
        exclude = ["creat_time","update_time"]

class Pagination(object):
    """Cursor-based pagination — no COUNT query, uses id as cursor.

    Cursor 格式：{id} 或 {id},{total}。翻页时 total 随 cursor 传递，避免重算 COUNT。
    """

    def __init__(self, request, queryset, page_size=13, page_param="cursor",
                 rows_per_page_options=[13, 5, 10, 15, 20, 50, 100, 200, 500, 1000, 5000], jump_pages=10):
        import copy
        query_dict = copy.deepcopy(request.GET)
        query_dict._mutable = True
        self.query_dict = query_dict

        requested_page_size = int(request.GET.get("rows_per_page", page_size))
        if requested_page_size in rows_per_page_options:
            self.page_size = requested_page_size
        else:
            self.page_size = page_size

        cursor_raw = request.GET.get(page_param, "")
        direction = request.GET.get("dir", "next")
        jump = int(request.GET.get("jump", "0") or 0)
        if jump > jump_pages:
            jump = jump_pages
        elif jump < -jump_pages:
            jump = -jump_pages

        # 解析 cursor：支持 "id,total" 格式
        carried_total = 0
        if cursor_raw and ',' in cursor_raw:
            parts = cursor_raw.split(',', 1)
            cursor = parts[0]
            try:
                carried_total = int(parts[1])
            except (ValueError, IndexError):
                carried_total = 0
        else:
            cursor = cursor_raw

        base_qs = queryset.order_by('-id')
        if cursor and cursor.isdecimal():
            if direction == "prev" or jump < 0:
                abs_jump = abs(jump) if jump < 0 else 0
                skip = self.page_size * abs_jump
                page_qs = base_qs.filter(id__gt=int(cursor)).order_by('id')[skip:skip + self.page_size + 1]
                rows = list(page_qs)
                if not rows and abs_jump > 0:
                    # 跳页越过第一条 → 回退到首页
                    page_qs = base_qs.annotate(
                        exact_total=RawSQL("COUNT(*) OVER()", [])
                    ).order_by('-id')[:self.page_size + 1]
                    rows = list(page_qs)
                    self.exact_total = rows[0].exact_total if rows else 0
                    self.estimated_total = self.exact_total
                    carried_total = 0
                    self.has_prev = False
                    self.has_next = len(rows) > self.page_size
                    if self.has_next:
                        rows = rows[:self.page_size]
                    self.page_queryset = rows
                else:
                    if not rows:
                        # prev 方向无结果（已到第一页），回退到首页
                        page_qs = base_qs.annotate(
                            exact_total=RawSQL("COUNT(*) OVER()", [])
                        ).order_by('-id')[:self.page_size + 1]
                        rows = list(page_qs)
                        self.exact_total = rows[0].exact_total if rows else 0
                        self.estimated_total = self.exact_total
                        carried_total = 0
                        self.has_prev = False
                        self.has_next = len(rows) > self.page_size
                        if self.has_next:
                            rows = rows[:self.page_size]
                        self.page_queryset = rows
                    else:
                        self.has_prev = len(rows) > self.page_size
                        if self.has_prev:
                            rows = rows[:self.page_size]
                        rows.reverse()
                        self.page_queryset = rows
                        self.has_next = True
            else:
                skip = self.page_size * max(jump, 0)
                page_qs = base_qs.filter(id__lt=int(cursor))[skip:skip + self.page_size + 1]
                rows = list(page_qs)
                if not rows and jump > 0:
                    # 跳页越过最后一条 → 回退到尾页
                    page_qs = base_qs.annotate(
                        exact_total=RawSQL("COUNT(*) OVER()", [])
                    ).order_by('id')[:self.page_size + 1]
                    rows = list(page_qs)
                    self.exact_total = rows[0].exact_total if rows else 0
                    self.estimated_total = self.exact_total
                    carried_total = 0
                    self.has_next = False
                    self.has_prev = len(rows) > self.page_size
                    if self.has_prev:
                        rows = rows[:self.page_size]
                    rows.reverse()
                    self.page_queryset = rows
                else:
                    self.has_next = len(rows) > self.page_size
                    if self.has_next:
                        rows = rows[:self.page_size]
                    self.page_queryset = rows
                    self.has_prev = True
            # 总数优先用 cursor 携带的值，没有则算一次
            if carried_total > 0:
                self.exact_total = carried_total
                self.estimated_total = carried_total
            elif self.page_queryset:
                exact_qs = queryset.annotate(
                    exact_total=RawSQL("COUNT(*) OVER()", [])
                ).values("exact_total")[:1]
                self.exact_total = exact_qs[0]["exact_total"] if exact_qs else 0
                self.estimated_total = self.exact_total
        else:
            # First page (no cursor): fetch newest rows with exact total
            page_qs = base_qs.annotate(
                exact_total=RawSQL("COUNT(*) OVER()", [])
            )[:self.page_size + 1]
            rows = list(page_qs)
            self.exact_total = rows[0].exact_total if rows else 0
            self.has_next = len(rows) > self.page_size
            if self.has_next:
                rows = rows[:self.page_size]
            self.page_queryset = rows
            self.has_prev = False
            self.estimated_total = self.exact_total

        # 生成翻页 cursor 时附带总数
        self._total_suffix = f",{self.exact_total}" if getattr(self, 'exact_total', None) else ""
        if self.page_queryset:
            self.next_cursor = str(self.page_queryset[-1].id) + self._total_suffix
            self.prev_cursor = str(self.page_queryset[0].id) + self._total_suffix
        else:
            self.next_cursor = ""
            self.prev_cursor = ""

        self.rows_per_page_options = rows_per_page_options
        self.page_param = page_param
        self.jump_pages = jump_pages

    def html(self):
        page_str_list = []

        button_style = """position: relative;
                        display: inline-block;
                        padding: 0;
                        text-decoration: none;
                        border-radius:19px;
                        color:#4778c7;
                        height:40px;
                        border: 1px solid #4778c7;
                        width:auto;
                        padding: 0 12px;
                        line-height: 40px;
                        vertical-align: middle;
                        text-align: center;
                        background-color: #040c1f;
                        """

        # Prev button
        if self.has_prev:
            self.query_dict.setlist(self.page_param, [self.prev_cursor])
            self.query_dict.setlist('dir', ['prev'])
            prev_html = '<li><a href="?{}" style="{}">< 上一页</a></li>'.format(self.query_dict.urlencode(), button_style)
        else:
            prev_html = '<li><span style="{};opacity:0.4;cursor:default;">< 上一页</span></li>'.format(button_style)
        page_str_list.append(prev_html)

        # Next button
        if self.has_next:
            self.query_dict.setlist(self.page_param, [self.next_cursor])
            self.query_dict.setlist('dir', ['next'])
            next_html = '<li><a href="?{}" style="{}">下一页 ></a></li>'.format(self.query_dict.urlencode(), button_style)
        else:
            next_html = '<li><span style="{};opacity:0.4;cursor:default;">下一页 ></span></li>'.format(button_style)
        page_str_list.append(next_html)

        # Rows-per-page selector
        search_string = '''
            <li>
               <form style="float: left; margin-left: -1px; align-items: center;" method="get">
                <span style="font-weight: normal;color:#7e8e9e;">每页显示</span>
                <select name="rows_per_page" onchange="this.form.submit()" style="border-radius: 0;background-color: #040c1f;color: #3498db; height: 29px; border: 1px solid #4778c7;border-radius:19px">
                    {}
                </select>
                条
            </form>
            </li>
        '''.format(''.join(['<option value="{}"{}>{}</option>'.format(option, ' selected' if self.page_size == option else '', option) for option in self.rows_per_page_options]))
        page_str_list.append(search_string)

        # Estimated total
        page_str_list.append(
            '<div style="align-items: center; justify-content: center; height: 28px; margin-left:10px;">'
            '<span style="font-weight:normal;">'
            '<label style="color:#7e8e9e;">共约 </label>'
            '<button style="position: relative;display: inline-block;padding: 0; background-color: #204660; color:#fff; '
            'text-decoration: none;border-radius:19px; height:40px;border: 1px solid #4778c7;width:60px; '
            'line-height: 40px; vertical-align: middle; text-align: center;">{}</button>'
            '<label style="color:#7e8e9e;"> 条记录</label></span></div>'.format(self.estimated_total)
        )
        page_string = mark_safe("".join(page_str_list))

        return page_string















def build_facet_result(queryset, field, offset=0, limit=FACET_PAGE_SIZE):
    if field == 'favicon':
        from django.db.models import Count, Max

        grouped_qs = (
            queryset.exclude(favicon_md5__isnull=True)
            .exclude(favicon_md5='')
            .values('favicon_md5')
            .annotate(count=Count('id'), favicon=Max('favicon'))
            .order_by('-count', 'favicon_md5')
        )
        total_count = grouped_qs.count()
        rows = list(grouped_qs[offset:offset + FAVICON_PAGE_SIZE + 1])
        items = [
            {'name': item['favicon_md5'], 'count': item['count'], 'favicon': item['favicon'] or ''}
            for item in rows[:FAVICON_PAGE_SIZE]
            if item['favicon_md5']
        ]
        has_more = len(rows) > FAVICON_PAGE_SIZE
        next_offset = offset + len(items)
        return {
            'items': items,
            'has_more': has_more,
            'next_offset': next_offset,
            'count_label': str(total_count),
        }
    if field == 'cert':
        from django.db.models import Count

        grouped_qs = (
            queryset.exclude(cert_common_name__isnull=True)
            .exclude(cert_common_name='')
            .values('cert_common_name')
            .annotate(count=Count('id'))
            .order_by('-count', 'cert_common_name')
        )
        total_count = grouped_qs.count()
        rows = list(grouped_qs[offset:offset + limit + 1])
        items = [
            {'name': item['cert_common_name'], 'count': item['count']}
            for item in rows[:limit]
            if item['cert_common_name']
        ]
        has_more = len(rows) > limit
        next_offset = offset + len(items)
        return {
            'items': items,
            'has_more': has_more,
            'next_offset': next_offset,
            'count_label': str(total_count),
        }
    if field == 'ipc':
        from django.db.models import Count, F, Value, Func
        from django.db.models.functions import Concat
        from django.db.models import CharField

        class SplitPart(Func):
            function = 'split_part'
            arity = 3

        ip_queryset = queryset.filter(ip__regex=r'^\d+\.\d+\.\d+\.\d+$')
        c_segment_expr = Concat(
            SplitPart(F('ip'), Value('.'), Value(1)), Value('.'),
            SplitPart(F('ip'), Value('.'), Value(2)), Value('.'),
            SplitPart(F('ip'), Value('.'), Value(3)), Value('.0/24'),
            output_field=CharField(),
        )
        grouped_qs = (
            ip_queryset.annotate(c_seg=c_segment_expr)
            .values('c_seg')
            .annotate(count=Count('id'))
            .order_by('-count', 'c_seg')
        )
        total_count = grouped_qs.count()
        rows = list(grouped_qs[offset:offset + limit + 1])
        items = [
            {'name': item['c_seg'], 'count': item['count']}
            for item in rows[:limit]
            if item['c_seg']
        ]
    elif field == 'product':
        sql, params = queryset.query.sql_with_params()
        grouped_sql = f"""
            SELECT p AS facet_value, COUNT(*) as cnt
            FROM ({sql}) AS _sub, unnest(_sub.products) AS p
            WHERE p IS NOT NULL AND p <> ''
            GROUP BY p
            UNION ALL
            SELECT p AS facet_value, COUNT(*) as cnt
            FROM ({sql}) AS _sub, unnest(_sub.dir_products) AS p
            WHERE p IS NOT NULL AND p <> ''
            GROUP BY p
        """
        merged_sql = f"""
            SELECT facet_value, SUM(cnt) as cnt
            FROM ({grouped_sql}) AS unioned
            GROUP BY facet_value
        """
        page_sql = f"""
            SELECT facet_value, cnt
            FROM ({merged_sql}) AS merged_rows
            ORDER BY cnt DESC, facet_value ASC
            LIMIT %s OFFSET %s
        """
        # subquery appears twice in UNION ALL — duplicate params to match
        doubled_params = [*params, *params]
        count_sql = f"SELECT COUNT(*) FROM ({merged_sql}) AS merged_rows"
        with connection.cursor() as cursor:
            cursor.execute(count_sql, doubled_params)
            total_count = cursor.fetchone()[0]
            cursor.execute(page_sql, [*doubled_params, limit + 1, offset])
            rows = cursor.fetchall()
        items = [
            {'name': row[0], 'count': row[1]}
            for row in rows[:limit]
            if row[0]
        ]
    elif field in {'vuln', 'cve'}:
        sql, params = queryset.query.sql_with_params()
        exp_result_table = connection.ops.quote_name(models.auto_scan_exp_result._meta.db_table)
        exp_table = connection.ops.quote_name(models.EXP._meta.db_table)
        exp_fk_column = connection.ops.quote_name(models.auto_scan_exp_result._meta.get_field('EXP_id').column)
        exp_id_column = connection.ops.quote_name(models.EXP._meta.pk.column)
        facet_column = connection.ops.quote_name('title' if field == 'vuln' else models.EXP._meta.get_field('CVE').column)
        grouped_sql = f"""
            SELECT exp.{facet_column} AS facet_value, COUNT(*) AS cnt
            FROM ({sql}) AS identify
            JOIN {exp_result_table} AS exp_result
              ON identify.id = exp_result.identify_result_id
             AND exp_result.task_type IN (1, 2, 3)
            JOIN {exp_table} AS exp
              ON exp_result.{exp_fk_column} = exp.{exp_id_column}
            WHERE exp.{facet_column} IS NOT NULL
              AND exp.{facet_column} <> ''
            GROUP BY exp.{facet_column}
        """
        page_sql = f"""
            SELECT facet_value, cnt
            FROM ({grouped_sql}) AS grouped_rows
            ORDER BY cnt DESC, facet_value ASC
            LIMIT %s OFFSET %s
        """
        count_sql = f"SELECT COUNT(*) FROM ({grouped_sql}) AS grouped_rows"
        with connection.cursor() as cursor:
            cursor.execute(count_sql, params)
            total_count = cursor.fetchone()[0]
            cursor.execute(page_sql, [*params, limit + 1, offset])
            rows = cursor.fetchall()
        items = [
            {'name': row[0], 'count': row[1]}
            for row in rows[:limit]
            if row[0]
        ]
    else:
        from django.db.models import Count

        grouped_qs = (
            queryset.values(field)
            .annotate(count=Count('id'))
            .order_by('-count', field)
        )
        total_count = grouped_qs.count()
        rows = list(grouped_qs[offset:offset + limit + 1])
        # 把 NULL 和空字符串合并为同一个 "(空)" facet 项，与搜索 !field:"*" 的口径一致
        empty_items = [r for r in rows if not r[field]]
        empty_merged_count = sum(r['count'] for r in empty_items)
        items = []
        if empty_merged_count:
            items.append({'name': '(空)', 'count': empty_merged_count})
        items += [
            {'name': str(r[field]), 'count': r['count']}
            for r in rows
            if r[field]
        ]
        items = items[:limit]

    has_more = len(rows) > limit
    next_offset = offset + len(items)
    return {
        'items': items,
        'has_more': has_more,
        'next_offset': next_offset,
        'count_label': str(total_count),
    }




def get_product(ip):
    filtered_data = models.auto_scan_indentify_result.objects.filter(target__icontains=ip)
    pro_port_product_info = []
    port_info = []
    for obj in filtered_data:
        port = obj.port
        protocol = obj.protocol
        if port not in port_info:
            port_info.append(port)
        for product in (obj.products or []):
            _info = f"protocol:{protocol}_port:{port}_product:{product}"
            if _info not in pro_port_product_info:
                pro_port_product_info.append(_info)
    return (pro_port_product_info, port_info)


def build_port_overview(ip, current_target, zone_id=None):
    rows = []
    seen = {}
    qs = models.auto_scan_indentify_result.objects.filter(ip=ip)
    if zone_id:
        qs = qs.filter(zone_id=zone_id)
    for obj in qs.order_by('port', 'id'):
        key = (obj.protocol or '', obj.port)
        products_set = set(p for p in (obj.products or []) if p) | set(p for p in (obj.dir_products or []) if p)
        if key in seen:
            idx = seen[key]
            rows[idx]['products'] = sorted(set(rows[idx]['products']) | products_set)
            if not rows[idx]['is_current'] and obj.target == current_target:
                rows[idx]['is_current'] = True
                rows[idx]['target'] = obj.target or ''
            continue
        seen[key] = len(rows)
        rows.append({
            'protocol': obj.protocol or '',
            'port': obj.port,
            'target': obj.target or '',
            'products': sorted(products_set),
            'is_current': (obj.target == current_target),
        })

    rows.sort(key=lambda row: (0 if row['is_current'] else 1, row['port'], row['protocol']))
    return rows


def _attach_port_overview(items):
    for item in items:
        item.port_overview = [{
            'protocol': item.protocol,
            'port': item.port,
            'target': item.target,
            'products': item.products or [],
            'is_current': True,
        }]
        item.port_overview_has_more = True



def chart_data(data):
    try:
        x_axis = []
        y_axis = []
        for key,value in data.items():
            x_axis.append(key)
            y_axis.append(value)

        result = {
            'x_axis': x_axis,
            'y_axis': y_axis,
        }
        return result
    except Exception:
        traceback.print_exc()

display_fields = ["title","product","ipc","country","province","city","isp","port","protocol","status_code","uri_path"]

class ModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['target']
    class Meta:
        model = models.auto_scan_tasks
        exclude = ["creat_time","status","process","startTime","endTime","update_time","current_line"]

def Task_result(request,uid,standalone=None):
    _t_global_start = time.time()
    search_string = ""
    condition_tree = None
    parse_error = False
    favicon_offset = max(int(request.GET.get('favicon_offset', '0') or 0), 0)
    try:
        search_string = request.GET.get('search_data', "")
    except:
        traceback.print_exc()

    # 用户可显式传 zone_id 切换区域；未传时默认用任务自身所属 zone
    req_zone_id = request.GET.get('zone_id', '') or None
    intranet_only = False
    if req_zone_id:
        if req_zone_id == '__intranet__':
            intranet_only = True
            req_zone_id = None
        else:
            try:
                req_zone_id = int(req_zone_id)
            except (ValueError, TypeError):
                req_zone_id = None
    if intranet_only:
        task_zone_id = None  # 交由下方 exclude 处理
    elif req_zone_id is not None:
        task_zone_id = req_zone_id
    else:
        _task_zone = models.auto_scan_tasks.objects.filter(id=uid).values("zone_id").first()
        task_zone_id = _task_zone["zone_id"] if _task_zone else None

    get_display_fields = request.GET.get('selectedOptionsInput', "")

    if get_display_fields:
        global display_fields
        get_display_fields = json.loads(get_display_fields)
        display_fields = get_display_fields

    if search_string:
        scoped_search = f'({search_string}) && task_id:"{uid}"'
        try:
            condition_tree = parse_condition(scoped_search)
            query_condition = to_query_structure(condition_tree)
            data = models.auto_scan_indentify_result.objects.filter(query_condition).order_by("-id")
        except Exception:
            search_string = ""
            data = models.auto_scan_indentify_result.objects.none().order_by("-id")
            parse_error = True
    else:
        data = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=uid).order_by("-id")

    # zone 过滤：intranet_only 排除公网，否则限定特定 zone
    if intranet_only:
        data = data.exclude(zone__code='public')
    elif task_zone_id is not None:
        data = data.filter(zone_id=task_zone_id)
    page_object = Pagination(request, data)

    items = list(page_object.page_queryset)

    # Batch: query vulns by identify_result_id (no task_id filter, cross-task visible)
    vuln_rows = []
    if items:
        asset_ids = [item.id for item in items if item.id]
        if asset_ids:
            vuln_rows = list(
                models.auto_scan_exp_result.objects
                .filter(identify_result_id__in=asset_ids, task_type__in=[1, 2, 3])
                .select_related('EXP_id')
                .order_by('-id')
            )
    vuln_by_key = {}
    for row in vuln_rows:
        vuln_by_key.setdefault(row.identify_result_id, []).append(row)

    related_vulns_map = {}

    for item in items:
        vulns = _build_related_vulns_from_rows(vuln_by_key.get(item.id, []))
        related_vulns_map[item.id] = vulns
        item.related_vulns = vulns
        item.country_code = _country_code(item.country or '')

    context = {
        'content': items,
        'field_statistics': {},
        'total_counts': {},
        'related_vulns_map': related_vulns_map,
        'page_string': page_object.html(),
        "search_string": search_string,
        "search_string_js": json.dumps(search_string).replace('</', '<\\/'),
        "display_fields": display_fields,
        "task_id": uid,
        "total": getattr(page_object, 'exact_total', None) or page_object.estimated_total,
        "parse_error": parse_error,
    }

    standalone = (standalone == '1') or (request.GET.get('standalone') == '1')
    if standalone:
        task_row = models.auto_scan_tasks.objects.filter(id=uid).values("task_name").first()
        context['task_name'] = task_row["task_name"] if task_row else ""
        context['field_statistics_json'] = '{}'
        context['total_counts_json'] = '{}'
        context['page_object'] = page_object
        context['global_mode'] = False
        context['vuln_total'] = 0
        context['favicon_facet_page_size'] = FAVICON_PAGE_SIZE

        if request.GET.get('format') == 'json':
            if parse_error:
                logger.debug(f'[TIMING Task_result] TOTAL|ms={int((time.time()-_t_global_start)*1000)}|parse_error=True')
                return JsonResponse({'status': False, 'error': '搜索语法解析失败，请检查搜索条件'})
            logger.debug(f'[TIMING Task_result] step=1|desc=search_parse+main_query|ms={int((time.time()-_t_global_start)*1000)}|rows={len(items)}')
            deep_search_mode = _has_deep_search(condition_tree)
            favicon_facet = {'items': [], 'has_more': False, 'next_offset': 0, 'count_label': ''} if deep_search_mode else build_facet_result(data, 'favicon', favicon_offset, FAVICON_PAGE_SIZE)
            _t_pre_json = time.time()
            _fv_items = len(favicon_facet['items'])
            logger.debug(f'[TIMING Task_result] step=2|desc=favicon_facet|ms={int((_t_pre_json-_t_global_start)*1000)}|items={_fv_items}|skipped={deep_search_mode}')
            payload = _build_identify_results_payload(
                items=items,
                related_vulns_map=related_vulns_map,
                page_object=page_object,
                favicon_facet=favicon_facet,
                deep_search_mode=deep_search_mode,
                scope='task',
                facet_endpoint=reverse('api_task_facet', kwargs={'uid': uid}),
                search_string=search_string,
                task_id=uid,
                task_name=context.get('task_name', ''),
            )
            logger.debug(f'[TIMING Task_result] step=3|desc=build_results+json|ms={int((time.time()-_t_pre_json)*1000)}')
            logger.debug(f'[TIMING Task_result] TOTAL|ms={int((time.time()-_t_global_start)*1000)}')
            return JsonResponse(payload)

        deep_search_mode = _has_deep_search(condition_tree)
        favicon_facet = {'items': [], 'has_more': False, 'next_offset': 0, 'count_label': ''} if deep_search_mode else build_facet_result(data, 'favicon', favicon_offset, FAVICON_PAGE_SIZE)
        context['favicon_items'] = favicon_facet['items']
        context['favicon_items_json'] = json.dumps(favicon_facet['items'])
        context['favicon_has_more'] = favicon_facet['has_more']
        context['favicon_next_offset'] = favicon_facet['next_offset']
        context['favicon_total'] = favicon_facet['count_label']

        _attach_port_overview(items)

        return render(request, "project/expload/task_manage/auto_scan_identify_result_standalone.html", context)

    return render(request, "project/expload/task_manage/auto_scan_identify_result.html", context)



def task_result_api(request, uid):
    request.GET = request.GET.copy()
    request.GET['format'] = 'json'
    return Task_result(request, uid, standalone='1')


def facet(request, uid):
    facet_request, error_response = _validate_facet_request(request)
    if error_response:
        return error_response

    assert facet_request is not None
    field = facet_request['field']
    search_string = facet_request['search_string']
    offset = facet_request['offset']

    # 用户可显式传 zone_id 切换区域；未传时默认用任务自身所属 zone
    req_zone_id = request.GET.get('zone_id', '') or None
    intranet_only = False
    if req_zone_id:
        if req_zone_id == '__intranet__':
            intranet_only = True
            req_zone_id = None
        else:
            try:
                req_zone_id = int(req_zone_id)
            except (ValueError, TypeError):
                req_zone_id = None
    if intranet_only:
        task_zone_id = None  # 交由下方 exclude 处理
    elif req_zone_id is not None:
        task_zone_id = req_zone_id
    else:
        _task_zone = models.auto_scan_tasks.objects.filter(id=uid).values("zone_id").first()
        task_zone_id = _task_zone["zone_id"] if _task_zone else None

    if search_string:
        try:
            scoped_search = f'({search_string}) && task_id:"{uid}"'
            condition_tree = parse_condition(scoped_search)
            query_condition = to_query_structure(condition_tree)
            queryset = models.auto_scan_indentify_result.objects.filter(query_condition)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': False, 'error': f'搜索语法解析失败: {e}'}, status=400)
    else:
        queryset = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=uid)

    # zone 过滤：intranet_only 排除公网，否则限定特定 zone
    if intranet_only:
        queryset = queryset.exclude(zone__code='public')
    elif task_zone_id is not None:
        queryset = queryset.filter(zone_id=task_zone_id)

    result = build_facet_result(queryset, field, offset=offset)
    return JsonResponse({'status': 'ok', 'field': field, **result})


def task_result_html(request, result_id):
    """Serve raw HTML source code as plain text (no script execution) in a new tab."""
    import ast
    if request.method != 'GET':
        return HttpResponse(status=405)
    item = models.auto_scan_indentify_result.objects.filter(id=result_id).values('html', 'target').first()
    if not item or not item.get('html'):
        return HttpResponse(
            '<html><body style="font-family:sans-serif;padding:40px;color:#78716c;"><p>该记录无 HTML 内容</p></body></html>'
        )
    raw = item['html']
    # Content was stored as Python bytes repr, e.g.: b'<html>\\n<head>...'
    # Use ast.literal_eval to correctly parse bytes literal including multi-byte UTF-8 sequences
    try:
        html_bytes = ast.literal_eval(raw)
        if isinstance(html_bytes, bytes):
            html = html_bytes.decode('utf-8', errors='replace')
        else:
            html = str(html_bytes)
    except (ValueError, SyntaxError):
        html = raw
    # HTML-escape for safe display as plain text
    safe = html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    page = (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">'
        '<title>响应源码</title>'
        '<style>'
        'body{background:#f5f3f0;margin:0;padding:20px 28px;font-family:"DM Sans",monospace;}'
        'pre{background:#fafaf9;border:1px solid #e7e5e4;border-radius:6px;padding:20px 24px;overflow-x:auto;'
        'font-size:13px;line-height:1.65;white-space:pre-wrap;word-break:break-all;color:#292524;}'
        '</style></head><body><pre>' + safe + '</pre></body></html>'
    )
    return HttpResponse(page, content_type='text/html; charset=utf-8')

def vuln_result_text(request, result_id):
    if request.method != 'GET':
        return HttpResponse(status=405)
    item = models.auto_scan_exp_result.objects.filter(id=result_id).select_related('EXP_id').values('result', 'EXP_id__title', 'EXP_id__CVE').first()
    if not item:
        return JsonResponse({'status': False, 'error': 'not found'}, status=404)
    return JsonResponse({
        'status': 'ok',
        'result': item['result'] or '',
        'plugin_name': item['EXP_id__title'] or '',
        'cve': item['EXP_id__CVE'] or '',
    })


def TaskResult_download(request):
    try:
        task_id = request.GET.get("uid")
        queryset = models.auto_scan_indentify_result.objects.filter(task_relations__task_id=task_id)
        search_data = request.GET.get("search_data", "")
        if search_data:
            try:
                condition_tree = parse_condition(search_data)
                query_condition = to_query_structure(condition_tree)
                queryset = queryset.filter(query_condition)
            except Exception:
                pass

        zone_id_raw = request.GET.get('zone_id', '') or None
        intranet_only = False
        zone_id = None
        if zone_id_raw:
            if zone_id_raw == '__intranet__':
                intranet_only = True
            else:
                try:
                    zone_id = int(zone_id_raw)
                except (ValueError, TypeError):
                    pass
        if intranet_only:
            queryset = queryset.exclude(zone__code='public')
        elif zone_id is not None:
            queryset = queryset.filter(zone_id=zone_id)

        task_queryset = models.auto_scan_tasks.objects.filter(id=task_id).values("task_name").first()
        task_name = task_queryset["task_name"]

        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=EXPreuslt.csv'

        csv_data = io.StringIO()
        writer = csv.writer(csv_data, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL, lineterminator='\n')

        headers = ["id",'task_name', 'url', 'product','creatime']
        writer.writerow(headers)

        for item in queryset:
            creatime = item.creatime
            createtime_str = creatime.strftime("%Y-%m-%d %H:%M:%S")
            url = f"{item.protocol or 'http'}://{item.host or ''}:{item.port or 0}{item.uri_path or ''}"
            row = [item.id, task_name, url, ', '.join(item.products or []), createtime_str]  
            writer.writerow(row) 
        response.write(codecs.BOM_UTF8)
        response.write(csv_data.getvalue().encode('utf-8'))
        csv_data.close()
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
    except Exception as e:
        traceback.print_exc()
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "TaskResult_download error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=EXPreuslt.csv'
        return response


# ── Global asset search (cross-task) ──

def global_asset_search(request):
    _t0 = time.time()
    search_string = request.GET.get('search_data', '')
    zone_id_raw = request.GET.get('zone_id', '') or None
    zone_id = None
    intranet_only = False
    if zone_id_raw:
        if zone_id_raw == '__intranet__':
            intranet_only = True
        else:
            try:
                zone_id = int(zone_id_raw)
            except (ValueError, TypeError):
                pass
    condition_tree = None
    parse_error = False
    favicon_offset = max(int(request.GET.get('favicon_offset', '0') or 0), 0)
    if search_string:
        try:
            condition_tree = parse_condition(search_string)
            query_condition = to_query_structure(condition_tree)
            data = models.auto_scan_indentify_result.objects.filter(query_condition).order_by('-id')
        except Exception:
            search_string = ""
            data = models.auto_scan_indentify_result.objects.none().order_by('-id')
            parse_error = True
    else:
        data = models.auto_scan_indentify_result.objects.all().order_by('-id')
    if intranet_only:
        data = data.exclude(zone__code='public')
    elif zone_id:
        data = data.filter(zone_id=zone_id)
    page_object = Pagination(request, data)

    items = list(page_object.page_queryset)
    logger.debug(f'[TIMING global_asset_search] step=1|desc=search_parse+main_query|ms={int((time.time()-_t0)*1000)}|rows={len(items)}')
    _t1 = time.time()

    item_task_map = {}
    if items:
        item_ids = [item.id for item in items]
        relation_rows = models.AssetTaskRelation.objects.filter(
            identify_result_id__in=item_ids
        ).values_list('identify_result_id', 'task_id')
        for rid, tid in relation_rows:
            item_task_map.setdefault(rid, []).append(tid)

    # Batch: query vulns by identify_result_id (no task_id filter, cross-task visible)
    vuln_rows = []
    if items:
        item_ids = [item.id for item in items if item.id]
        if item_ids:
            vuln_rows = list(
                models.auto_scan_exp_result.objects
                .filter(identify_result_id__in=item_ids, task_type__in=[1, 2, 3])
                .select_related('EXP_id')
                .order_by('-id')
            )
    vuln_by_key = {}
    for row in vuln_rows:
        vuln_by_key.setdefault(row.identify_result_id, []).append(row)

    related_vulns_map = {}
    for item in items:
        vulns = _build_related_vulns_from_rows(vuln_by_key.get(item.id, []))
        related_vulns_map[item.id] = vulns
        item.related_vulns = vulns
        item.country_code = _country_code(item.country or '')
    logger.debug(f'[TIMING global_asset_search] step=2|desc=related_vulns|ms={int((time.time()-_t1)*1000)}|vuln_rows={len(vuln_rows)}')

    _t2 = time.time()

    _exact = getattr(page_object, 'exact_total', None)
    context = {
        'content': items,
        'field_statistics': {},
        'total_counts': {},
        'related_vulns_map': related_vulns_map,
        'page_string': page_object.html(),
        'search_string': search_string,
        'search_string_js': json.dumps(search_string).replace('</', '<\\/'),
        'display_fields': display_fields,
        'task_id': 0,
        'total': _exact if _exact is not None else page_object.estimated_total,
        'task_name': '全局资产',
        'vuln_total': 0,
        'page_object': page_object,
        'field_statistics_json': '{}',
        'total_counts_json': '{}',
        'global_mode': True,
        'parse_error': parse_error,
        'favicon_facet_page_size': FAVICON_PAGE_SIZE,
        'favicon_items': [],
        'favicon_items_json': '[]',
        'favicon_total': '0',
        'favicon_has_more': False,
        'favicon_next_offset': 0,
        'favicon_offset': 0,
    }

    if request.GET.get('format') == 'json':
        if parse_error:
            logger.debug(f'[TIMING global_asset_search] TOTAL|ms={int((time.time()-_t0)*1000)}|parse_error=True')
            return JsonResponse({'status': False, 'error': '搜索语法解析失败，请检查搜索条件'})
        deep_search_mode = _has_deep_search(condition_tree)
        favicon_facet = {'items': [], 'has_more': False, 'next_offset': 0, 'count_label': ''} if deep_search_mode else build_facet_result(data, 'favicon', favicon_offset, FAVICON_PAGE_SIZE)
        _fv_items = len(favicon_facet['items'])
        logger.debug(f'[TIMING global_asset_search] step=3|desc=favicon_facet|ms={int((time.time()-_t2)*1000)}|favicon_items={_fv_items}|skipped={deep_search_mode}')
        _t3 = time.time()

        payload = _build_identify_results_payload(
            items=items,
            related_vulns_map=related_vulns_map,
            page_object=page_object,
            favicon_facet=favicon_facet,
            deep_search_mode=deep_search_mode,
            scope='global',
            facet_endpoint=reverse('api_global_facet'),
            search_string=search_string,
            task_name='全局资产',
        )
        logger.debug(f'[TIMING global_asset_search] step=4|desc=build_results+json|ms={int((time.time()-_t3)*1000)}')
        logger.debug(f'[TIMING global_asset_search] TOTAL|ms={int((time.time()-_t0)*1000)}')
        return JsonResponse(payload)

    deep_search_mode = _has_deep_search(condition_tree)
    favicon_facet = {'items': [], 'has_more': False, 'next_offset': 0, 'count_label': ''} if deep_search_mode else build_facet_result(data, 'favicon', 0, FAVICON_PAGE_SIZE)
    context['favicon_items'] = favicon_facet['items']
    context['favicon_items_json'] = json.dumps(favicon_facet['items'])
    context['favicon_total'] = favicon_facet['count_label']
    context['favicon_has_more'] = favicon_facet['has_more']
    context['favicon_next_offset'] = favicon_facet['next_offset']

    _attach_port_overview(items)

    logger.debug(f'[TIMING global_asset_search] TOTAL(html)|ms={int((time.time()-_t0)*1000)}')
    return render(request, 'project/expload/task_manage/auto_scan_identify_result_standalone.html', context)



def global_asset_search_api(request):
    request.GET = request.GET.copy()
    request.GET['format'] = 'json'
    return global_asset_search(request)


def _build_related_vulns_from_rows(rows):
    seen = set()
    vulns = []
    for obj in rows:
        exp = obj.EXP_id
        key = (exp.title if exp else '', exp.CVE if exp and exp.CVE else '', obj.product or '')
        if key in seen:
            continue
        seen.add(key)
        vulns.append({
            'id': obj.id,
            'exp_id': exp.id if exp else None,
            'plugin_name': exp.title if exp else '',
            'cve': exp.CVE if exp and exp.CVE else '',
            'product': obj.product or '',
            'target': obj.target or '',
        })
    return vulns


def global_facet(request):
    facet_request, error_response = _validate_facet_request(request)
    if error_response:
        return error_response

    assert facet_request is not None
    field = facet_request['field']
    search_string = facet_request['search_string']
    offset = facet_request['offset']

    if search_string:
        try:
            condition_tree = parse_condition(search_string)
            query_condition = to_query_structure(condition_tree)
            queryset = models.auto_scan_indentify_result.objects.filter(query_condition)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': False, 'error': f'搜索语法解析失败: {e}'}, status=400)
    else:
        queryset = models.auto_scan_indentify_result.objects.all()

    zone_id_raw = request.GET.get('zone_id', '') or None
    if zone_id_raw:
        if zone_id_raw == '__intranet__':
            queryset = queryset.exclude(zone__code='public')
        else:
            try:
                zone_id = int(zone_id_raw)
                queryset = queryset.filter(zone_id=zone_id)
            except (ValueError, TypeError):
                pass

    result = build_facet_result(queryset, field, offset=offset)
    return JsonResponse({'status': 'ok', 'field': field, **result})



def task_facet_api(request, uid):
    return facet(request, uid)


def global_facet_api(request):
    return global_facet(request)


FACET_ALLOWED_FIELDS = {
    'protocol', 'port', 'title', 'country', 'province', 'city', 'isp',
    'status_code', 'ipc', 'product', 'vuln', 'cve', 'favicon',
    'cert', 'cert_org', 'cert_org_unit', 'uri_path',
    'icp', 'copyright',
}


def _validate_facet_request(request):
    field = request.GET.get('field', '')
    search_string = request.GET.get('search_data', '')
    offset = max(int(request.GET.get('offset', '0') or 0), 0)
    if field not in FACET_ALLOWED_FIELDS:
        return None, JsonResponse({'status': False, 'error': f'invalid field: {field}'}, status=400)
    return {
        'field': field,
        'search_string': search_string,
        'offset': offset,
    }, None


def port_overview_more(request):
    ip = request.GET.get('ip', '')
    offset = max(int(request.GET.get('offset', '0') or 0), 0)
    limit = max(int(request.GET.get('limit', '20') or 0), 1)
    current_target = request.GET.get('current_target', '')
    zone_id = request.GET.get('zone_id', '') or None
    if zone_id:
        try:
            zone_id = int(zone_id)
        except (ValueError, TypeError):
            zone_id = None
    if not ip:
        return JsonResponse({'status': 'error', 'error': 'ip required'}, status=400)
    all_rows = build_port_overview(ip, current_target, zone_id=zone_id)
    total = len(all_rows)
    rows = all_rows[offset:offset + limit]
    return JsonResponse({
        'status': 'ok',
        'rows': rows,
        'total': total,
        'has_more': (offset + len(rows)) < total,
    })


# ── IP detail (new tab page) ──

def ip_detail_api(request):
    ip = (request.GET.get('ip') or '').strip()
    zone_id = request.GET.get('zone_id', '') or None
    if zone_id:
        try:
            zone_id = int(zone_id)
        except (ValueError, TypeError):
            zone_id = None
    if not ip:
        return JsonResponse({'status': 'error', 'error': 'ip required'}, status=400)

    qs = models.auto_scan_indentify_result.objects.filter(ip=ip)
    if zone_id:
        qs = qs.filter(zone_id=zone_id)
    assets = list(qs.order_by('port', 'id'))
    if not assets:
        return JsonResponse({'status': 'ok', 'ip': ip, 'assets': []})

    result_ids = [a.id for a in assets]
    target_map = {a.id: a.target or '' for a in assets}

    # Asset → task_id mapping via AssetTaskRelation
    asset_tasks = {}
    for rel in models.AssetTaskRelation.objects.filter(identify_result_id__in=result_ids).values('identify_result_id', 'task_id'):
        asset_tasks.setdefault(rel['identify_result_id'], []).append(rel['task_id'])

    # Batch vulns: query by identify_result_id (no task_id filter, cross-task visible)
    vuln_rows = []
    if assets:
        asset_ids = [a.id for a in assets if a.id]
        if asset_ids:
            vuln_rows = list(
                models.auto_scan_exp_result.objects
                .filter(identify_result_id__in=asset_ids, task_type__in=[1, 2, 3])
                .select_related('EXP_id')
                .order_by('-id')
            )
    vuln_by_key = {}
    for vr in vuln_rows:
        vuln_by_key.setdefault(vr.identify_result_id, []).append(vr)

    # Batch dirscan results
    dirscan_q = Q()
    for a in assets:
        dirscan_q |= Q(host=a.host, port=a.port)
    dirscan_rows = list(
        models.auto_scan_directory_result.objects.filter(dirscan_q).order_by('uri_path')
    ) if assets else []
    dirscan_by_key = {}
    for dr in dirscan_rows:
        dirscan_by_key.setdefault((dr.host, dr.port), []).append(dr)

    # Serialize
    result = []
    for a in assets:
        vulns_flat = []
        seen = set()
        for vr in vuln_by_key.get(a.id, []):
            exp = vr.EXP_id
            key = (exp.title if exp else '', exp.CVE if exp and exp.CVE else '', vr.product or '')
            if key in seen:
                continue
            seen.add(key)
            vulns_flat.append({
                'id': vr.id,
                'plugin_name': exp.title if exp else '',
                'cve': exp.CVE if exp and exp.CVE else '',
                'product': vr.product or '',
            })
        dirscan_items = []
        for dr in dirscan_by_key.get((a.host, a.port), []):
            dirscan_items.append({
                'uri_path': dr.uri_path or '',
                'status_code': dr.status_code,
                'title': dr.title or '',
                'products': dr.products or [],
                'content_length': dr.content_length,
            })
        result.append({
            'id': a.id,
            'protocol': a.protocol or '',
            'port': a.port,
            'host': a.host or '',
            'target': a.target or '',
            'products': sorted(set((a.products or []) + (a.dir_products or []))),
            'title': a.title or '',
            'status_code': a.status_code,
            'cert_common_name': a.cert_common_name or '',
            'cert_org': a.cert_org or '',
            'related_vulns': vulns_flat,
            'dirscan_results': dirscan_items,
        })

    return JsonResponse({'status': 'ok', 'ip': ip, 'assets': result})


# ── Export task dispatch (POST) ──

EXPORT_ALLOWED_FIELDS = {
    "title", "product", "ipc", "country", "province", "city", "isp",
    "port", "protocol", "status_code", "uri_path", "url", "host", "ip",
    "favicon_md5", "cert_org", "cert_common_name", "cert_serial",
    "vuln", "cve",
}
EXPORT_LIMIT_MAX = 50000


def _build_dirscan_filter_kwargs(request):
    """从 request.GET 解析 dirscan 过滤条件，返回 (filter_kwargs, base_filter)。"""
    host = request.GET.get("host", "").strip()
    port_str = request.GET.get("port", "").strip()
    protocol = request.GET.get("protocol", "").strip()
    task_id_str = request.GET.get("task_id", "").strip()

    by_task = bool(task_id_str)
    base_filter = {}
    if by_task:
        try:
            base_filter["task_id"] = int(task_id_str)
        except (ValueError, TypeError):
            return None, None, True  # error
    else:
        if not host or not port_str:
            return None, None, True
        try:
            port = int(port_str)
        except (ValueError, TypeError):
            return None, None, True
        base_filter = {"host": host, "port": port}
        if protocol:
            base_filter["protocol"] = protocol

    # 列筛选参数
    extra = {}
    for param, field in [
        ("status_code", "status_code"),
        ("uri_path", "uri_path"),
        ("product", "products"),
        ("title", "title"),
        ("cert_org", "cert_org"),
        ("cert_org_unit", "cert_org_unit"),
        ("cert_common_name", "cert_common_name"),
    ]:
        val = request.GET.get(param, "").strip()
        if val:
            if field == "products":
                extra["products__contains"] = [val]
            else:
                extra[field] = val

    target_search = request.GET.get("target_search", "").strip()
    if target_search:
        extra["target__icontains"] = target_search

    return {**base_filter, **extra}, base_filter, False


def dirscan_results_filters_api(request):
    if request.method != "GET":
        return JsonResponse({"status": False, "error": "仅支持 GET"}, status=405)

    filter_kwargs, _, err = _build_dirscan_filter_kwargs(request)
    if err:
        return JsonResponse({"status": False, "error": "缺少 host+port 或 task_id 参数"}, status=400)

    qs = models.auto_scan_directory_result.objects.filter(**filter_kwargs)

    status_codes = sorted(
        set(qs.values_list("status_code", flat=True).distinct()),
        key=lambda x: (x is None, x or 0),
    )
    titles = sorted(
        set(t for t in qs.values_list("title", flat=True).distinct() if t),
    )
    cert_orgs = sorted(
        set(c for c in qs.values_list("cert_org", flat=True).distinct() if c),
    )
    cert_org_units = sorted(
        set(c for c in qs.values_list("cert_org_unit", flat=True).distinct() if c),
    )
    cert_common_names = sorted(
        set(c for c in qs.values_list("cert_common_name", flat=True).distinct() if c),
    )
    uri_paths = sorted(
        set(u for u in qs.values_list("uri_path", flat=True).distinct() if u),
    )

    # ArrayField 的 DISTINCT 不支持跨行展开，Python 侧去重
    all_products = set()
    for row in qs.values_list("products", flat=True):
        if row:
            for p in row:
                if p:
                    all_products.add(p)
    products = sorted(all_products)

    return JsonResponse({
        "status": "ok",
        "status_codes": status_codes,
        "titles": titles,
        "cert_orgs": cert_orgs,
        "cert_org_units": cert_org_units,
        "cert_common_names": cert_common_names,
        "uri_paths": uri_paths,
        "products": products,
    })


def dirscan_results_api(request):
    """GET /api/v1/assets/dirscan-results?host=example.com&port=443&protocol=http&page=1&rows_per_page=10"""
    if request.method != "GET":
        return JsonResponse({"status": False, "error": "仅支持 GET"}, status=405)

    filter_kwargs, base_filter, err = _build_dirscan_filter_kwargs(request)
    if err:
        return JsonResponse({"status": False, "error": "缺少 host+port 或 task_id 参数"}, status=400)

    # 仅检查是否存在（不返回分页数据）
    if request.GET.get("check_only") == "true":
        has = models.auto_scan_directory_result.objects.filter(**filter_kwargs).exists()
        return JsonResponse({"status": "ok", "has_dirscan": has})

    page = max(int(request.GET.get("page", "1") or "1"), 1)
    rows_per_page = max(min(int(request.GET.get("rows_per_page", "10") or "10"), 100), 1)
    queryset = models.auto_scan_directory_result.objects.filter(**filter_kwargs)
    sort = request.GET.get("sort", "")
    if sort == "content_length_desc":
        queryset = queryset.order_by(F("content_length").desc(nulls_last=True), "uri_path")
    elif sort == "content_length_asc":
        queryset = queryset.order_by(F("content_length").asc(nulls_last=True), "uri_path")
    else:
        queryset = queryset.order_by("uri_path")
    total = queryset.count()
    total_pages = (total + rows_per_page - 1) // rows_per_page
    offset = (page - 1) * rows_per_page
    page_rows = list(queryset[offset:offset + rows_per_page])
    results = []
    for r in page_rows:
        results.append({
            "id": r.id,
            "task_id": r.task_id,
            "ip": r.ip or "",
            "port": r.port,
            "uri_path": r.uri_path or "",
            "target": r.target or "",
            "status_code": r.status_code,
            "title": r.title or "",
            "products": r.products or [],
            "favicon": r.favicon or "",
            "favicon_md5": r.favicon_md5 or "",
            "cert_org": r.cert_org or "",
            "cert_org_unit": r.cert_org_unit or "",
            "cert_common_name": r.cert_common_name or "",
            "cert_serial": r.cert_serial or "",
            "content_length": r.content_length,
            "header": r.header or "",
            "html": r.html or "",
            "creatime": r.creatime.strftime("%Y-%m-%d %H:%M") if r.creatime else "",
        })
    return JsonResponse({
        "status": "ok",
        "results": results,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "rows_per_page": rows_per_page,
    })


@deny_user
def asset_export(request):
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "仅支持 POST"}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"status": False, "error": "请求体必须是 JSON"}, status=400)

    fields = body.get("fields", [])
    if not fields or not isinstance(fields, list):
        return JsonResponse({"status": False, "error": "请至少选择一个导出字段"}, status=400)
    for f in fields:
        if f not in EXPORT_ALLOWED_FIELDS:
            return JsonResponse({"status": False, "error": f"无效字段: {f}"}, status=400)

    export_limit_raw = body.get("export_limit", None)
    export_limit = None
    if export_limit_raw is not None and str(export_limit_raw).lower() != "all":
        try:
            export_limit = int(export_limit_raw)
            if export_limit < 1:
                return JsonResponse({"status": False, "error": "导出条数最小为 1"}, status=400)
            if export_limit > EXPORT_LIMIT_MAX:
                return JsonResponse({"status": False, "error": f"导出条数上限 {EXPORT_LIMIT_MAX}"}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({"status": False, "error": "导出条数必须是数字或 'all'"}, status=400)

    task_type = body.get("task_type", "global")
    if task_type not in ("global", "task"):
        return JsonResponse({"status": False, "error": "task_type 无效"}, status=400)

    task_id = body.get("task_id", None)
    task_name = str(body.get("task_name", "") or "").strip()[:256]
    if task_type == "task":
        if not task_id:
            return JsonResponse({"status": False, "error": "任务检索需提供 task_id"}, status=400)
        task_row = models.auto_scan_tasks.objects.filter(id=task_id).values("task_name").first()
        if not task_row:
            return JsonResponse({"status": False, "error": "任务不存在"}, status=400)
        task_name = task_name or task_row["task_name"]

    zone_id_raw = body.get("zone_id", None)
    zone_id = None
    if zone_id_raw is not None:
        if zone_id_raw == '__intranet__':
            zone_id = -1  # sentinel: 所有内网（排除公网）
        else:
            try:
                zone_id = int(zone_id_raw)
            except (ValueError, TypeError):
                pass

    search_string = body.get("search_string", "")
    include_vuln_result = "vuln" in fields and bool(body.get("include_vuln_result", True))

    export_task = models.ExportTask.objects.create(
        task_type=task_type,
        task_id=task_id,
        task_name=task_name,
        zone_id=zone_id,
        search_string=search_string,
        fields=fields,
        include_vuln_result=include_vuln_result,
        export_limit=export_limit,
        status="processing",
    )

    from app_cybersparker.tasks import run_export_task
    from app_cybersparker.services.celery_runtime_service import dispatch_task
    dispatch_task(run_export_task, export_task.id, queue="maintenance")

    return JsonResponse({
        "status": "ok",
        "export_task_id": export_task.id,
        "message": "导出任务已提交",
    })
