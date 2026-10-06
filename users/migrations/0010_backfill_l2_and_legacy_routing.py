from django.db import migrations


def backfill(apps, schema_editor):
    """Carry existing rows across the L1-only -> L1+L2 workflow change.

    Two independent fixes:

    1. Every enriched file that already exists was produced by the Cluster Head
       split, so it must keep reaching its approver through the CH_ATSID in its
       filename.

    2. Every file already approved by L1 was delivered to HRMS under the old
       one-stage flow. Marking it L2-approved keeps it out of the new L2 queue.
       Without this the entire approval history would appear as pending for L2,
       and approving any of it would SCP a duplicate record to HRMS.
    """
    UploadedFile = apps.get_model('users', 'UploadedFile')
    UploadedFile.objects.filter(is_split=True).update(legacy_ch_routed=True)
    UploadedFile.objects.filter(approved_by_l1=True).update(approved_by_l2=True)


def unbackfill(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    UploadedFile.objects.update(legacy_ch_routed=False, approved_by_l2=False)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_uploadedfile_approved_at_l2_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]