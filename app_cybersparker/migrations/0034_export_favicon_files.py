import base64
import hashlib
import os
import re

from django.db import migrations


FAVICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'static', 'favicons')

_MEDIA_TO_EXT = {
    'image/x-icon': 'ico', 'image/vnd.microsoft.icon': 'ico',
    'image/png': 'png', 'image/svg+xml': 'svg',
    'image/gif': 'gif', 'image/jpeg': 'jpg', 'image/webp': 'webp',
}

_DATA_URI_RE = re.compile(r'^data:([^;]+);base64,(.+)$', re.DOTALL)


def _export_one(favicon_value):
    """Convert base64 data URI → file path. Returns (path, md5) or (value, None)."""
    m = _DATA_URI_RE.match((favicon_value or '').strip())
    if not m:
        return favicon_value, None
    media_type = m.group(1).strip().lower()
    try:
        content_bytes = base64.b64decode(m.group(2))
    except Exception:
        return favicon_value, None
    md5 = hashlib.md5(content_bytes).hexdigest()
    ext = _MEDIA_TO_EXT.get(media_type, 'ico')
    filename = f'{md5}.{ext}'
    filepath = os.path.join(FAVICON_DIR, filename)
    if not os.path.exists(filepath):
        os.makedirs(FAVICON_DIR, exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(content_bytes)
    return f'/static/favicons/{filename}', md5


def export_favicons(apps, schema_editor):
    model = apps.get_model('app_cybersparker', 'auto_scan_indentify_result')
    count = 0
    for row in model.objects.exclude(favicon__isnull=True).exclude(favicon=''):
        new_path, md5 = _export_one(row.favicon)
        if md5 is None:
            continue
        row.favicon = new_path
        if md5 and not row.favicon_md5:
            row.favicon_md5 = md5
        row.save(update_fields=['favicon', 'favicon_md5'])
        count += 1
    print(f'  Exported {count} favicon(s) to {FAVICON_DIR}')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0033_upper_html_gin_index'),
    ]

    operations = [
        migrations.RunPython(export_favicons, reverse_code=noop),
    ]
