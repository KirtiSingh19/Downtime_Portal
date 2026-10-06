import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = (
        "Create the default superuser if it does not exist. Safe to run on every "
        "container start: an existing account is left exactly as it is."
    )

    def handle(self, *args, **options):
        # The same variables Django's own `createsuperuser --noinput` reads, so
        # the credentials can be changed per deployment without a code change.
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "Admin@12345")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            # Never touched: resetting the password here would undo any change
            # made through the admin site on every restart.
            self.stdout.write(f"Superuser '{username}' already exists; left unchanged.")
            return

        try:
            with transaction.atomic():
                # role='admin' matters: login routing checks role before
                # is_superuser, and the default 'regular' would send this
                # account to the upload page instead of the admin site.
                User.objects.create_superuser(
                    username=username, email=email, password=password, role="admin",
                )
        except IntegrityError:
            # Another process created it between the check and the insert.
            self.stdout.write(f"Superuser '{username}' already exists; left unchanged.")
            return

        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created."))
