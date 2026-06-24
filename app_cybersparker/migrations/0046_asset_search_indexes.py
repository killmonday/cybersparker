# Generated migration — add indexes for asset search performance at scale
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("app_cybersparker", "0045_batch_pause_resume"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_dir_products_gin ON app_cybersparker_auto_scan_indentify_result USING GIN (dir_products)",
            reverse_sql="DROP INDEX IF EXISTS idx_dir_products_gin",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_cert_common_name ON app_cybersparker_auto_scan_indentify_result (cert_common_name)",
            reverse_sql="DROP INDEX IF EXISTS idx_cert_common_name",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_uri_path ON app_cybersparker_auto_scan_indentify_result (uri_path)",
            reverse_sql="DROP INDEX IF EXISTS idx_uri_path",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_title ON app_cybersparker_auto_scan_indentify_result (title)",
            reverse_sql="DROP INDEX IF EXISTS idx_title",
        ),
    ]
