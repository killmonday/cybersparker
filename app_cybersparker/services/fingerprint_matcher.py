"""指纹规则匹配引擎 — 被调试页和自动扫描任务共用。

只返回 bool，不跟踪 matched_text / regular_error（这两个是调试页特有需求）。
"""
import re

rtitle = re.compile(r'title="(.*)"')
rheader = re.compile(r'header="(.*)"')
rbody = re.compile(r'body="(.*)"')
rbracket = re.compile(r'\((.*)\)')
rtitle_not = re.compile(r'title!="(.*)"')
rheader_not = re.compile(r'header!="(.*)"')
rbody_not = re.compile(r'body!="(.*)"')
regular_rtitle = re.compile(r'title~="(.*)"')
regular_rheader = re.compile(r'header~="(.*)"')
regular_rbody = re.compile(r'body~="(.*)"')


def context_rule_values(context=None):
    context = context or {}
    cert_values = [
        context.get("cert_org"),
        context.get("cert_org_unit"),
        context.get("cert_common_name"),
    ]
    cert_values = [v for v in cert_values if v]
    if not cert_values and context.get("cert"):
        cert_values = [context.get("cert")]
    favicon_values = [v for v in [context.get("favicon"), context.get("favicon_md5"), context.get("favicon_mmh3")] if v]
    favicon_md5_values = [v for v in [context.get("favicon_md5"), context.get("favicon"), context.get("favicon_mmh3")] if v]
    favicon_mmh3_values = [v for v in [context.get("favicon_mmh3")] if v]
    return {
        "cert_common_name": [v for v in [context.get("cert_common_name")] if v],
        "cert_org_unit": [v for v in [context.get("cert_org_unit")] if v],
        "cert_serial": [v for v in [context.get("cert_serial")] if v],
        "favicon_md5": favicon_md5_values,
        "favicon_mmh3": favicon_mmh3_values,
        "cert_org": [v for v in [context.get("cert_org")] if v],
        "favicon": favicon_values,
        "cert": cert_values,
        "uri_path": [v for v in [context.get("uri_path")] if v],
    }


def match_context_rule(key, context=None):
    """context 字段匹配（cert/favicon/uri_path），以扫描任务版本为准"""
    values_by_field = context_rule_values(context)
    key_text = str(key)
    for field, values in values_by_field.items():
        if not values:
            continue
        if f'{field}~="' in key_text:
            pattern = re.findall(re.compile(rf'{re.escape(field)}~="(.*)"'), key_text)[0]
            try:
                regex_pattern = re.compile(pattern)
            except re.error:
                return False
            return any(regex_pattern.search(str(v)) for v in values)
        if f'{field}!="' in key_text:
            expected = str(re.findall(re.compile(rf'{re.escape(field)}!="(.*)"'), key_text)[0]).lower()
            return all(expected not in str(v).lower() for v in values)
        if f'{field}="' in key_text:
            expected = str(re.findall(re.compile(rf'{re.escape(field)}="(.*)"'), key_text)[0]).lower()
            return any(expected in str(v).lower() for v in values)
    return None


def _regulations_mate(model, key, search_data):
    try:
        regex_pattern = re.compile(str(re.findall(model, key)[0]))
        return bool(regex_pattern.search(search_data))
    except re.error:
        return False


def check_rule(key, header, body, title, context=None):
    """单条规则匹配（不含布尔表达式），返回 bool"""
    try:
        ctx_match = match_context_rule(key, context=context)
        if ctx_match is not None:
            return ctx_match
        if 'title~="' in str(key):
            return _regulations_mate(regular_rtitle, key, title)
        elif 'title!="' in str(key):
            return str(re.findall(rtitle_not, key)[0]).lower() not in str(title).lower()
        elif 'body~="' in str(key):
            return _regulations_mate(regular_rbody, key, body)
        elif 'body!="' in str(key):
            return re.findall(rbody_not, key)[0] not in str(body)
        elif 'header~="' in str(key):
            return _regulations_mate(regular_rheader, key, str(header))
        elif 'header!="' in str(key):
            return re.findall(rheader_not, key)[0] not in str(header)
        elif 'title="' in str(key):
            return str(re.findall(rtitle, key)[0]).lower() in str(title).lower()
        elif 'body="' in str(key):
            return re.findall(rbody, key)[0] in str(body)
        else:
            return re.findall(rheader, key)[0] in str(header)
    except Exception:
        return False


def match_condition(condition, header, body, title, context=None, rule_fn=None):
    """解析指纹条件的布尔表达式（||, &&, 括号），rule_fn 默认使用 check_rule"""
    if rule_fn is None:
        rule_fn = check_rule

    if '||' in condition and '&&' not in condition and '(' not in condition:
        for rule in condition.split('||'):
            if rule_fn(rule, header, body, title, context=context):
                return True

    elif '||' not in condition and '&&' not in condition and '(' not in condition:
        if rule_fn(condition, header, body, title, context=context):
            return True

    elif '&&' in condition and '||' not in condition and '(' not in condition:
        rules = condition.split('&&')
        num = 0
        for rule in rules:
            if rule_fn(rule, header, body, title, context=context):
                num += 1
        if num == len(rules):
            return True

    else:
        if re.findall(rbracket, condition):
            if '&&' in re.findall(rbracket, condition)[0]:
                for rule in condition.split('||'):
                    if '&&' in rule:
                        rules = rule.split('&&')
                        num = 0
                        for _rule in rules:
                            if rule_fn(_rule, header, body, title, context=context):
                                num += 1
                        if num == len(rules):
                            return True
                    else:
                        if rule_fn(rule, header, body, title, context=context):
                            return True
            else:
                rules = condition.split('&&')
                num = 0
                for rule in rules:
                    if '||' in rule:
                        for _rule in rule.split('||'):
                            if rule_fn(_rule, header, body, title, context=context):
                                num += 1
                                break
                    else:
                        if rule_fn(rule, header, body, title, context=context):
                            num += 1
                if num == len(rules):
                    return True
        else:
            return False
