from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from users.models import UploadedFile
import pandas as pd
from users.models import User

class Command(BaseCommand):
    help = 'Sends summary email with Total Raised, Approved, and Pending files by Cluster Head.'

    def handle(self, *args, **kwargs):
        all_files = UploadedFile.objects.filter(is_valid_format=True, is_split=True)

        summary_data = {}
        SKIP_CHATS = ['ATS0011', 'ATS0022', 'ATS83664', 'ATS54511', 'ATS79016', 'ATS78393', 'ATS92522']  # Add CHATS codes you want to skip , 'ATS54511', 'ATS78393'

        def get_user_full_name(username):
            try:
                user = User.objects.get(username=username)
                return f"{user.first_name} {user.last_name}".strip() or "N/A"
            except User.DoesNotExist:
                return "N/A"


        for file_record in all_files:
            filename = file_record.file.name.split('/')[-1]
            if "_" not in filename:
                continue
            try:
                chats = filename.split('_')[-1].replace('.csv', '').replace('.xlsx', '').replace('.xls', '')
            except IndexError:
                continue
            
            if chats in SKIP_CHATS:
                continue  # Skip this CHATS

            if chats not in summary_data:
                summary_data[chats] = {"Total Raised": 0, "Approved": 0, "Pending": 0, "Rejected": 0}

            summary_data[chats]["Total Raised"] += 1

            if file_record.approved_by_l2:
                summary_data[chats]["Approved"] += 1
            elif file_record.rejected_by_l2 or file_record.rejected_by_l1:
                summary_data[chats]["Rejected"] += 1
            else:
                summary_data[chats]["Pending"] += 1

        if not summary_data:
            self.stdout.write(self.style.WARNING("No data to summarize."))
            return

        # Build DataFrame
        df = pd.DataFrame([
            {
                "ATS ID": chats,
                "Cluster Head": get_user_full_name(chats),
                "Total Raised": data["Total Raised"],
                "Approved": data["Approved"],
                "Rejected": data["Rejected"],
                "Pending": data["Pending"]
            }
            for chats, data in summary_data.items()
        ])

        df = df.sort_values(by='ATS ID')

        # Generate HTML table
        html_table = df.to_html(
            index=False,
            escape=False,
            border=0,
            classes="summary-table",
        )

        subject = "Pending Downtime Approval Report"
        # Email body with embedded CSS
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
                color: #333;
            }}
            .summary-table tr:nth-child(even) {{
                background-color: #f9f9f9;
            }}
            </style>
        </head>
        <body>
            <p>Dear Team,</p>
            <p>Please find the pending files, containing downtime records, that need your approval to be sent to HRMS.</p>
            {html_table}
        </body>
        </html>
        """

        # Send email
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=['digx.automation@iccs.in', 'trrishan.pareek@iccs.in', 'ravi.taneja@iccs.in', 'akash.tiwari@iccs.in', 'lucky.kapur@iccs.in',
            'ajay.kalra@iccs.in', 'ram.prasad@iccs.in', 'rohit.singh@iccs.in', 'chandrachooda.bhat@iccs.in',
            'satish.kumar1@iccs.in', '	wasim.saudagar@iccs.in', 'gaurav.kukreja@iccs.in', 'vikram.arora@iccs.in',
            'paras.chordia@iccs.in', 'osama.1@iccs.in','vijay.b@iccs.in','process.coordinator2@iccs.in'],  #  , 'amit.miglani@iccs.in'

        )
        email.content_subtype = 'html'
        email.send()

        self.stdout.write(self.style.SUCCESS("Summary email sent successfully."))
