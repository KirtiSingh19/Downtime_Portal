from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from users.models import User, UploadedFile
from users.utils import calculate_pending_stats

class Command(BaseCommand):
    help = 'Sends daily email to L1 users with count of pending files for approval.'

    def handle(self, *args, **kwargs):
        l1_users = User.objects.filter(role='l1')
        for user in l1_users:
            # Files created since Cluster Head routing was removed are pending for
            # every L1 user. Older files count only for the Cluster Head named in
            # their filename.
            pending_count = UploadedFile.objects.filter(
                Q(
                    l1_status='',
                    rejected_by_l1=False,
                    is_valid_format=True,
                    is_split=True,
                )
                & (
                    Q(legacy_ch_routed=False)
                    | Q(legacy_ch_routed=True, file__icontains=user.username)
                )
            ).count()

            if pending_count > 0:
                # Get stats from files
                total_processes, total_empcode, total_records, process_names = calculate_pending_stats(user.username)

                subject = "Daily Pending Files Summary"
                from_email = settings.DEFAULT_FROM_EMAIL
                to_email = [user.email]

                # Fallback plain text message
                plain_message = (
                    f"Dear { user.first_name } { user.last_name },\n\n"
                    f"You have {pending_count} downtime file(s) pending for approval.\n"
                    f"Please login to: http://172.20.122.231:8550/login/\n"
                )

                # HTML message
                html_message = f"""
                <html>
                    <body>
                        <p>Dear {user.first_name} {user.last_name},</p>
                        <p>You have <strong>{pending_count}</strong> downtime file(s) pending for approval.</p>
                        <p>Please <a href="http://172.20.122.231:8550/login/">log in here</a> to review them.</p>

                        <h3>Summary of Pending Files:</h3>
                        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                            <tr style="background-color: #f2f2f2;">
                                <th>Total Processes</th>
                                <th>Process Names</th>
                                <th>Unique EmpCodes</th>
                                <th>Total Records</th>
                            </tr>
                            <tr>
                                <td align="center">{total_processes}</td>
                                <td>{process_names}</td>
                                <td align="center">{total_empcode}</td>
                                <td align="center">{total_records}</td>
                            </tr>
                        </table>
                    </body>
                </html>
                """

                send_mail(
                    subject=subject,
                    message=plain_message,  # fallback for non-HTML clients
                    from_email=from_email,
                    recipient_list=to_email,
                    html_message=html_message
                )
