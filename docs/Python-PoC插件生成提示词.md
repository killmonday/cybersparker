# Python PoC 插件生成提示词

根据漏洞描述，生成符合以下规范的 Python 漏洞验证脚本，并输出创建插件所需的必要参数。

---

## 脚本格式规范

### 运行环境

- Python 3
- 尽量使用标准库，非必要禁止引入其他第三方包。
- 引入了第三方包时，在脚本开头用注释写上需要安装的依赖，必须写为：“# pip install lib1 lib2” 这种格式
- 一般情况下不需要获取 task_args 参数，除非用户已经告知其具体用途 
- 对于需要发送http/https请求，必须使用 `requests`库，除非用户在后文的自定义提示词里说明了需要更换

### 函数签名

脚本需导出以下函数（`_verify` 必须实现，其余按漏洞类型选做）：

```python
def _verify(target):
    """漏洞验证。target 是 dict: {"target": "http://192.168.1.1:8080", "task_args": {...}}"""
    url = target["target"]                           # 入口第一行：取出 URL 字符串
    # 漏洞存在 → return {'target': url, 'result': '证据描述'}
    # 漏洞不存在 → 不返回 或 return None

def _cmd_exc(target, cmd):
    """命令执行。target 是 dict，cmd 是用户输入的命令"""
    url = target["target"]
    return {'target': url, 'result': '执行结果'}

def _code_exc(target, cmd):
    """代码执行/SQL注入。target 是 dict，cmd 是用户输入的代码/SQL语句"""
    url = target["target"]
    return {'target': url, 'result': '执行结果'}

def _file_read(target, path):
    """文件读取。target 是 dict，path 是用户输入的文件路径"""
    url = target["target"]
    return {'target': url, 'result': '文件内容'}

```

### target 参数说明

`target` 是**字典**，由运行时自动传入，包含以下键：

| 键 | 类型 | 说明 |
|----|------|------|
| `"target"` | str | 目标 URL，如 `"http://192.168.1.1:8080"`。**入口第一行必须取出：`url = target["target"]`** |
| `"task_args"` | dict | 任务的自定义参数，用户在任务配置中填写。可通过 `target.get("task_args", {})` 读取。例如用户配置了 `{"callback": "http://x.com"}`，插件内可取 `target["task_args"]["callback"]`。为空时值为 `{}` |

### 关键规则

1. `target` 是**字典**，**入口第一行必须写 `url = target["target"]`** 取出 URL 字符串。后续所有代码用 `url` 变量，**不要直接用 `target` 做字符串拼接**（`target.rstrip()` 会报错）。
2. 内部 helper 函数保持**字符串参数**，只传 `url`，不传 `target` 字典。
3. 返回值是 **dict**，必须包含 `target`（**URL 字符串**，即变量 `url`，不是 `target` 字典）和 `result`（结果描述）。**返回 `{'target': url, ...}` 而非 `{'target': target, ...}`**。
4. 所有 HTTP 请求必须加 `verify=False`、`timeout=10`。
5. 不要写 `proxies={}`，默认写一个 `if __name__ == "__main__"` 并硬编码调用_verify（写为：`print(_verify({'target':'http://example.com'}))` 仅供手动调试，实际运行时不会走此分支）。
6. 可以用 `requests.session()` 保持 cookie，必须用 `try/except`包裹执行逻辑部分，出错时调用固定调用 `raise RuntimeError(traceback.format_exc())`。
7. `result` 要尽可能带上具体证据（响应关键内容等），不要只写 "success"。

### 完整示例

```python
import requests
import traceback

def _verify(target):
    url = target["target"]
    full_url = f"{url}/api/config"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    task_args = target.get("task_args", {}) # task_args：用户可配置任务的自定义参数

    try:
        resp = requests.get(full_url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200 and 'password' in resp.text.lower():
            return {'target': url, 'result': f'配置信息泄露：{resp.text[:500]}'}
    except:
        raise RuntimeError(traceback.format_exc())

def _cmd_exc(target, cmd):
    url = target["target"]
    full_url = f"{url}/ping"
    data = {'host': f'127.0.0.1; {cmd}'}

    try:
        resp = requests.post(full_url, data=data, timeout=10, verify=False)
        return {'target': url, 'result': resp.text}
    except:
        raise RuntimeError(traceback.format_exc())

if __name__ == "__main__":
    print(_verify({'target':'http://example.com'}))
```

---

## 必须输出的参数

生成脚本后，同时按以下格式输出参数。程序会解析这些参数来创建插件。

```yaml
# 以下字段由你（AI）提供：
title: "[CVE-xxxx-xxxx]厂商-产品-漏洞类型"   # 必填，插件名称，≤128字符
CVE: "CVE-2024-1234"                         # 可选，没有则留空
Type: 1                                      # 必填，漏洞类型编号（见下表）
severity: "high"                             # 必填，危害等级
tags: "rce, cve, unauth"                     # 可选，标签列表，逗号分隔
extentions: "1,2"                            # 必填，实现了哪些方法（见下表）
ctime: "2024/03/15"                          # 可选，漏洞公开日期，格式 YYYY/MM/DD
```

### Type（漏洞类型）

| 值 | 含义 |
|----|------|
| 1 | 命令执行 |
| 2 | 代码执行 |
| 3 | SQL注入 |
| 4 | 信息泄露 |
| 5 | 文件上传 |
| 6 | 文件读取 |
| 7 | 目录遍历 |
| 8 | 跨站请求伪造 |
| 9 | 身份绕过 |
| 10 | 弱口令 |
| 11 | 路径泄露 |
| 12 | 其他 |

### severity（危害等级）

`critical`（严重）/ `high`（高危）/ `medium`（中危）/ `low`（低危）/ `info`（信息）

### extentions（支持方法）

| 值 | 含义 | 对应函数 |
|----|------|---------|
| 1 | Verify（验证） | `_verify` |
| 2 | Command Execute（命令执行） | `_cmd_exc` |
| 3 | Code Execute（代码执行） | `_code_exc` |
| 4 | File Reading（文件读取） | `_file_read` |
| 5 | Attack（攻击利用） | `_attack` / `_attact` |

至少包含 `1`。多个值用逗号分隔，如实现了 `_verify` + `_cmd_exc` 则填 `"1,2"`。

> 以下字段由程序自动设置，你不需要提供：`plugin_language`（固定为 1）、`poc_content`（取你生成的脚本内容）。
