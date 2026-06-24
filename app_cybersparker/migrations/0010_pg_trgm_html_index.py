# Generated migration for pg_trgm HTML full-text search
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0009_add_process_to_auto_scan_tasks'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm",
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_html_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (html gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_html_trgm",
        ),
    ]
