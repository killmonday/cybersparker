"""
JS 跳转 URL 提取。

策略：
  1) AST 静态分析（esprima）— 解析 <script> 块为语法树，追踪变量/函数定义链
  2) 正则回退 — AST 解析失败或未找到时用正则匹配字面量 + 变量回查
"""

import logging
import re

logger = logging.getLogger(__name__)

# ---- 正则回退 ----

_JS_REDIRECT_LITERAL = [
    re.compile(r"(?:window\.)?location\.href\s*=\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"window\.navigate\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    re.compile(r"window\.location\.replace\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    re.compile(r"self\.location\s*=\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"top\.location\s*=\s*['\"]([^'\"]+)['\"]"),
]

_RE_VAR_DIRECT = re.compile(
    r"(?:window\.)?(?:location|self\.location|top\.location)\.href\s*=\s*([a-zA-Z_$][\w$]*)",
    re.IGNORECASE,
)


def _regex_fallback(text):
    """正则匹配：字面量 → 变量回查。返回 URL 或 None。"""
    for pattern in _JS_REDIRECT_LITERAL:
        m = pattern.search(text)
        if m:
            return m.group(1)

    for m in _RE_VAR_DIRECT.finditer(text):
        var_name = re.escape(m.group(1))
        dm = re.search(
            r'(?:var\s+)?' + var_name + r'\s*=\s*[\'"]([^\'"]*?)[\'"]',
            text,
            re.IGNORECASE,
        )
        if dm:
            return dm.group(1)

    return None


# ---- AST 静态分析 ----

def _extract_chain(left_node):
    """从 MemberExpression 提取属性链: window.location.href → ['window','location','href']"""
    chain = []
    cur = left_node
    while isinstance(cur, dict) and cur.get('type') == 'MemberExpression':
        p = cur.get('property', {})
        chain.insert(0, p.get('name', '') if isinstance(p, dict) else '')
        cur = cur['object']
    if isinstance(cur, dict) and cur.get('type') == 'Identifier':
        chain.insert(0, cur['name'])
    return chain


def _is_redirect_assign(node):
    """识别跳转操作。返回 (True, right_node) 或 (False, None)。

    覆盖：
      location.href = X             self/top/window/document.location.href = X
      self/top/window.location = X
      location.replace(X) / location.assign(X) / location.href(X)
    """
    if not isinstance(node, dict):
        return False, None

    # 方法调用: location.replace(url)
    if node.get('type') == 'CallExpression':
        callee = node.get('callee', {})
        if callee.get('type') == 'MemberExpression':
            chain = _extract_chain(callee)
            if (len(chain) >= 2 and chain[-2] == 'location' and
                    chain[-1] in ('replace', 'assign', 'href')):
                args = node.get('arguments', [])
                return (True, args[0]) if args else (False, None)
        return False, None

    # 赋值: xxx = url
    if node.get('type') != 'AssignmentExpression' or node.get('operator') != '=':
        return False, None
    left = node.get('left', {})
    if left.get('type') != 'MemberExpression':
        return False, None

    chain = _extract_chain(left)
    if not chain:
        return False, None

    # .href = X
    if chain[-1] == 'href' and len(chain) >= 2 and chain[-2] == 'location':
        if chain[0] in ('location', 'self', 'top', 'window', 'document'):
            return True, node.get('right', {})
        if len(chain) == 3 and chain[0] in ('self', 'top', 'window', 'document'):
            return True, node.get('right', {})

    # .location = X
    if (len(chain) == 2 and chain[-1] == 'location' and
            chain[0] in ('self', 'top', 'window')):
        return True, node.get('right', {})

    return False, None


def _resolve_ast_value(node, scope):
    """从 AST 节点解析字符串值。

    支持：Literal, TemplateLiteral(静态前缀), Identifier(scope回查),
          BinaryExpression(静态拼接), CallExpression(函数返回值)
    """
    if not isinstance(node, dict):
        return None
    t = node.get('type')

    if t == 'Literal':
        v = node.get('value')
        return v if isinstance(v, str) else None

    if t == 'TemplateLiteral':
        quasis = node.get('quasis', [])
        if quasis:
            return (quasis[0].get('value', {}).get('raw') or
                    quasis[0].get('value', {}).get('cooked')) or None

    if t == 'Identifier':
        return scope.get(node.get('name'))

    if t == 'BinaryExpression' and node.get('operator') == '+':
        left = _resolve_ast_value(node.get('left', {}), scope)
        right = _resolve_ast_value(node.get('right', {}), scope)
        if left is not None and right is not None:
            return str(left) + str(right)
        if left is not None:
            return left
        if right is not None:
            return right

    if t == 'CallExpression':
        callee = node.get('callee', {})
        if callee.get('type') == 'Identifier':
            return scope.get('__fn__' + callee.get('name', ''))

    return None


_FUNCTION_TYPES = frozenset(
    {"FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"}
)


def _walk_ast(node, scope, results, in_function=False):
    """递归遍历 AST：收集 var/function 定义，提取跳转 URL。

    函数体内的 location.href= 通常是 onclick 等事件回调，
    不是页面级自动跳转，跳过不提取。
    """
    if not isinstance(node, dict):
        return

    t = node.get("type")

    # 变量声明
    if t == "VariableDeclaration":
        for decl in node.get("declarations", []):
            did = decl.get("id", {})
            init = decl.get("init")
            if did.get("type") == "Identifier" and init:
                val = _resolve_ast_value(init, scope)
                if val:
                    scope[did["name"]] = val

    # 函数声明 → 提取 return 字面量，body 内标记 in_function
    if t == "FunctionDeclaration":
        fid = node.get("id", {})
        body = node.get("body", {})
        if fid.get("type") == "Identifier" and body.get("type") == "BlockStatement":
            for stmt in body.get("body", []):
                if stmt.get("type") == "ReturnStatement":
                    arg = stmt.get("argument")
                    if arg:
                        val = _resolve_ast_value(arg, scope)
                        if val:
                            scope["__fn__" + fid["name"]] = val
                            break
            for stmt in body.get("body", []):
                if isinstance(stmt, dict):
                    _walk_ast(stmt, scope, results, in_function=True)
        return

    # 函数表达式/箭头函数 → body 内标记 in_function
    if t in _FUNCTION_TYPES:
        body = node.get("body", {})
        if body.get("type") == "BlockStatement":
            for stmt in body.get("body", []):
                if isinstance(stmt, dict):
                    _walk_ast(stmt, scope, results, in_function=True)
        elif isinstance(body, dict):
            # 箭头函数简写: () => expression (无花括号)
            _walk_ast(body, scope, results, in_function=True)
        return

    # 跳转赋值？（函数体内跳过 — 通常是事件回调，不是自动跳转）
    if not in_function:
        is_redirect, right_node = _is_redirect_assign(node)
        if is_redirect:
            val = _resolve_ast_value(right_node, scope)
            if val and isinstance(val, str) and len(val) >= 1:
                if not val.startswith("javascript:") and not val.startswith("#"):
                    results.append(val)

    # 递归子节点
    for key, child in node.items():
        if key in (
            "type",
            "operator",
            "value",
            "name",
            "kind",
            "raw",
            "pattern",
            "computed",
            "quasis",
        ):
            continue
        if isinstance(child, dict):
            _walk_ast(child, scope, results, in_function)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    _walk_ast(item, scope, results, in_function)


def _extract_script_blocks(html_body):
    """提取内联 <script> 块（跳过外部引用）。"""
    pattern = re.compile(
        r'<script[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
    blocks = []
    for m in pattern.finditer(html_body):
        tag = m.group(0)
        if ' src=' in tag or " src=" in tag:
            continue
        code = m.group(1).strip()
        if code:
            blocks.append(code)
    return blocks


def _ast_find_redirect_url(html_body):
    """AST 分析所有内联 <script> 块，返回第一个跳转 URL 或 None。"""
    try:
        import esprima
    except ImportError:
        logger.debug("esprima not installed, skipping AST redirect detection")
        return None

    blocks = _extract_script_blocks(html_body)
    if not blocks:
        return None

    for code in blocks:
        scope = {}
        try:
            ast = esprima.parseScript(code, {'tolerant': True})
            d = ast.toDict()
            for node in d.get('body', []):
                results = []
                _walk_ast(node, scope, results)
                if results:
                    return results[0]
        except Exception:
            continue

    return None


# ---- 统一入口 ----

def get_js_redirect_url(html_body):
    """从 HTML body 提取 JS 跳转 URL。

    先 AST 静态分析，失败则回退正则匹配。
    AST 成功解析但未找到跳转时，不退回正则（避免函数体内的事件回调被误判）。
    返回 URL 字符串或 None。
    """
    if not html_body:
        return None

    text = html_body.strip().replace('\xa0', ' ').replace('&nbsp;', ' ')

    ast_available = False
    try:
        import esprima  # noqa: F811
        ast_available = True
    except ImportError:
        pass

    if ast_available:
        try:
            result = _ast_find_redirect_url(text)
            if result:
                return result
            # AST 成功解析但未找到跳转 → 不退回正则
            return None
        except Exception:
            logger.debug(
                "AST redirect detection failed, falling back to regex",
                exc_info=True,
            )

    # 正则回退（AST 不可用或解析失败）
    try:
        return _regex_fallback(text)
    except Exception:
        logger.debug("Regex redirect fallback also failed", exc_info=True)
        return None
