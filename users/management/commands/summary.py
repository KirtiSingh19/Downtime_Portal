import os
import pandas as pd
import pytz
from django.core.management.base import BaseCommand
from users.models import UploadedFile, DailySummary
from datetime import datetime, timedelta

class Command(BaseCommand):
    help = "Updates DailySummary table with unique EmpCode counts (approved/pending) per process and date (optimized)."

    def handle(self, *args, **kwargs):
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
        file_root = os.path.join(base_dir, 'media')

        # Load EmpCode → Process mapping
        process_map_path = os.path.join(file_root, "process_ch", "ats_process_ch.xlsx")
        try:
            process_map_df = pd.read_excel(process_map_path)
            emp_process_map = dict(zip(process_map_df['EmpCode'], process_map_df['Process']))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading ats_process_ch.xlsx: {e}"))
            return

        ist = pytz.timezone("Asia/Kolkata")
        # cutoff_date = pd.to_datetime("2025-07-01")
        #  rolling cutoff (35 days back from today)
        cutoff_date = datetime.now() - timedelta(days=35)
        cutoff_date = pd.to_datetime(cutoff_date.strftime("%Y-%m-%d"))

        all_files = UploadedFile.objects.filter(is_valid_format=True, is_split=True)

        all_summary_objects = []  # collect all updates here

        for file_record in all_files:
            file_path = os.path.join(file_root, file_record.file.name.replace('/', os.sep))
            if not os.path.exists(file_path):
                continue

            try:
                if file_path.endswith('.csv'):
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipping {file_path}, error: {e}"))
                continue

            if "EmpCode" not in df.columns or "Date" not in df.columns:
                self.stdout.write(self.style.WARNING(f"Skipping {file_path}, missing EmpCode/Date columns"))
                continue

            # Parse with correct format (mm-dd-yyyy)
            df["Date"] = pd.to_datetime(df["Date"], format="%m-%d-%Y", errors="coerce")

            # Drop invalid and filter July onwards
            df = df.dropna(subset=["Date"])
            df = df[df["Date"] >= cutoff_date]

            if df.empty:
                continue

            # Convert to IST (if UTC-based, else remove)
            df["Date"] = df["Date"].dt.tz_localize("UTC").dt.tz_convert(ist)

            # Map processes vectorized
            df["Process"] = df["EmpCode"].map(emp_process_map).fillna("Unknown")

            # Status flags
            if file_record.approved_by_l2:
                df["Approved"] = 1
                df["Pending"] = 0
            elif not (file_record.rejected_by_l2 or file_record.rejected_by_l1):  # pending
                df["Approved"] = 0
                df["Pending"] = 1
            else:  # rejected → skip
                continue

            # Deduplicate (Date + EmpCode)
            df = df.drop_duplicates(subset=["Date", "EmpCode"])

            # Aggregate by Date + Process
            summary_df = df.groupby(["Date", "Process"]).agg(
                approved=("Approved", "sum"),
                pending=("Pending", "sum")
            ).reset_index()

            # Convert Date to string (dd-mm-yyyy) for saving
            summary_df["Date"] = summary_df["Date"].dt.strftime("%d-%m-%Y")

            # Convert to Django objects
            for _, row in summary_df.iterrows():
                all_summary_objects.append(
                    DailySummary(
                        date=row["Date"],
                        process=row["Process"],
                        approved=row["approved"],
                        pending=row["pending"],
                    )
                )

        # Bulk insert/update in one go
        if all_summary_objects:
            DailySummary.objects.bulk_create(
                all_summary_objects,
                update_conflicts=True,
                update_fields=["approved", "pending"],
                unique_fields=["date", "process"]
            )

        self.stdout.write(self.style.SUCCESS("DailySummary updated."))
