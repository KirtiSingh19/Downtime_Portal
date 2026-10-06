import os
import pandas as pd
from datetime import datetime
from pathlib import Path

# Define the folder and output file
UPLOAD_DIR = Path("media/L2_approved")
DIR = Path("media/ishita")
OUTPUT_FILE = DIR / "ishitajain.csv"

# Define the timestamp range (May 1 to June 1, inclusive of May 1)
start_date = datetime(2025, 6, 9)
end_date = datetime(2025, 6, 26)

# Acceptable file extensions
VALID_EXTENSIONS = ['.csv', '.xls', '.xlsx']

# Initialize a list to collect DataFrames
combined_data = []

# Loop through files in upload directory
for file_path in UPLOAD_DIR.iterdir():
    if file_path.suffix.lower() in VALID_EXTENSIONS and file_path.is_file():
        # Get file's modified timestamp
        file_timestamp = datetime.fromtimestamp(file_path.stat().st_mtime)
        
        if start_date <= file_timestamp < end_date:
            try:
                if file_path.suffix == ".csv":
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)
                # df['SourceFile'] = file_path.name  # Optional: Track origin
                combined_data.append(df)
            except Exception as e:
                print(f"Error reading {file_path.name}: {e}")

# Combine and save to ishita.xlsx
if combined_data:
    final_df = pd.concat(combined_data, ignore_index=True)
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Combined file saved as: {OUTPUT_FILE}")
else:
    print("No files found in the specified date range.")
