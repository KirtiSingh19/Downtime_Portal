import os
import pandas as pd
from django.db.models import Q
from users.models import UploadedFile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def calculate_pending_stats(l1_username):
    """Stats for the files one L1 user still has to mark Lock or Unlock.

    Files created since Cluster Head routing was removed are shared by every L1
    user, so they count for everyone. Older files still belong only to the Cluster
    Head named in their filename.
    """
    pending_files_qs = UploadedFile.objects.filter(
        Q(
            l1_status='',
            rejected_by_l1=False,
            is_valid_format=True,
            is_split=True,
        )
        & (
            Q(legacy_ch_routed=False)
            | Q(legacy_ch_routed=True, file__icontains=l1_username)
        )
    )

    files = [file_obj.file.path for file_obj in pending_files_qs if os.path.exists(file_obj.file.path)]


    if not files:
        return 0, 0, 0

    dfs = []
    for file in files:
        try:
            if file.endswith('.xlsx') or file.endswith('.xls'):
                df = pd.read_excel(file)
            elif file.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                continue
            dfs.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")
            continue

    if not dfs:
        return 0, 0, 0

    combined_df = pd.concat(dfs, ignore_index=True)
    total_processes = combined_df['Process'].nunique() if 'Process' in combined_df.columns else 0
    total_empcode = combined_df['EmpCode'].nunique() if 'EmpCode' in combined_df.columns else 0
    total_records = len(combined_df)
    process_list = combined_df['Process'].dropna().unique().tolist() if 'Process' in combined_df.columns else []
    process_names = ', '.join(sorted(process_list))

    return total_processes, total_empcode, total_records, process_names
