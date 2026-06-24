"""
共享资产检索查询解析器。

收口自:
- auto_scan_result.py（主版本 — 全局资产检索 / standalone 结果页）
- all_Indentify_result.py（后台识别结果列表）

以 auto_scan_result.py 为基准，合并 all_Indentify_result.py 的兼容逻辑。
"""
import re
from functools import reduce

from django.db import connection
from django.db.models import Q
from django.db.models.expressions import RawSQL

from app_cybersparker import models

CERT_SEARCH_FIELDS = ("cert_org", "cert_org_unit", "cert_common_name")


# ── 查询解析器入口 ────────────────────────────────────────

def parse_condition(condition_str):
    """解析用户输入的检索字符串 → 条件树 (dict)"""
    quoted = {}

    def _save(m):
        key = f'\x00Q{len(quoted)}\x00'
        quoted[key] = m.group(0)
        return key

    protected = re.sub(r'"[^"]*"', _save, condition_str)
    tokens = [token.strip() for token in re.findall(r'\(|\)|\|\||&&|[^|&()]+', protected) if token.strip()]
    for i, tok in enumerate(tokens):
        for key, orig in quoted.items():
            if key in tok:
                tokens[i] = tok.replace(key, orig)
                break
    return parse_logical_or(tokens)


def parse_logical_or(tokens):
    left_operand = parse_logical_and(tokens)
    if tokens and tokens[0] == '||':
        tokens.pop(0)
        right_operand = parse_logical_or(tokens)
        return {'operator': 'OR', 'operands': [left_operand, right_operand]}
    return left_operand


def parse_logical_and(tokens):
    left_operand = parse_primary(tokens)
    if tokens and tokens[0] == '&&':
        tokens.pop(0)
        right_operand = parse_logical_and(tokens)
        return {'operator': 'AND', 'operands': [left_operand, right_operand]}
    return left_operand


def parse_primary(tokens):
    token = tokens.pop(0)
    if token == '(':
        expression = parse_logical_or(tokens)
        if tokens.pop(0) != ')':
            raise ValueError('Mismatched parentheses')
        return expression
    # Check for deep search operator := first (exact substring match)
    if ':=' in token:
        field, value = token.split(':=', 1)
        return {'field': field.strip('"'), 'value': value.strip('"'), 'deep_search': True}
    field, value = re.split(r'[:=]', token, maxsplit=1)
    return {'field': field.strip('"'), 'value': value.strip('"')}


def _has_deep_search(condition):
    """递归检查条件树中是否有 deep_search 标记（:= 语法）"""
    if not isinstance(condition, dict):
        return False
    if condition.get('deep_search'):
        return True
    for operand in condition.get('operands', []):
        if _has_deep_search(operand):
            return True
    return False


# ── 字段查询构建 ──────────────────────────────────────────

def _build_html_tsvector_query(value):
    """HTML 快捷检索（: / =）— tsvector 全文匹配词条。

    子查询加 ORDER BY id DESC，强制 PG 走 idx_html_tsvector GIN 索引
    而非 PK 倒序扫 + 逐行计算 tsvector（后者 5756 行要 150ms，走 GIN 只需 0.7ms）。
    """
    tbl = models.auto_scan_indentify_result._meta.db_table
    return Q(id__in=RawSQL(
        f"SELECT id FROM {tbl} WHERE to_tsvector('simple', html) @@ plainto_tsquery('simple', %s) ORDER BY id DESC",
        [value],
    ))


def _build_html_deep_search_query(value):
    """HTML 深度检索（:=）— 子串 LIKE，PG 在 trigram/bigm 索引间按 cost 自选。"""
    tbl = models.auto_scan_indentify_result._meta.db_table
    return Q(id__in=RawSQL(
        f"SELECT id FROM {tbl} WHERE UPPER(html) LIKE UPPER(%s)",
        [f'%{value}%']
    ))


def build_cert_query(value):
    query = Q()
    for field_name in CERT_SEARCH_FIELDS:
        query |= Q(**{f"{field_name}__icontains": value})
    return query


def _build_not_null_query(field, negated=False):
    """构建字段不为空的 Q 查询。用于搜索 ctx.field:\"*\" 通配符。"""
    if field == "product":
        query = Q(products__isnull=False) & ~Q(products=[])
    elif field in {"html", "body"}:
        query = Q(html__isnull=False) & ~Q(html='')
    elif field == "header":
        query = Q(header__isnull=False) & ~Q(header='')
    elif field == "cert":
        query = (
            (Q(cert_org__isnull=False) & ~Q(cert_org='')) |
            (Q(cert_org_unit__isnull=False) & ~Q(cert_org_unit='')) |
            (Q(cert_common_name__isnull=False) & ~Q(cert_common_name=''))
        )
    elif field == "cert_serial":
        query = Q(cert_serial__isnull=False) & ~Q(cert_serial='')
    elif field in {"favicon", "favicon_md5"}:
        query = Q(favicon_md5__isnull=False) & ~Q(favicon_md5='')
    elif field in {"vuln", "cve"}:
        query = Q(id__in=build_related_exp_exists())
    elif field in {"province", "city", "isp", "copyright", "icp"}:
        query = Q(**{f"{field}__isnull": False}) & ~Q(**{field: ''})
    elif field in {"ip", "host", "uri_path"}:
        query = Q(**{f"{field}__isnull": False}) & ~Q(**{field: ''})
    elif field == "ipc":
        query = Q(ip__isnull=False) & ~Q(ip='')
    else:
        query = Q(**{f"{field}__isnull": False})
        CharField_fields = {"title", "country"}
        if field in CharField_fields:
            query = query & ~Q(**{field: ''})
    return ~query if negated else query


# ── 跨表查询辅助（vuln/cve） ──────────────────────────────

def build_related_exp_exists():
    """返回存在任意漏洞验证结果的资产 ID（用于 vuln/cve * 通配符）"""
    identify_table = connection.ops.quote_name(models.auto_scan_indentify_result._meta.db_table)
    exp_result_table = connection.ops.quote_name(models.auto_scan_exp_result._meta.db_table)
    identify_id_column = connection.ops.quote_name(models.auto_scan_indentify_result._meta.pk.column)
    return RawSQL(
        f"""
        SELECT identify.{identify_id_column}
        FROM {identify_table} AS identify
        JOIN {exp_result_table} AS exp_result
          ON identify.id = exp_result.identify_result_id
         AND exp_result.task_type IN (1, 2, 3)
        """,
        [],
    )


def build_related_exp_lookup(field, value):
    identify_table = connection.ops.quote_name(models.auto_scan_indentify_result._meta.db_table)
    exp_result_table = connection.ops.quote_name(models.auto_scan_exp_result._meta.db_table)
    exp_table = connection.ops.quote_name(models.EXP._meta.db_table)
    identify_id_column = connection.ops.quote_name(models.auto_scan_indentify_result._meta.pk.column)
    exp_fk_column = connection.ops.quote_name(models.auto_scan_exp_result._meta.get_field('EXP_id').column)
    exp_id_column = connection.ops.quote_name(models.EXP._meta.pk.column)
    exp_filter_column = connection.ops.quote_name('title' if field == 'vuln' else models.EXP._meta.get_field('CVE').column)

    return RawSQL(
        f"""
        SELECT identify.{identify_id_column}
        FROM {identify_table} AS identify
        JOIN {exp_result_table} AS exp_result
          ON identify.id = exp_result.identify_result_id
         AND exp_result.task_type IN (1, 2, 3)
        JOIN {exp_table} AS exp
          ON exp_result.{exp_fk_column} = exp.{exp_id_column}
        WHERE exp.{exp_filter_column} = %s
        """,
        [value],
    )


# ── Q 对象构建 → 消费方直接 filter() ──────────────────────

def to_query_structure(condition):
    """将条件树转换为 Django Q 对象。"""
    if 'operator' in condition:
        operator = condition['operator']
        operands = [to_query_structure(operand) for operand in condition['operands']]
        return reduce_operands(operator, operands)

    field = condition['field']
    negated = field.startswith('!')
    if negated:
        field = field[1:]

    value = condition['value']
    if value == "(空)":
        return _build_not_null_query(field, negated=True)
    if value == "*":
        return _build_not_null_query(field, negated=negated)
    if field == "task_id":
        try:
            query = Q(task_relations__task_id=int(value))
        except (ValueError, TypeError):
            query = Q(pk__in=[])
    elif field == "ipc":
        v = value.rstrip('*').rstrip('/').rsplit('/', 1)[0]
        parts = [p for p in v.split('.') if p.isdigit()]
        if len(parts) >= 3:
            prefix = '.'.join(parts[:3])
            rx = '^' + re.escape(prefix) + r'\.\d+$'
            query = Q(ip__iregex=rx)
        else:
            query = Q(ip__icontains=v)
    elif field == "product":
        query = Q(products__contains=[value]) | Q(dir_products__contains=[value])
    elif field in {"html", "body"}:
        if condition.get('deep_search'):
            query = _build_html_deep_search_query(value)
        else:
            query = _build_html_tsvector_query(value)
    elif field == "header":
        query = Q(header__icontains=value)
    elif field in {"vuln", "cve"}:
        query = Q(id__in=build_related_exp_lookup(field, value))
    elif field == "ip":
        if '*' in value:
            regex = '^' + re.escape(value).replace(r'\*', '.*') + '$'
            query = Q(ip__iregex=regex)
        else:
            query = Q(ip=value)
    elif field == "host":
        if '*' in value:
            regex = '^' + re.escape(value).replace(r'\*', '.*') + '$'
            query = Q(host__iregex=regex)
        else:
            query = Q(host=value)
    elif field == "uri_path":
        if '*' in value:
            regex = '^' + re.escape(value).replace(r'\*', '.*') + '$'
            query = Q(uri_path__iregex=regex)
        else:
            query = Q(uri_path=value)
    elif field in {"favicon", "favicon_md5"}:
        query = Q(favicon_md5=value)
    elif field == "cert":
        query = build_cert_query(value)
    elif field == "cert_serial":
        query = Q(cert_serial=value)
    elif field in {"province", "city", "isp", "copyright", "icp"}:
        query = Q(**{f"{field}__icontains": value})
    else:
        if negated:
            query = Q(**{f"{field}__icontains": value})
        else:
            query = Q(**{field: value})

    return ~query if negated else query


def reduce_operands(operator, operands_list):
    if operator == 'AND':
        return reduce(lambda x, y: x & y, operands_list)
    elif operator == 'OR':
        return reduce(lambda x, y: x | y, operands_list)
