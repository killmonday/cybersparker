# 将证书字段索引从 B-tree 替换为 pg_trgm GIN，加速中英文混合模糊搜索

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0069_drop_icp_btree'),
    ]

    operations = [
        # 1. 删除旧的 B-tree 索引（对 icontains 无效）
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_cert_common_name",
            reverse_sql="CREATE INDEX IF NOT EXISTS idx_cert_common_name ON app_cybersparker_auto_scan_indentify_result (cert_common_name)",
        ),
        # 2. 创建 GIN trigram 索引
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_cert_org_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(cert_org) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_cert_org_upper_trgm",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_cert_org_unit_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(cert_org_unit) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_cert_org_unit_upper_trgm",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_cert_common_name_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(cert_common_name) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_cert_common_name_upper_trgm",
        ),
    ]
