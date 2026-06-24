from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0032_change_dirscan_defaults_pool_concurrency_vuln'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_html_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(html) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_html_upper_trgm",
        ),
    ]
