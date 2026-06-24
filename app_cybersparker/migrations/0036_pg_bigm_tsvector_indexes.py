from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0035_favicon_varchar_index'),
    ]

    operations = [
        # pg_bigm: Korean/CJK bigram full-text search (must be installed manually first)
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_bigm",
            reverse_sql="DROP EXTENSION IF EXISTS pg_bigm",
        ),
        # Bigram GIN index: accelerates ILIKE for CJK (Chinese) text search
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_html_upper_bigm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(html) gin_bigm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_html_upper_bigm",
        ),
        # tsvector GIN index: tokenized full-text search for ASCII/English
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_html_tsvector ON app_cybersparker_auto_scan_indentify_result USING GIN (to_tsvector('simple', html))",
            reverse_sql="DROP INDEX IF EXISTS idx_html_tsvector",
        ),
        # Trigram GIN index: header field (small, mostly ASCII)
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_header_upper_trgm ON app_cybersparker_auto_scan_indentify_result USING GIN (UPPER(header) gin_trgm_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_header_upper_trgm",
        ),
    ]
