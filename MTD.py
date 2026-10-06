import os
import re
import pandas as pd
from datetime import datetime
from django.core.mail import EmailMessage
from django.conf import settings
import django
from collections import defaultdict

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UploadData.settings')  # Replace with your project name
django.setup()

# Define directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPROVED_DIR = os.path.join(BASE_DIR, 'media', 'L2_approved')
STATUS_DIR = os.path.join(BASE_DIR, 'media', 'combined_approve_mtd')
MTD_DIR = os.path.join(BASE_DIR, 'media', 'mtd_status')
ACTIVE_DIR = os.path.join(BASE_DIR, 'media', 'active_list')
MAPPING_FILE = os.path.join(BASE_DIR, 'media', 'process_ch', 'ats_process_ch.xlsx')

# Create folders if not exist
os.makedirs(STATUS_DIR, exist_ok=True)
os.makedirs(MTD_DIR, exist_ok=True)

# Date setup
today = datetime.today()
today_str = today.strftime('%d-%m-%Y')
current_month = today.strftime('%Y-%m')
date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')

# Read and combine approved files
dfs = []
for file in os.listdir(APPROVED_DIR):
    if file.endswith(('.csv', '.xls', '.xlsx')):
        file_path = os.path.join(APPROVED_DIR, file)
        try:
            if file.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            dfs.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")

if not dfs:
    print("No valid files found for the current month.")
    exit()

# Combine files
combined_df = pd.concat(dfs, ignore_index=True)

# Map Process column
try:
    mapping_df = pd.read_excel(MAPPING_FILE)
    if 'EmpCode' not in mapping_df.columns or 'Process' not in mapping_df.columns:
        raise ValueError("Mapping file must contain 'EmpCode' and 'Process'")
    
    combined_df = combined_df.merge(mapping_df[['EmpCode', 'Process']], on='EmpCode', how='left')

except Exception as e:
    print(f"Error loading mapping file: {e}")
    exit()

# Save combined file to media/status
combined_file_path = os.path.join(STATUS_DIR, f"{today_str}.csv")
combined_df.to_csv(combined_file_path, index=False)

# Filter to current month
combined_df['Date'] = pd.to_datetime(combined_df['Date'], errors='coerce')
combined_df = combined_df[combined_df['Date'].dt.month == today.month]
combined_df = combined_df[combined_df['Date'].dt.year == today.year]
combined_df['Date'] = combined_df['Date'].dt.strftime('%Y-%m-%d')

# Drop rows with missing EmpCode or Date
combined_df = combined_df.dropna(subset=['EmpCode', 'Date'])

# Ensure EmpCode is treated as string (if needed)
combined_df['EmpCode'] = combined_df['EmpCode'].astype(str)

# Drop duplicates based on EmpCode + Date + Process
unique_df = combined_df.drop_duplicates(subset=['EmpCode', 'Date', 'Process'])

# --- Build multi-level table ---
data_dict = defaultdict(dict)
process_set = set()
date_set = set()
hrms_error_dates = set()
# Get all unique dates
date_columns = sorted(unique_df['Date'].unique())

for date_col in date_columns:
    date_display = datetime.strptime(date_col, '%Y-%m-%d').strftime('%d-%m-%Y')
    date_set.add(date_display)

    # Attendance count per process
    attendance_counts = unique_df[unique_df['Date'] == date_col]['Process'].value_counts()

    # Head count from active list
    active_file = os.path.join(ACTIVE_DIR, f"{date_col}_active.xlsx")
    # head_counts = pd.Series(dtype=int)
    head_counts = {}
    hrms_error = False

    if os.path.exists(active_file):
        try:
            active_df = pd.read_excel(active_file)

            # Apply filters
            valid_designations = ['CCE', 'SR.CCE', 'Sr. Tourist Information Executive']
            excluded_levels = ['Corporate', 'SHARED']

            filtered_df = active_df[
                active_df['Designation'].isin(valid_designations) &
                ~active_df['Level'].isin(excluded_levels)
            ]

            # Count per process
            if 'Level' in filtered_df.columns:
                head_counts = filtered_df['Level'].value_counts()

        except Exception as e:
            print(f"Error reading or filtering {active_file}: {e}")
            hrms_error = True
    else:
        hrms_error = True

    if hrms_error:
        hrms_error_dates.add(date_display)

    all_processes = set(attendance_counts.index).union(set(head_counts.keys()))
    for process in all_processes:
        attn = int(attendance_counts.get(process, 0))
        if hrms_error:
            head = 'HRMS Error'
        else:
            head = int(head_counts.get(process, 0))
        data_dict[process][date_display] = {'Head Count': head, 'Attendance Count': attn}
        process_set.add(process)

# Sort processes and dates
processes = sorted(process_set)
dates = sorted(date_set, key=lambda d: datetime.strptime(d, '%d-%m-%Y'))

# Build MultiIndex columns
tuples = []
for date in dates:
    tuples.append((date, 'Head Count'))
    tuples.append((date, 'Attendance Count'))
multi_index = pd.MultiIndex.from_tuples(tuples)

# Create final DataFrame
final_table = []
for process in processes:
    row = []
    for date in dates:
        if date in hrms_error_dates:
            head = 'HRMS Error'
        else:
            head = data_dict[process].get(date, {}).get('Head Count', 0)
            head = head if isinstance(head, str) else int(head)
        attn = data_dict[process].get(date, {}).get('Attendance Count', 0)
        row.append(head)
        row.append(attn)
    final_table.append(row)

final_df = pd.DataFrame(final_table, index=processes, columns=multi_index)
final_df.index.name = 'Process'

attendance_cols_idx = [i for i, col in enumerate(final_df.columns) if col[1] == 'Attendance Count']
final_df[('Total', 'Attendance Count')] = final_df.iloc[:, attendance_cols_idx].sum(numeric_only=True, axis=1)

# Add 'Total' row (sum for both Head Count and Attendance Count across all processes)
total_row = {}
for col in final_df.columns:
    if final_df[col].dtype == 'O':  # object type, could include strings like 'HRMS Error'
        total_row[col] = ''
    else:
        total_row[col] = final_df[col].sum()

# Append total row
final_df.loc['Total'] = pd.Series(total_row)

# Save CSV
mtd_file_path = os.path.join(MTD_DIR, f"MTD_Summary_with_HC_{today_str}.csv")
final_df.to_csv(mtd_file_path)

# Convert to styled HTML table
html_table = final_df.style.set_table_attributes('border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; text-align: center;"') \
    .set_properties(**{'border': '1px solid black', 'padding': '5px'}) \
    .apply(lambda x: ['background-color: #d9edf7; font-weight: bold;' if x.name == 'Total' else '' for _ in x], axis=1) \
    .to_html()


# Prepare email content
subject = f"MTD Process Summary Report - {today_str}"
from_email = settings.DEFAULT_FROM_EMAIL
to_emails = ['digx.automation@iccs.in', 'trrishan.pareek@iccs.in', 'sourabh.kumar@iccs.in']  # Replace with actual recipients 

# , 'ravi.taneja@iccs.in',
#             'ajay.kalra@iccs.in', '	ramakrishna.prasad@iccs.in', '	rohit.singh@iccs.in', '	chandrachooda.bhat@iccs.in',
#             'satish.kumar1@iccs.in', '	wasim.saudagar@iccs.in', 'gaurav.kukreja@iccs.in', 'amit.miglani@iccs.in', 'vikram.arora@iccs.in'

html_content = f"""
<p>Dear Team,</p>
<p>Please find below the Month-to-Date Process Summary as of <b>{today_str}</b>:</p>
{html_table}
<p>Attached are the full combined data file and the MTD summary as CSV for reference.</p>
"""

# Send email with 2 attachments
email = EmailMessage(
    subject=subject,
    body=html_content,
    from_email=from_email,
    to=to_emails,
)
email.content_subtype = "html"

# Attach combined file and MTD file
with open(combined_file_path, 'rb') as f1:
    email.attach(os.path.basename(combined_file_path), f1.read(), 'text/csv')
with open(mtd_file_path, 'rb') as f2:
    email.attach(os.path.basename(mtd_file_path), f2.read(), 'text/csv')

email.send()
print("Email sent with summary and attachments.")
