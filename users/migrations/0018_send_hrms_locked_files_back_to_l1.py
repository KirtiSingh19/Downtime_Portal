"""Send files HRMS refused as "already processed" back to L1.

Before this rule, such a failure either released only the L2 approval (file
left in L2 Pending) or kept it (file left in L2 File Status). Either way it now
belongs in L1's Files to mark tab, as new failures of this kind are sent there
by users.tasks._record_delivery_failure. A successful upload clears the error,
so no delivered file matches.
"""

from django.db import migrations


def send_back(apps, schema_editor):
    UploadedFile = apps.get_model('users', 'UploadedFile')
    UploadedFile.objects.filter(
        is_split=True,
        rejected_by_l2=False,
        rejected_by_l1=False,
        last_delivery_error__icontains='already processed',
    ).update(
        approved_by_l2=False, approved_by_l2_user=None, approved_at_l2=None,
        l1_status='', l1_status_by=None, l1_status_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_uploadedfile_hrms_notified_key'),
    ]

    operations = [
        migrations.RunPython(send_back, migrations.RunPython.noop),
    ]
