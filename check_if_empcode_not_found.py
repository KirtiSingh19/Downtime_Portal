import os
import django
import pandas as pd

# Step 1: Set the DJANGO_SETTINGS_MODULE environment variable
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UploadData.settings')  # Replace with your project name

# Step 2: Initialize Django
django.setup()

# Step 3: Now you can safely import models
from users.models import UploadedFile  # Adjust the app name if needed

# Constants
UPLOAD_DIR = "media/EmpCode Not Found/"
TARGET_EMPCODE = "ATS99124"
TARGET_DATE = "09-10-2025"  # Format: DD-MM-YYYY

def read_file(filepath):
    try:
        if filepath.endswith(".csv"):
            return pd.read_csv(filepath)
        elif filepath.endswith((".xls", ".xlsx")):
            return pd.read_excel(filepath)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return pd.DataFrame()

def search_empcode_date(empcode, date):
    matches = []
    for filename in os.listdir(UPLOAD_DIR):
        if filename.endswith((".csv", ".xls", ".xlsx")):
            filepath = os.path.join(UPLOAD_DIR, filename)
            df = read_file(filepath)

            if {'EmpCode', 'Date', 'Minutes'}.issubset(df.columns):
                filtered = df[
                    (df['EmpCode'].astype(str).str.lower() == empcode.lower()) &
                    (df['Date'].astype(str) == date)
                ]
                if not filtered.empty:
                    matches.append((filename, filtered))
    return matches

# Run search
results = search_empcode_date(TARGET_EMPCODE, TARGET_DATE)

# Output results
if results:
    print(f"Matches found for EmpCode '{TARGET_EMPCODE}' on '{TARGET_DATE}':\n")
    for filename, df in results:
    #     try:
    #         file_obj = UploadedFile.objects.get(file__icontains=filename)
            # timestamp = file_obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        # except UploadedFile.DoesNotExist:
            # timestamp = "Unknown (not found in DB)"

        print(f"File: {filename}")
        # print(f"Uploaded at : {timestamp}")
        print(df.to_string(index=False), "\n")
else:
    print(f"No matches found for EmpCode '{TARGET_EMPCODE}' on '{TARGET_DATE}'.")
