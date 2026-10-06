"""Carry files decided under the retired L1 approval step onto l1_status.

L2's queue used to be gated on approved_by_l1; it is now gated on l1_status
being set. Without this, every file L1 had already approved but L2 had not yet
actioned would drop out of the L2 queue the moment the new gate went live.

An L1 approval meant "released to L2", which is what Unlock means now, so that
is what those rows are given. Files L1 rejected are left with no status: they
are terminal and must not appear on L2's queue.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    UploadedFile.objects.filter(approved_by_l1=True, l1_status='').update(
        l1_status='unlock',
    )
    # The who/when cannot be set in a single UPDATE from other columns portably,
    # so copy the L1 approver's stamp row by row.
    for row in UploadedFile.objects.filter(
        approved_by_l1=True, l1_status='unlock', l1_status_at__isnull=True
    ).only('id', 'approved_by_id', 'approved_at'):
        UploadedFile.objects.filter(id=row.id).update(
            l1_status_by_id=row.approved_by_id,
            l1_status_at=row.approved_at,
        )


def unbackfill(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    UploadedFile.objects.filter(approved_by_l1=True, l1_status='unlock').update(
        l1_status='', l1_status_by=None, l1_status_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0013_uploadedfile_l1_status_uploadedfile_l1_status_at_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
