import logging
import os
import re
import shutil
import pandas as pd
from pathlib import Path
from django.conf import settings
from django.db.models import Q
from users.models import UploadedFile


logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# An EmpCode is the letters ATS followed by digits, nothing else. Codes are
# upper-cased and trimmed before this is applied, so "  ats25475 " passes as
# ATS25475; anything still not matching is a row this mapping cannot use.
EMPCODE_PATTERN = re.compile(r"^ATS\d+$")


def calculate_pending_stats(l1_username):
    """Stats for the files one L1 user still has to mark Lock or Unlock.

    Files created since Cluster Head routing was removed are shared by every L1
    user, so they count for everyone. Older files still belong only to the
    Cluster Head named in their filename.
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

    files = [
        file_obj.file.path
        for file_obj in pending_files_qs
        if os.path.exists(file_obj.file.path)
    ]

    if not files:
        return 0, 0, 0, ''

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
        return 0, 0, 0, ''

    combined_df = pd.concat(dfs, ignore_index=True)

    total_processes = (
        combined_df['Process'].nunique()
        if 'Process' in combined_df.columns
        else 0
    )

    total_empcode = (
        combined_df['EmpCode'].nunique()
        if 'EmpCode' in combined_df.columns
        else 0
    )

    total_records = len(combined_df)

    process_list = (
        combined_df['Process']
        .dropna()
        .unique()
        .tolist()
        if 'Process' in combined_df.columns
        else []
    )

    process_names = ', '.join(sorted(process_list))

    return (
        total_processes,
        total_empcode,
        total_records,
        process_names
    )


# ============================================================
# HRMS DUMP CLEANING + MAPPING UPDATE
# ============================================================

def clean_hrms_dump_and_update_mapping():
    """
    Clean the latest HRMS dump file and replace mapping.csv.

    HRMS input columns required:
        EmpCode
        LevelDescription
        LocationName
        Active
        DesignationName

    Processing:
        1. Keep only Active == 1
        2. Remove CCE and Sr.CCE from DesignationName
        3. Keep only EmpCode, LevelDescription, LocationName
        4. Rename LevelDescription -> Process
        5. Rename LocationName -> Location
        6. Remove empty rows
        7. Remove duplicate records

    Cleaned HRMS output:
        media/hrms_dump/<original_name>_cleaned.csv

    Mapping:
        media/mapping/mapping.csv

    Final columns:
        EmpCode
        Process
        Location
    """

    # --------------------------------------------------------
    # 1. Get media paths
    # --------------------------------------------------------

    media_dir = Path(settings.MEDIA_ROOT)

    hrms_dump_dir = media_dir / "hrms_dump"
    mapping_dir = media_dir / "mapping"

    mapping_file = mapping_dir / "mapping.csv"

    # Create folders if they don't exist
    hrms_dump_dir.mkdir(parents=True, exist_ok=True)
    mapping_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # 2. Find HRMS dump files
    # --------------------------------------------------------

    dump_files = []

    for pattern in ("*.csv", "*.xlsx", "*.xls"):
        dump_files.extend(hrms_dump_dir.glob(pattern))

    # Ignore already cleaned files
    original_files = [
        file
        for file in dump_files
        if not file.stem.endswith("_cleaned")
    ]

    if not original_files:
        raise FileNotFoundError(
            f"No HRMS dump file found in {hrms_dump_dir}"
        )

    # Get latest HRMS dump file
    hrms_file = max(
        original_files,
        key=lambda file: file.stat().st_mtime
    )

    logger.info("HRMS dump selected: %s", hrms_file)

    # --------------------------------------------------------
    # 3. Read HRMS file
    # --------------------------------------------------------

    extension = hrms_file.suffix.lower()

    if extension == ".csv":
        df = pd.read_csv(hrms_file)

    elif extension in [".xlsx", ".xls"]:
        df = pd.read_excel(hrms_file)

    else:
        raise ValueError(
            f"Unsupported HRMS file format: {extension}"
        )

    # --------------------------------------------------------
    # 4. Clean column names
    # --------------------------------------------------------

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
    )

    # --------------------------------------------------------
    # 5. Validate required columns
    # --------------------------------------------------------

    required_columns = [
        "EmpCode",
        "LevelDescription",
        "LocationName",
        "Active",
       
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "HRMS dump is missing required columns: "
            + ", ".join(missing_columns)
        )

    logger.info("Total HRMS records before cleaning: %s", len(df))

    # --------------------------------------------------------
    # 6. Keep only Active == 1
    # --------------------------------------------------------

    # Convert Active to string and normalize values
    active_values = (
        df["Active"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    df = df[
        active_values.isin(["1", "1.0", "true", "yes"])
    ].copy()

    logger.info("Records after Active == 1 filter: %s", len(df))

    # --------------------------------------------------------
    # 7. Remove CCE and Sr.CCE
    # --------------------------------------------------------
# --------------------------------------------------------
# 7. Keep ONLY CCE and Sr.CCE / SRCEE
# --------------------------------------------------------

  
    # --------------------------------------------------------
    # 8. Keep only required output columns
    # --------------------------------------------------------

    cleaned_df = df[
        [
            "EmpCode",
            "LevelDescription",
            "LocationName",
        ]
    ].copy()

    # --------------------------------------------------------
    # 9. Rename columns
    # --------------------------------------------------------

    cleaned_df.rename(
        columns={
            "LevelDescription": "Process",
            "LocationName": "Location",
        },
        inplace=True
    )

    # --------------------------------------------------------
    # 10. Clean values
    # --------------------------------------------------------

    for column in [
        "EmpCode",
        "Process",
        "Location",
    ]:
        cleaned_df[column] = (
            cleaned_df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # --------------------------------------------------------
    # 10b. Normalise and validate EmpCode
    # --------------------------------------------------------

    # Upper-case before validating, so a lower-case code from HRMS is corrected
    # rather than rejected: "Ats25475" is the same employee as "ATS25475".
    cleaned_df["EmpCode"] = cleaned_df["EmpCode"].str.upper()

    valid_empcode = cleaned_df["EmpCode"].str.match(EMPCODE_PATTERN)
    invalid_rows = cleaned_df[~valid_empcode]

    if not invalid_rows.empty:
        # Logged one by one and dropped, rather than aborting the run: a single
        # stray code from HRMS must not stop the mapping being refreshed. The
        # values are named so they can be chased up at source.
        for index, value in invalid_rows["EmpCode"].items():
            logger.warning(
                "Invalid EmpCode dropped: %r (source row %s)", value, index
            )
        logger.warning(
            "Dropped %s row(s) with an EmpCode that is not ATS<digits>.",
            len(invalid_rows),
        )

    cleaned_df = cleaned_df[valid_empcode].copy()

    if cleaned_df.empty:
        raise ValueError(
            "No rows with a valid EmpCode remain; mapping.csv left unchanged."
        )

    # --------------------------------------------------------
    # 11. Remove completely empty rows
    # --------------------------------------------------------

    cleaned_df = cleaned_df[
        ~(
            (cleaned_df["EmpCode"] == "")
            & (cleaned_df["Process"] == "")
            & (cleaned_df["Location"] == "")
        )
    ].copy()

    # --------------------------------------------------------
    # 12. Remove duplicate records
    # --------------------------------------------------------

    cleaned_df.drop_duplicates(
        subset=[
            "EmpCode",
            "Process",
            "Location",
        ],
        inplace=True
    )

    # --------------------------------------------------------
    # 13. Ensure final column order
    # --------------------------------------------------------

    cleaned_df = cleaned_df[
        [
            "EmpCode",
            "Process",
            "Location",
        ]
    ]

    logger.info("Final cleaned records: %s", len(cleaned_df))

    # --------------------------------------------------------
    # 14. Save cleaned HRMS dump
    # --------------------------------------------------------

    cleaned_file = (
        hrms_dump_dir /
        f"{hrms_file.stem}_cleaned.csv"
    )

    cleaned_df.to_csv(
        cleaned_file,
        index=False,
        encoding="utf-8-sig"
    )

    logger.info("Cleaned HRMS file created: %s", cleaned_file)

    # --------------------------------------------------------
    # 15. Create temporary mapping file
    # --------------------------------------------------------

    temp_mapping_file = (
        mapping_dir /
        "mapping_temp.csv"
    )

    cleaned_df.to_csv(
        temp_mapping_file,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 16. Replace mapping.csv
    # --------------------------------------------------------

    try:
        os.replace(
            str(temp_mapping_file),
            str(mapping_file)
        )

    except Exception:
        if temp_mapping_file.exists():
            temp_mapping_file.unlink()

        raise

    logger.info("Mapping file successfully replaced: %s", mapping_file)

    # --------------------------------------------------------
    # 17. Clear the processed files out of hrms_dump
    # --------------------------------------------------------

    # Only reached once mapping.csv has been replaced, so a failed run always
    # leaves the dump in place to be retried. Removal failures are logged and
    # not raised: the mapping is already updated and that is the outcome that
    # matters.
    removed = []
    for path in (cleaned_file, hrms_file):
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
                logger.info("Removed processed file: %s", path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)

    # --------------------------------------------------------
    # 18. Return result
    # --------------------------------------------------------

    return {
        "source_file": str(hrms_file),
        "cleaned_file": str(cleaned_file),
        "mapping_file": str(mapping_file),
        "rows": len(cleaned_df),
        "columns": list(cleaned_df.columns),
        "invalid_empcodes": len(invalid_rows),
        "removed_files": removed,
    }