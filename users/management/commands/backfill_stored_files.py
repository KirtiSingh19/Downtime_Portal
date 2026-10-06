import os

from django.conf import settings
from django.core.management.base import BaseCommand

from users.models import StoredFile, UploadedFile
from users.views import store_file_content


class Command(BaseCommand):
    help = (
        'Copies files that are still on disk into the database, so they stay '
        'viewable once the disk copy is gone. Normally this happens the first '
        'time someone presses View; this does it for every file at once.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be stored without writing anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Files with nothing stored yet. The ones already stored are left alone:
        # the stored copy is what the preview renders, so rewriting it would
        # change what people see, not just where it is read from.
        pending = UploadedFile.objects.filter(stored__isnull=True)

        stored = skipped = 0
        total_bytes = 0

        for uploaded_file in pending:
            path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file.name)
            if not os.path.exists(path):
                # Nothing to copy: the bytes are gone from disk and were never
                # stored. Reported rather than passed over in silence.
                skipped += 1
                continue

            size = os.path.getsize(path)
            if dry_run:
                stored += 1
                total_bytes += size
                self.stdout.write(f'  would store {uploaded_file.file.name} ({size} bytes)')
                continue

            # The same helper the View page uses, so there is one place that
            # decides how a file gets into the database.
            row = store_file_content(uploaded_file)
            if row is None:
                skipped += 1
                continue

            stored += 1
            total_bytes += row.size
            self.stdout.write(f'  stored {uploaded_file.file.name} ({row.size} bytes)')

        already = StoredFile.objects.count() - (0 if dry_run else stored)
        verb = 'would be stored' if dry_run else 'stored'

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{stored} file(s) {verb}, {total_bytes / 1024:.1f} KB.'
        ))
        if already:
            self.stdout.write(f'{already} file(s) were already stored and were left alone.')
        if skipped:
            self.stdout.write(self.style.WARNING(
                f'{skipped} file(s) skipped: no copy on disk and none stored, '
                'so there are no bytes to keep.'
            ))
        if dry_run:
            self.stdout.write('Dry run - nothing was written.')
