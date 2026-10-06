import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from users.models import UploadedFile
from users.models import User

class Command(BaseCommand):
    help = 'Sends summary email with Total Raised, Approved, and Pending record counts by CHATS.'

    def handle(self, *args, **kwargs):
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')  # go back to project root
        file_root = os.path.join(base_dir, 'media')

        all_files = UploadedFile.objects.filter(is_valid_format=True, is_split=True)

        summary_data = {}
        SKIP_CHATS = ['ATS0011', 'ATS0022', 'ATS83664']  # Add CHATS codes you want to skip

        def get_user_full_name(username):
            try:
                user = User.objects.get(username=username)
                return f"{user.first_name} {user.last_name}".strip() or "N/A"
            except User.DoesNotExist:
                return "N/A"

        def get_row_count(file_path):
            try:
                if file_path.endswith('.csv'):
                    df = pd.read_csv(file_path)
                elif file_path.endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(file_path)
                else:
                    return 0
                return len(df)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                return 0

        for file_record in all_files:
            file_name = os.path.basename(file_record.file.name)
            full_path = os.path.join(file_root, file_record.file.name.replace('/', os.sep))
            if not os.path.exists(full_path):
                continue

            try:
                chats = file_name.split('_')[-1].split('.')[0]
            except IndexError:
                continue

            if chats in SKIP_CHATS:
                continue  # Skip this CHATS

            row_count = get_row_count(full_path)
            if row_count == 0:
                continue

            if chats not in summary_data:
                summary_data[chats] = {"Total Raised": 0, "Approved": 0, "Pending": 0, "Rejected": 0}

            summary_data[chats]["Total Raised"] += row_count

            if file_record.approved_by_l2:
                summary_data[chats]["Approved"] += row_count
            elif file_record.rejected_by_l2 or file_record.rejected_by_l1:
                summary_data[chats]["Rejected"] += row_count
            else:
                summary_data[chats]["Pending"] += row_count

        if not summary_data:
            self.stdout.write(self.style.WARNING("No valid data found in files."))
            return

        df = pd.DataFrame([
            {
                "CHATS": chats,
                "Name": get_user_full_name(chats),
                "Total Raised": data["Total Raised"],
                "Approved": data["Approved"],
                "Rejected": data["Rejected"],
                "Pending": data["Pending"]
            }
            for chats, data in summary_data.items()
        ])

        df = df.sort_values(by='CHATS')

        # Styled HTML Table
        html_table = df.to_html(index=False, border=0, classes="summary-table")

        # Email Body
        body = f"""
        <html>
          <head>
            <style>
              .summary-table {{
                width: 100%;
                border-collapse: collapse;
                font-family: Arial, sans-serif;
              }}
              .summary-table th, .summary-table td {{
                border: 1px solid #dddddd;
                text-align: center;
                padding: 8px;
              }}
              .summary-table th {{
                background-color: #f2f2f2;
              }}
              .summary-table tr:nth-child(even) {{
                background-color: #f9f9f9;
              }}
            </style>
          </head>
          <body>
            <p>Dear Team,</p>
            <p>Please find below the CHATS-wise record summary report (by number of records inside files):</p>
            {html_table}
          </body>
        </html>
        """

        email = EmailMessage(
            subject="Daily CHATS Record Summary",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=['digx.automation@iccs.in'],  # update as needed 
        )
        email.content_subtype = 'html'
        email.send()

        self.stdout.write(self.style.SUCCESS("Summary email sent successfully."))
