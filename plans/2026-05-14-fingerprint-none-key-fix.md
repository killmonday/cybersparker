# fix: fingerprint_indentify 两处运行时错误

## 问题
1. **根因**：`check()` 使用 `sqlite3.connect('db\\exp.db')`（Windows 反斜杠路径），
   Linux 上无法打开数据库文件，抛 `OperationalError` 后返回 `(None, None)`。
2. **连锁反应**：`handle()` 对 `key=None` 做 `'||' in key` 触发 `TypeError`。

## 修复
1. `check()`：将 raw sqlite3 + 硬编码 Windows 路径替换为 Django ORM
   (`models.fingerPrint.objects.filter(id=_id).values_list(...).first()`)，
   使用 Django 配置的跨平台数据库路径，同时移除无用 `import sqlite3`。
2. `handle()`：`name, key = check(_id)` 之后增加 `if key is None: continue` 防御性 guard。

## 风险
低。`check()` 签名和返回值契约不变；同类已在使用 Django ORM。

## 结果
- 修复：2 处修改（check 函数重写 + handle 空值 guard）
- 编译：通过
- 测试：15/15 通过，无回归
- 影响分析：LOW 风险

