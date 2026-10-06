import pytz
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from users.models import DailySummary
import csv
import io

class Command(BaseCommand):
    help = "Send email with list of processes per date from DailySummary for the last 5 days in professional color format with CSV attachment."

    def handle(self, *args, **kwargs):
        # Get today's date in IST
        ist = pytz.timezone("Asia/Kolkata")
        today = datetime.now(ist).date()
        start_date = today - timedelta(days=4)

        # Fetch and filter data
        qs = DailySummary.objects.values_list("date", "process").distinct()
        filtered = []
        for d, process in qs:
            try:
                real_date = datetime.strptime(d, "%d-%m-%Y").date()
                if start_date <= real_date <= today and process != "Unknown":
                    filtered.append((real_date, process))
            except Exception:
                continue

        if not filtered:
            self.stdout.write(self.style.WARNING("No process records found for last 5 days."))
            return

        # Group processes by date
        data_by_date = {}
        for d, process in filtered:
            d_str = d.strftime("%d-%m-%Y")
            data_by_date.setdefault(d_str, []).append(process)

        sorted_dates = sorted(data_by_date.keys(), key=lambda x: datetime.strptime(x, "%d-%m-%Y"))
        max_rows = max(len(set(data_by_date[d])) for d in sorted_dates)

        # Build HTML table
        html_message = f"""
        <html>
        <body>
        <h3>Processes recorded from {start_date.strftime('%d-%m-%Y')} to {today.strftime('%d-%m-%Y')}:</h3>
        <table cellpadding="5" cellspacing="0" style="
            border-collapse: collapse;
            border: 2px solid black;
            width: auto;
            text-align: center;
            font-family: Arial, sans-serif;
        ">
        """

        # Header row: Dark blue background, white text
        html_message += "<tr>"
        for d in sorted_dates:
            html_message += f'<th style="border: 2px solid black; padding: 8px; background-color: #1F4E78; color: white;">{d}</th>'
        html_message += "</tr>"

        # Data rows: alternating very light blue and white
        for i in range(max_rows):
            html_message += "<tr>"
            row_color = "#D9EAF7" if i % 2 == 0 else "#FFFFFF"
            for d in sorted_dates:
                processes = sorted(set(data_by_date[d]))
                value = processes[i] if i < len(processes) else ""
                html_message += f'<td style="border: 2px solid black; padding: 5px; background-color: {row_color}; color: black;">{value}</td>'
            html_message += "</tr>"

        html_message += "</table></body></html>"

        # Prepare CSV attachment
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(sorted_dates)  # header
        for i in range(max_rows):
            row = []
            for d in sorted_dates:
                processes = sorted(set(data_by_date[d]))
                row.append(processes[i] if i < len(processes) else "")
            writer.writerow(row)
        csv_data = output.getvalue()
        output.close()

        # Send email
        subject = f"Process List ({start_date.strftime('%d-%m-%Y')} to {today.strftime('%d-%m-%Y')})"
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = ["digx.automation@iccs.in", "akash.tiwari@iccs.in", 'rahul.kumar@iccs.in', 'mis.support@iccs.in', 'trrishan.pareek@iccs.in', 'osama.1@iccs.in', 'sourabh.kumar@iccs.in', 'mukesh.gupta@iccs.in']

        try:
            email = EmailMessage(subject, html_message, from_email, recipient_list)
            email.content_subtype = "html"
            email.attach("process_list.csv", csv_data, "text/csv")
            email.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"Email sent successfully to {', '.join(recipient_list)}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to send email: {e}"))
