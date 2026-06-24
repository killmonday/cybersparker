# ============================================================
# PostgreSQL 17 + pg_bigm（中文全文检索扩展）
# ============================================================
# pg_bigm 无预编译包，使用本地源码 tarball 编译安装。
# 多阶段构建：第一阶段编译，第二阶段只复制产物。

FROM postgres:17 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    make gcc postgresql-server-dev-17 libicu-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pg_bigm-1.2-20250903.tar.gz /tmp/

RUN cd /tmp \
    && tar xzf pg_bigm-1.2-20250903.tar.gz \
    && cd pg_bigm-1.2-20250903 \
    && USE_PGXS=1 make \
    && USE_PGXS=1 make install \
    && rm -rf /tmp/pg_bigm-1.2-20250903 /tmp/pg_bigm-1.2-20250903.tar.gz

# ---- 最终镜像（Debian 版，含已编译的 pg_bigm）----
FROM postgres:17

# 从 builder 复制编译好的扩展文件
COPY --from=builder /usr/lib/postgresql/17/lib/pg_bigm.so /usr/lib/postgresql/17/lib/
COPY --from=builder /usr/share/postgresql/17/extension/pg_bigm.control /usr/share/postgresql/17/extension/
COPY --from=builder /usr/share/postgresql/17/extension/pg_bigm--*.sql /usr/share/postgresql/17/extension/
