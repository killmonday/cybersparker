# Nuclei 运行时引擎增强（ceye + helper + extractor + cookie）

- 状态：已完成
- 关联 backlog：BL-RUNTIME-002, BL-NUCLEI-001, BL-NUCLEI-002
- 执行模式：Mode D-Chain（持续运行）

## 已交付

1. **BL-RUNTIME-002 (P0)**：CeyeConfig 模型 + migration + ceye_config 视图/模板/路由/导航。引擎 B 注入 `ceye_url` + `interactsh_url`（降级），匹配成功后 poll ceye DNS 记录。
2. **BL-NUCLEI-001 (P0)**：15 个 helper 函数（`url_encode`/`sha256`/`gzip`/`replace`/`trim` 等），SAFE_FUNCTIONS 从 20 个增至 35 个。
3. **BL-NUCLEI-002 (P1)**：JSON extractor（`.key[0].sub` 路径）+ XPath matcher/extractor（lxml）+ cookie 复用（单模板 Session 共享）。
4. **调试页修复**：搜索框 oninput 过滤 + `getTodayDate` 跨 script 块移动 + POC 点击同步服务端兼容 Nuclei 标题格式。

## 验证

- `python manage.py check`：0 issues
- `python manage.py migrate`：全部已应用
- 5 个隔离 probe：全部通过
- 8 项引擎 B 集成测试：全部通过
- 调试页搜索 + 选中 + 代码同步：手动验证通过
