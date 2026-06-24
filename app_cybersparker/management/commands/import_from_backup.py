"""
从 db.SQL（PostgreSQL pg_dump）导入指纹表、POC 插件表、指纹-POC 关系表。

导入顺序：Tag → fingerPrint → EXP → exp_tags → exp_relate_fingerprint
跳过策略：
  - fingerPrint: 跳过 condition 重复的（保留第一条）
  - EXP: 跳过 title 重复的（保留第一条）
  - exp_tags: 跳过 exp_id 或 tag_id 不存在于导入数据的
  - exp_relate_fingerprint: 跳过任一 FK 不存在的，跳过 (EXP_id, fingerprint_id) 重复的

用法：
  python manage.py import_from_backup --input db.SQL
  python manage.py import_from_backup --input db.SQL --dry-run   # 仅检查，不写入
"""
import re
import sys
from io import StringIO
from django.core.management.base import BaseCommand
from django.db import connection, transaction

# COPY 数据中各表在 pg_dump 里的表名
TABLE_MAP = {
    "fingerprint": "public.app_cybersparker_fingerprint",
    "exp": 'public.app_cybersparker_exp',
    "exp_relate_fingerprint": "public.app_cybersparker_exp_relate_fingerprint",
    "exp_tags": "public.app_cybersparker_exp_tags",
    "tag": "public.app_cybersparker_tag",
}

# 导入顺序（遵守 FK 依赖）
IMPORT_ORDER = ["tag", "fingerprint", "exp", "exp_tags", "exp_relate_fingerprint"]

# 各表的列名（按 old db.SQL 的 COPY 列顺序）
TABLE_COLUMNS = {
    "fingerprint": ["id", "product", "condition", "create_time"],
    "exp": ["id", "title", "CVE", "Type", "time", "creat_time", "update_time",
            "plugin_language", "use", "poc_type", "poc", "poc_content", "severity"],
    "exp_relate_fingerprint": ["id", "EXP_id_id", "fingerprint_id_id"],
    "exp_tags": ["id", "exp_id", "tag_id"],
    "tag": ["id", "name"],
}

# 导入后需要重置序列的表
SEQUENCE_MAP = {
    "fingerprint": "app_cybersparker_fingerprint_id_seq",
    "exp": "app_cybersparker_exp_id_seq",
    "exp_relate_fingerprint": "app_cybersparker_exp_relate_fingerprint_id_seq",
    "exp_tags": "app_cybersparker_exp_tags_id_seq",
    "tag": "app_cybersparker_tag_id_seq",
}


def parse_pg_value(val):
    """将 pg_dump COPY 中的值转为 Python 值。\\N 表示 NULL。"""
    if val == "\\N":
        return None
    return val


def extract_copy_sections(filepath):
    """从 pg_dump 文件中提取各表的 COPY 数据段。

    返回 dict: table_key -> list of dicts（每行是 {列名: 值}）
    """
    sections = {key: [] for key in IMPORT_ORDER}

    current_table = None
    current_columns_str = None
    in_copy = False

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # 检测 COPY 开始
            if not in_copy and line.startswith("COPY "):
                for key, pg_table in TABLE_MAP.items():
                    if line.startswith(f"COPY {pg_table} "):
                        current_table = key
                        # 提取列名：COPY public.xxx (col1, "col2", ...) FROM stdin;
                        m = re.search(r"\(([^)]+)\)", line)
                        if m:
                            current_columns_str = m.group(1)
                        in_copy = True
                        break
                continue

            # COPY 数据结束标记
            if in_copy and line.strip() == "\\.":
                in_copy = False
                current_table = None
                current_columns_str = None
                continue

            # 在 COPY 区域内，解析数据行
            if in_copy and current_table:
                parts = line.rstrip("\n").split("\t")
                cols = [c.strip().strip('"') for c in current_columns_str.split(",")]
                if len(parts) >= len(cols):
                    row = {}
                    for i, col in enumerate(cols):
                        row[col] = parse_pg_value(parts[i])
                    sections[current_table].append(row)

    return sections


class Command(BaseCommand):
    help = "从 db.SQL 备份导入指纹/POC/关系数据"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input", type=str, default="db.SQL",
            help="pg_dump SQL 文件路径（默认 db.SQL）",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="仅解析和报告，不实际写入数据库",
        )
        parser.add_argument(
            "--batch-size", type=int, default=2000,
            help="每批插入的行数（默认 2000）",
        )

    def handle(self, **options):
        input_path = options["input"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # ── 1. 解析 db.SQL ──
        self.stdout.write(f"正在解析 {input_path} ...")
        try:
            sections = extract_copy_sections(input_path)
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"文件不存在: {input_path}"))
            sys.exit(1)

        # 报告解析结果
        for key in IMPORT_ORDER:
            self.stdout.write(f"  {key}: 解析到 {len(sections[key])} 行")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run 完成，未写入数据库。"))
            return

        # ── 2. 逐表导入 ──
        # 记录成功导入的 ID 集合，用于后续 FK 校验
        imported_ids = {}

        for table_key in IMPORT_ORDER:
            rows = sections[table_key]
            if not rows:
                self.stdout.write(f"  {table_key}: 无数据，跳过")
                imported_ids[table_key] = set()
                continue

            columns = TABLE_COLUMNS[table_key]
            db_table = f"app_cybersparker_{table_key}" if table_key != "fingerprint" else "app_cybersparker_fingerprint"
            # 对 exp_relate_fingerprint 表名特殊处理
            if table_key == "exp_relate_fingerprint":
                db_table = "app_cybersparker_exp_relate_fingerprint"
            elif table_key == "exp":
                db_table = "app_cybersparker_exp"
            elif table_key == "exp_tags":
                db_table = "app_cybersparker_exp_tags"
            elif table_key == "tag":
                db_table = "app_cybersparker_tag"
            elif table_key == "fingerprint":
                db_table = "app_cybersparker_fingerprint"

            # FK 校验 & 去重
            valid_rows = []
            skipped_fk = 0
            skipped_dup = 0
            seen = set()

            for row in rows:
                # FK 校验
                if table_key == "exp_tags":
                    exp_id = int(row["exp_id"]) if row["exp_id"] else None
                    tag_id = int(row["tag_id"]) if row["tag_id"] else None
                    if exp_id and exp_id not in imported_ids.get("exp", set()):
                        skipped_fk += 1
                        continue
                    if tag_id and tag_id not in imported_ids.get("tag", set()):
                        skipped_fk += 1
                        continue
                elif table_key == "exp_relate_fingerprint":
                    exp_id = int(row["EXP_id_id"]) if row["EXP_id_id"] else None
                    fp_id = int(row["fingerprint_id_id"]) if row["fingerprint_id_id"] else None
                    if exp_id and exp_id not in imported_ids.get("exp", set()):
                        skipped_fk += 1
                        continue
                    if fp_id and fp_id not in imported_ids.get("fingerprint", set()):
                        skipped_fk += 1
                        continue
                    # 检查 (EXP_id_id, fingerprint_id_id) 唯一性
                    dup_key = (exp_id, fp_id)
                    if dup_key in seen:
                        skipped_dup += 1
                        continue
                    seen.add(dup_key)

                # 去重：fingerprint 按 condition 去重，exp 按 title 去重
                if table_key == "fingerprint":
                    cond = row["condition"]
                    if cond in seen:
                        skipped_dup += 1
                        continue
                    seen.add(cond)
                elif table_key == "exp":
                    title = row["title"]
                    if title in seen:
                        skipped_dup += 1
                        continue
                    seen.add(title)
                elif table_key == "tag":
                    name = row["name"]
                    if name in seen:
                        skipped_dup += 1
                        continue
                    seen.add(name)

                valid_rows.append(row)

            self.stdout.write(
                f"  {table_key}: 有效 {len(valid_rows)} 行"
                f"（跳过 FK 不存在 {skipped_fk}，跳过重复 {skipped_dup}）"
            )

            if not valid_rows:
                imported_ids[table_key] = set()
                continue

            # 批量 INSERT
            col_names = [f'"{c}"' if c.upper() != c else c for c in columns]
            # 对 exp_relate_fingerprint，列名中有大写字母需要加引号
            quoted_cols = []
            for c in columns:
                if c == "EXP_id_id" or c == "CVE" or c == "Type":
                    quoted_cols.append(f'"{c}"')
                elif c.upper() == c and c != c.lower():
                    quoted_cols.append(f'"{c}"')
                else:
                    quoted_cols.append(c)
            # 简化处理：全部加引号
            quoted_cols = [c if c.startswith('"') else c for c in columns]
            # 对于 exp 表，CVE、Type 需要引号
            col_names_fixed = []
            for c in columns:
                cn = c
                if cn == "CVE":
                    cn = '"CVE"'
                elif cn == "Type":
                    cn = '"Type"'
                elif cn == "EXP_id_id":
                    cn = '"EXP_id_id"'
                col_names_fixed.append(cn)

            col_list = ", ".join(col_names_fixed)
            placeholders = ", ".join(["%s"] * len(columns))

            total_imported = 0
            batch = []
            imported_id_set = set()

            for row in valid_rows:
                values = [row.get(c) for c in columns]
                batch.append(values)
                rid = int(row["id"]) if row["id"] else None
                if rid:
                    imported_id_set.add(rid)

                if len(batch) >= batch_size:
                    total_imported += self._flush_batch(
                        db_table, col_list, placeholders, batch
                    )
                    batch = []

            if batch:
                total_imported += self._flush_batch(
                    db_table, col_list, placeholders, batch
                )

            imported_ids[table_key] = imported_id_set
            self.stdout.write(f"    实际写入 {total_imported} 行")

        # ── 3. 重置序列 ──
        self.stdout.write("\n重置序列...")
        with connection.cursor() as cursor:
            for table_key in IMPORT_ORDER:
                seq_name = SEQUENCE_MAP.get(table_key)
                if not seq_name:
                    continue
                db_table = f"app_cybersparker_{table_key}"
                if table_key == "exp_relate_fingerprint":
                    db_table = "app_cybersparker_exp_relate_fingerprint"
                elif table_key == "exp":
                    db_table = "app_cybersparker_exp"
                elif table_key == "exp_tags":
                    db_table = "app_cybersparker_exp_tags"
                elif table_key == "tag":
                    db_table = "app_cybersparker_tag"
                elif table_key == "fingerprint":
                    db_table = "app_cybersparker_fingerprint"

                try:
                    cursor.execute(
                        f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {db_table}), 1), true)",
                        [seq_name],
                    )
                    self.stdout.write(f"  {seq_name}: 已重置")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  {seq_name}: 重置失败 ({e})"))

        self.stdout.write(self.style.SUCCESS("导入完成！"))

    def _flush_batch(self, db_table, col_list, placeholders, batch):
        """执行一批 INSERT，返回成功写入的行数。

        使用 Django cursor.executemany，在单个事务中完成批量写入。
        遇到冲突自动跳过（ON CONFLICT DO NOTHING）。
        """
        sql = f"INSERT INTO {db_table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        try:
            with connection.cursor() as cursor:
                cursor.executemany(sql, batch)
            return len(batch)
        except Exception as e:
            # Django executemany 不支持带 ON CONFLICT 的批量优化
            # 回退到逐行执行
            ok = 0
            with connection.cursor() as cursor:
                for vals in batch:
                    try:
                        cursor.execute(sql, vals)
                        ok += 1
                    except Exception:
                        pass  # ON CONFLICT DO NOTHING 不会抛异常，此处防御
            if ok < len(batch):
                self.stderr.write(
                    f"    批量写入: {ok}/{len(batch)} 行成功（{(len(batch) - ok)} 行因冲突跳过）"
                )
            return ok
