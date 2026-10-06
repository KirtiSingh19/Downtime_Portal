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
UPLOAD_DIR = "media/uploads/"
TARGET_EMPCODE = "ATS95035"
# TARGET_DATE = "06-09-2025"  # Format: DD-MM-YYYY

def read_file(filepath):
    try:
        if filepath.endswith(".csv"):
            return pd.read_csv(filepath)
        elif filepath.endswith((".xls", ".xlsx")):
            return pd.read_excel(filepath)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return pd.DataFrame()

def search_empcode_date(empcode):
    matches = []
    for filename in os.listdir(UPLOAD_DIR):
        if filename.endswith((".csv", ".xls", ".xlsx")):
            filepath = os.path.join(UPLOAD_DIR, filename)
            df = read_file(filepath)

            if {'EmpCode', 'Date', 'Minutes'}.issubset(df.columns):
                filtered = df[
                    (df['EmpCode'].astype(str).str.lower() == empcode.lower()) #& , TARGET_DATE , date on '{TARGET_DATE}'on '{TARGET_DATE}'
                    # (df['Date'].astype(str) == date)
                ]
                if not filtered.empty:
                    matches.append((filename, filtered))
    return matches

# Run search
results = search_empcode_date(TARGET_EMPCODE)

# Output results
if results:
    print(f"Matches found for EmpCode '{TARGET_EMPCODE}' :\n")

    for filename, df in results:
        file_objs = UploadedFile.objects.filter(file__icontains=filename)
        if file_objs.exists():
            for file_obj in file_objs:
                timestamp = file_obj.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                print(f"File: {filename}")
                print(f"Uploaded at : {timestamp}")
                print(df.to_string(index=False), "\n")
        else:
            print(f"File: {filename}")
            print("Uploaded at : Unknown (not found in DB)")
            print(df.to_string(index=False), "\n")
else:
    print(f"No matches found for EmpCode '{TARGET_EMPCODE}' .")
