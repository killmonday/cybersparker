# 将 copyright/icp 的 B-tree 索引替换为 pg_trgm GIN 索引，加速中英文模糊搜索

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0067_add_copyright_icp'),
    ]

    operations = [
        # 1. 删除 0067 创建的 B-tree 索引（对 icontains 无效）
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS app_cybersp_copyrig_f02be0_idx",
            reverse_sql="CREATE INDEX IF NOT EXISTS app_cybersp_copyrig_f02be0_idx ON app_cybersparker_auto_scan_indentify_result (copyright)",
        ),
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS app_cybersp_icp_57c247_idx",
            reverse_sql="CREATE INDEX IF NOT EXISTS app_cybersp_icp_57c247_idx ON app_cybersparker_auto_scan_indentify_result (icp)",
        ),
        # 2. 创建 GIN trigram 索引（支持 LIKE '%中英文混合%'）
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_copyright_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(copyright) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_copyright_upper_trgm",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_icp_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(icp) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_icp_upper_trgm",
        ),
    ]
