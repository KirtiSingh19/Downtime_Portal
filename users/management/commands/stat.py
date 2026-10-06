import pytz
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.conf import settings
from users.models import DailySummary
import csv
import io

class Command(BaseCommand):
    help = "Send email with process presence (Yes/No) per date for day-10 to day-3 with CSV attachment."

    def handle(self, *args, **kwargs):
        # Get today's date in IST
        ist = pytz.timezone("Asia/Kolkata")
        today = datetime.now(ist).date()
        start_date = today - timedelta(days=10)  # day-10
        end_date = today - timedelta(days=2)     # day-3

        # Fetch and filter data
        qs = DailySummary.objects.values_list("date", "process").distinct()
        filtered = []
        for d, process in qs:
            try:
                real_date = datetime.strptime(d, "%d-%m-%Y").date()
                if start_date <= real_date <= end_date and process != "Unknown":
                    filtered.append((real_date, process))
            except Exception:
                continue

        if not filtered:
            self.stdout.write(self.style.WARNING(f"No process records found from {start_date} to {end_date}."))
            return

        # Group data: {date: set(processes)}
        data_by_date = {}
        all_processes = set()
        for d, process in filtered:
            d_str = d.strftime("%d-%m-%Y")
            data_by_date.setdefault(d_str, set()).add(process)
            all_processes.add(process)

        sorted_dates = sorted(data_by_date.keys(), key=lambda x: datetime.strptime(x, "%d-%m-%Y"))
        sorted_processes = sorted(all_processes)

        # Build HTML table
        html_message = f"""
        <html>
        <body>
        <h3>Process availability from {start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}:</h3>
        <table cellpadding="5" cellspacing="0" style="
            border-collapse: collapse;
            border: 2px solid black;
            width: auto;
            text-align: center;
            font-family: Arial, sans-serif;
        ">
        """

        # Header row
        html_message += "<tr>"
        html_message += '<th style="border: 2px solid black; padding: 8px; background-color: #1F4E78; color: white;">Process</th>'
        for d in sorted_dates:
            html_message += f'<th style="border: 2px solid black; padding: 8px; background-color: #1F4E78; color: white;">{d}</th>'
        html_message += "</tr>"

        # Rows per process
        for i, process in enumerate(sorted_processes):
            row_color = "#D9EAF7" if i % 2 == 0 else "#FFFFFF"
            html_message += f'<tr><td style="border: 2px solid black; padding: 5px; background-color: {row_color}; color: black;">{process}</td>'
            for d in sorted_dates:
                value = "Yes" if process in data_by_date.get(d, set()) else "No"
                html_message += f'<td style="border: 2px solid black; padding: 5px; background-color: {row_color}; color: black;">{value}</td>'
            html_message += "</tr>"

        html_message += "</table></body></html>"

        # Prepare CSV attachment
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Process"] + sorted_dates)  # header
        for process in sorted_processes:
            row = [process]
            for d in sorted_dates:
                row.append("Yes" if process in data_by_date.get(d, set()) else "No")
            writer.writerow(row)
        csv_data = output.getvalue()
        output.close()

        # Send email
        subject = f"Process Availability ({start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')})"
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [
            "digx.automation@iccs.in", "akash.tiwari@iccs.in", 'rahul.kumar@iccs.in',
            'mis.support@iccs.in', 'trrishan.pareek@iccs.in', 'osama.1@iccs.in',
            'sourabh.kumar@iccs.in', 'mukesh.gupta@iccs.in'
        ]

        try:
            email = EmailMessage(subject, html_message, from_email, recipient_list)
            email.content_subtype = "html"
            email.attach("process_availability.csv", csv_data, "text/csv")
            email.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"Email sent successfully to {', '.join(recipient_list)}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to send email: {e}"))


# import pytz
# from datetime import datetime, timedelta
# from django.core.management.base import BaseCommand
# from django.core.mail import EmailMessage
# from django.conf import settings
# from users.models import DailySummary
# import csv
# import io

# class Command(BaseCommand):
#     help = "Send email with process presence (Yes/No) per date for the last 7 days with CSV attachment."

#     def handle(self, *args, **kwargs):
#         # Get today's date in IST
#         ist = pytz.timezone("Asia/Kolkata")
#         today = datetime.now(ist).date()
#         start_date = today - timedelta(days=7)

#         # Fetch and filter data
#         qs = DailySummary.objects.values_list("date", "process").distinct()
#         filtered = []
#         for d, process in qs:
#             try:
#                 real_date = datetime.strptime(d, "%d-%m-%Y").date()
#                 if start_date <= real_date <= today and process != "Unknown":
#                     filtered.append((real_date, process))
#             except Exception:
#                 continue

#         if not filtered:
#             self.stdout.write(self.style.WARNING("No process records found for last 7 days."))
#             return

#         # Group data: {date: set(processes)}
#         data_by_date = {}
#         all_processes = set()
#         for d, process in filtered:
#             d_str = d.strftime("%d-%m-%Y")
#             data_by_date.setdefault(d_str, set()).add(process)
#             all_processes.add(process)

#         sorted_dates = sorted(data_by_date.keys(), key=lambda x: datetime.strptime(x, "%d-%m-%Y"))
#         sorted_processes = sorted(all_processes)

#         # Build HTML table
#         html_message = f"""
#         <html>
#         <body>
#         <h3>Process availability from {start_date.strftime('%d-%m-%Y')} to {today.strftime('%d-%m-%Y')}:</h3>
#         <table cellpadding="5" cellspacing="0" style="
#             border-collapse: collapse;
#             border: 2px solid black;
#             width: auto;
#             text-align: center;
#             font-family: Arial, sans-serif;
#         ">
#         """

#         # Header row
#         html_message += "<tr>"
#         html_message += '<th style="border: 2px solid black; padding: 8px; background-color: #1F4E78; color: white;">Process</th>'
#         for d in sorted_dates:
#             html_message += f'<th style="border: 2px solid black; padding: 8px; background-color: #1F4E78; color: white;">{d}</th>'
#         html_message += "</tr>"

#         # Rows per process
#         for i, process in enumerate(sorted_processes):
#             row_color = "#D9EAF7" if i % 2 == 0 else "#FFFFFF"
#             html_message += f'<tr><td style="border: 2px solid black; padding: 5px; background-color: {row_color}; color: black;">{process}</td>'
#             for d in sorted_dates:
#                 value = "Yes" if process in data_by_date.get(d, set()) else "No"
#                 html_message += f'<td style="border: 2px solid black; padding: 5px; background-color: {row_color}; color: black;">{value}</td>'
#             html_message += "</tr>"

#         html_message += "</table></body></html>"

#         # Prepare CSV attachment
#         output = io.StringIO()
#         writer = csv.writer(output)
#         writer.writerow(["Process"] + sorted_dates)  # header
#         for process in sorted_processes:
#             row = [process]
#             for d in sorted_dates:
#                 row.append("Yes" if process in data_by_date.get(d, set()) else "No")
#             writer.writerow(row)
#         csv_data = output.getvalue()
#         output.close()

#         # Send email
#         subject = f"Process Availability ({start_date.strftime('%d-%m-%Y')} to {today.strftime('%d-%m-%Y')})"
#         from_email = settings.DEFAULT_FROM_EMAIL
#         recipient_list = [
#             "ishita.jain@iccs.in", "akash.tiwari@iccs.in", 'rahul.kumar@iccs.in',
#             'mis.support@iccs.in', 'trrishan.pareek@iccs.in', 'osama.1@iccs.in',
#             'sourabh.kumar@iccs.in', 'mukesh.gupta@iccs.in'
#         ]

#         try:
#             email = EmailMessage(subject, html_message, from_email, recipient_list)
#             email.content_subtype = "html"
#             email.attach("process_availability.csv", csv_data, "text/csv")
#             email.send(fail_silently=False)
#             self.stdout.write(self.style.SUCCESS(f"Email sent successfully to {', '.join(recipient_list)}"))
#         except Exception as e:
#             self.stdout.write(self.style.ERROR(f"Failed to send email: {e}"))
