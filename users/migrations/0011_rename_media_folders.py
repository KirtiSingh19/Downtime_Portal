from django.db import migrations

RENAMES = (
    ('enriched', 'L1_approved'),
    ('approved', 'L2_approved'),
)


def _rewrite(name, pairs):
    """Repoint a stored FileField path at the renamed folder.

    Paths written on Windows use a backslash separator, so both forms are matched
    and the result is normalised to the forward slash Django expects in URLs.
    """
    normalised = name.replace('\\', '/')
    for old, new in pairs:
        if normalised.startswith(f'{old}/'):
            return f'{new}/' + normalised[len(old) + 1:]
    return normalised


def forwards(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    for row in UploadedFile.objects.all().iterator():
        updated = _rewrite(row.file.name, RENAMES)
        if updated != row.file.name:
            UploadedFile.objects.filter(pk=row.pk).update(file=updated)


def backwards(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    reverse_pairs = tuple((new, old) for old, new in RENAMES)
    for row in UploadedFile.objects.all().iterator():
        updated = _rewrite(row.file.name, reverse_pairs)
        if updated != row.file.name:
            UploadedFile.objects.filter(pk=row.pk).update(file=updated)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_backfill_l2_and_legacy_routing'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]