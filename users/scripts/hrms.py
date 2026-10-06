"""Upload an L2-approved downtime CSV into AccentHRP.

Invoked by ``users.tasks.upload_to_hrms`` as::

    python users/scripts/hrms.py <path-to-media/L2_approved/*.csv>

Contract with the calling task:

* stdout carries exactly one status line. Everything else goes to the log file,
  because ``upload_to_hrms`` treats the substring "failed" anywhere in stdout as
  a failure.
* Exit code 0 with "Record Saved Successfully!" means the data reached HRMS.
* Any other outcome exits non-zero so the task can retry and un-approve.

The L2-approved CSV is treated as an immutable artifact: it is never renamed,
moved, or rewritten. When rejected rows have to be stripped before a re-upload,
the filtered copy is written to a temporary file instead.

The AccentHRP upload screen commits in two steps, and both are required:

1. ``Import Data`` (btn_ImpData) parses the CSV and lists every row in the
   GV_Error preview grid. It saves nothing and reports nothing.
2. ``Save Excel`` (btn_SaveExcel) writes the previewed rows to HRMS. Only this
   step produces a confirmation message.
"""

import logging
import ntpath
import os
import posixpath
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import paramiko
from dotenv import load_dotenv
from scp import SCPClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------------------------------------------------------
# Project layout. users/scripts/hrms.py -> parents[2] is the project root.
# --------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT") or (PROJECT_ROOT / "media"))
L2_APPROVED_DIR = MEDIA_ROOT / "L2_approved"

# Where failed employee records are reported. Never inside L2_approved, and only
# ever written to when HRMS actually rejects something - a clean upload leaves
# this folder untouched.
FAILED_RECORDS_DIR = MEDIA_ROOT / "failed_employees"

# --------------------------------------------------------------------------
# Configuration. Credentials come from .env, never from source.
# --------------------------------------------------------------------------
PORTAL_URL = os.environ.get("HRMS_PORTAL_URL", "http://192.168.1.45:4433/Accenthrp/")
PORTAL_USER = os.environ.get("HRMS_PORTAL_USER", "")
PORTAL_PASSWORD = os.environ.get("HRMS_PORTAL_PASSWORD", "")

# Optional: where the rejected-row report is copied for the OPs team.
REJECTED_SCP_HOST = os.environ.get("HRMS_HOST", "")
REJECTED_SCP_USER = os.environ.get("HRMS_USER", "")
REJECTED_SCP_PASSWORD = os.environ.get("HRMS_PASSWORD", "")
REJECTED_SCP_DIR = os.environ.get("HRMS_REJECTED_DIR", "")

SUCCESS_MESSAGE = "Record Saved Successfully!"

logging.basicConfig(
    filename=str(SCRIPT_DIR / "hrms_log.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def fail(reason):
    """Report a failure on stdout and exit non-zero for upload_to_hrms."""
    logging.error(reason)
    print(f"Upload failed: {reason}")
    sys.exit(1)


def resolve_target_csv(argv):
    """Return the L2-approved CSV to upload.

    A path given on the command line wins. Anything that does not resolve as
    given falls back to media/L2_approved/<filename>. With no argument at all -
    only when the script is run by hand - the newest CSV in that folder is used.

    The fallback takes the filename with both separator conventions on purpose.
    The producer and this script need not share an OS: a Windows caller passes
    "D:\\...\\media\\L2_approved\\x.csv", which POSIX neither treats as absolute
    nor splits, so posixpath.basename() alone would hand back the whole string
    and build a nonsense path out of it.
    """
    if len(argv) > 1 and argv[1].strip():
        raw = argv[1].strip()
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate.resolve()

        in_l2 = L2_APPROVED_DIR / ntpath.basename(posixpath.basename(raw))
        if in_l2.is_file():
            logging.info("Resolved %r to %s via L2_approved.", raw, in_l2)
            return in_l2.resolve()
        return in_l2

    logging.info("No path argument supplied; falling back to the newest L2-approved CSV.")
    if not L2_APPROVED_DIR.is_dir():
        fail(f"L2-approved directory does not exist: {L2_APPROVED_DIR}")
    candidates = sorted(
        L2_APPROVED_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        fail(f"No CSV files in {L2_APPROVED_DIR}")
    return candidates[0].resolve()


def build_driver():
    prefs = {
        "profile.default_content_settings.popups": 0,
        "download.default_directory": str(FAILED_RECORDS_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "safebrowsing.disable_download_protection": True,
    }
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-web-security")
    # Required: the worker container has no X display, so a windowed Chrome exits
    # at startup and Selenium reports it as "Chrome instance exited".
    options.add_argument("--headless=new")
    options.add_experimental_option("prefs", prefs)
    # Leave alerts standing instead of the default dismiss-and-notify. An ASP.NET
    # page may report the import outcome through alert(), and the default would
    # throw it away before it could be read - as a bare TimeoutException, which
    # is exactly what a missing banner looks like.
    options.set_capability("unhandledPromptBehavior", "ignore")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )


def take_alert(driver):
    """Return the text of an open JavaScript alert and dismiss it, else None."""
    try:
        alert = driver.switch_to.alert
        text = alert.text
        alert.accept()
        logging.info("JavaScript alert: %r", text)
        return text
    except Exception:
        return None


def open_upload_screen(driver):
    """Log in and navigate to Leave Section > Upload Productive Hour(CSV)."""
    driver.get(PORTAL_URL)
    logging.info("Accessed HRMS login page.")

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "txtUserName"))
    ).send_keys(PORTAL_USER)
    driver.find_element(By.ID, "txtPasswd").send_keys(PORTAL_PASSWORD)
    WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.ID, "btnSubmit"))
    ).click()
    logging.info("Login submitted.")
    time.sleep(4)

    # A rejected login leaves the browser on the login form, so the wait below
    # would spend 20 seconds and then raise a TimeoutException carrying no
    # message at all - which says nothing about the actual cause. Read the page
    # first and report it plainly.
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        page_text = ""
    for marker in ("valid password", "invalid password", "invalid user",
                   "incorrect password", "login failed"):
        if marker in page_text:
            fail(
                "HRMS rejected the login (portal said: %r). Check "
                "HRMS_PORTAL_USER and HRMS_PORTAL_PASSWORD in .env - the "
                "account may also be locked after repeated attempts." % marker
            )

    WebDriverWait(driver, 20).until(
        EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame1"))
    )
    logging.info("Switched to 'mainFrame1' iframe.")

    leave_menu = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.LINK_TEXT, "Leave Section"))
    )
    ActionChains(driver).move_to_element(leave_menu).perform()
    logging.info("Hovered over 'Leave Section'.")

    WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.LINK_TEXT, "Upload Productive Hour(CSV)"))
    ).click()
    logging.info("Navigated to Upload Productive Hour(CSV).")
    time.sleep(5)


def submit_file(driver, csv_path, dry_run=False):
    """Attach a CSV and press Import Data. Returns any alert text it raised."""
    file_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "FileUpload1"))
    )
    file_input.send_keys(str(csv_path))
    logging.info("Attached file: %s", csv_path)
    time.sleep(5)

    import_button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.ID, "btn_ImpData"))
    )
    if dry_run:
        logging.info("DRY RUN: Import Data located but not clicked.")
        return None
    import_button.click()
    logging.info("Import Data button clicked.")
    time.sleep(5)
    # Read any alert before anything else: with unhandledPromptBehavior=ignore an
    # open dialog makes every subsequent WebDriver call raise.
    return take_alert(driver)


def _preview_grid(driver):
    """Return the GV_Error preview grid, or None when HRMS rendered none.

    Despite the id, GV_Error is not an errors-only table: Import Data parses the
    CSV and lists every row in it under the columns
    ``ErrorMessage | EmpCode | Date | Minutes``. A row whose ErrorMessage cell is
    blank was accepted; a populated one names the problem. Its absence means the
    file was not parsed at all, so the wait is short and its own signal.
    """
    try:
        return WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, "//table[@id='GV_Error']"))
        )
    except Exception:
        return None


def _grid_rows(table):
    """Return the grid's data rows as lists of cell text, header excluded."""
    rows = []
    for row in table.find_elements(By.TAG_NAME, "tr"):
        cols = row.find_elements(By.TAG_NAME, "td")
        if cols:
            rows.append([col.text.strip() for col in cols])
    return rows


def extract_rejected_rows(driver):
    """Return the rows HRMS flagged, or an empty frame when every row was clean."""
    table = _preview_grid(driver)
    if table is None:
        logging.warning(
            "No GV_Error preview grid; HRMS did not parse the file into rows."
        )
        return pd.DataFrame()

    rows = _grid_rows(table)
    rejected = [row for row in rows if row and row[0]]
    logging.info(
        "Preview grid holds %d parsed row(s), %d of them flagged.",
        len(rows), len(rejected),
    )
    return pd.DataFrame(rejected)


def preview_row_count(driver):
    """How many rows Import Data parsed out of the CSV."""
    table = _preview_grid(driver)
    return 0 if table is None else len(_grid_rows(table))


def commit_import(driver):
    """Press Save Excel to commit the previewed rows. Returns any alert text.

    This is the step that actually writes to HRMS. Import Data alone only parses
    the CSV into the preview grid - it reports nothing and saves nothing, which
    is why the screen offers both buttons.
    """
    button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.ID, "btn_SaveExcel"))
    )
    button.click()
    logging.info("Save Excel button clicked; committing the previewed rows.")
    time.sleep(5)
    return take_alert(driver)


def save_rejected_report(rejected):
    """Write the rejected rows next to the media tree and return the path."""
    FAILED_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    path = FAILED_RECORDS_DIR / f"{stamp}_{uuid.uuid4().hex[:8]}_rejected.csv"

    report = rejected.copy()
    if report.shape[1] == 4:
        report.columns = ["Error", "EmpCode", "Date", "Minutes"]
    report.to_csv(path, index=False)
    logging.info("Rejected-row report written to %s", path)
    return path


def save_failed_employees(csv_path, hrms_error):
    """Report every employee in the CSV as failed, with the error HRMS gave.

    Used when HRMS turns down the file as a whole rather than row by row: the
    commit never went through, so no employee in it was saved and they all
    failed for the one reason HRMS reported. Row-level rejections are handled by
    save_rejected_report, which already carries the per-row ErrorMessage.

    The Error column holds the message HRMS itself returned. The caller only
    falls back to a description of its own when HRMS said nothing at all.
    """
    try:
        source = pd.read_csv(csv_path)
    except Exception as exc:
        logging.error(
            "Could not read %s to build the failed-employee report: %s",
            csv_path, exc, exc_info=True,
        )
        return None

    if source.empty:
        logging.warning("%s holds no rows; no failed-employee report written.", csv_path)
        return None

    FAILED_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    path = FAILED_RECORDS_DIR / f"{stamp}_{uuid.uuid4().hex[:8]}_failed.csv"

    report = source.copy()
    report.insert(0, "Error", " ".join(str(hrms_error).split()))
    report.to_csv(path, index=False)
    logging.info(
        "Failed-employee report for %d record(s) written to %s (Error=%r)",
        len(report), path, hrms_error,
    )
    return path


def filtered_copy(csv_path, rejected):
    """Write a temp CSV without the rejected EmpCodes. Original is untouched."""
    if rejected.shape[1] < 2:
        logging.warning("Rejected table has too few columns to identify EmpCodes.")
        return None, 0

    rejected_codes = set(rejected[1].astype(str).str.strip().str.upper())
    approved = pd.read_csv(csv_path)
    codes = approved.iloc[:, 0].astype(str).str.strip().str.upper()
    remaining = approved[~codes.isin(rejected_codes)]

    if remaining.empty:
        return None, 0

    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix="hrms_retry_", delete=False, newline=""
    )
    remaining.to_csv(handle, index=False)
    handle.close()
    logging.info(
        "Wrote filtered retry file %s with %d of %d row(s).",
        handle.name, len(remaining), len(approved),
    )
    return Path(handle.name), len(remaining)


def copy_report_to_ops(report_path):
    """Best-effort SCP of the rejected-row report. Never affects the exit code."""
    if not (REJECTED_SCP_HOST and REJECTED_SCP_DIR and REJECTED_SCP_PASSWORD):
        logging.info("Rejected-report SCP not configured; keeping the local copy only.")
        return

    ssh = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=REJECTED_SCP_HOST,
            username=REJECTED_SCP_USER,
            password=REJECTED_SCP_PASSWORD,
            timeout=10,
        )
        remote_path = f"{REJECTED_SCP_DIR.rstrip('/')}/{report_path.name}"
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(str(report_path), remote_path)
        logging.info("Copied rejected-row report to %s", remote_path)
    except Exception as exc:
        logging.error("Could not copy the rejected-row report: %s", exc, exc_info=True)
    finally:
        if ssh is not None:
            ssh.close()


# --------------------------------------------------------------------------
# Reading the import result out of AccentHRP.
#
# btn_ImpData is a plain type=submit, so Import Data is a full ASP.NET postback
# and the outcome comes back rendered into the page. The screen ships four
# empty message holders - the ASP.NET labels lbl_Msg and lbl_FileName (both
# class="Err_Msg", used for any message, not only errors) and the script-driven
# containers #MessageBar_MessageBox and #message. Any of them may carry the
# result, so all of them are read instead of betting on one banner.
#
# Only these dedicated holders decide the verdict. Whole-page text is logged for
# diagnostics but never classified: the rejected-row grid renders a column
# header literally called "Error", which would poison a naive keyword scan.
# --------------------------------------------------------------------------

MESSAGE_ELEMENT_IDS = ("lbl_Msg", "lbl_FileName", "MessageBar_MessageBox", "message")

DIAGNOSTIC_KEYWORDS = (
    "saved", "success", "successfully", "imported", "import",
    "error", "failed", "rejected",
)

# Checked before the success phrases so that "Import failed" cannot be read as a
# success just because it contains the word "import".
FAILURE_PHRASES = (
    "failed", "failure", "not saved", "unable", "invalid", "exception",
    "please select", "no file", "does not exist", "not uploaded", "wrong",
)

SUCCESS_PHRASES = (
    "record saved successfully", "saved successfully", "record saved",
    "successfully imported", "imported successfully", "import completed",
    "import successful", "successfully uploaded", "uploaded successfully",
    "data imported", "data saved", "success",
)


def classify(text):
    """Return True/False for a decisive message, or None when it says nothing."""
    if not text or not text.strip():
        return None
    lowered = text.strip().lower()
    if any(phrase in lowered for phrase in FAILURE_PHRASES):
        return False
    if any(phrase in lowered for phrase in SUCCESS_PHRASES):
        return True
    if "error" in lowered:
        return False
    return None


def _message_elements(driver):
    """Yield (source, text) for every message holder that carries text."""
    for element_id in MESSAGE_ELEMENT_IDS:
        for element in driver.find_elements(By.ID, element_id):
            text = (element.text or "").strip()
            if not text:
                # A hidden ASP.NET label still holds its caption in innerText.
                text = (element.get_attribute("innerText") or "").strip()
            classes = element.get_attribute("class") or ""
            logging.info(
                "  message holder #%s (class=%r, displayed=%s): %r",
                element_id, classes, element.is_displayed(), text,
            )
            if text:
                yield f"#{element_id}", text


def log_post_import_state(driver, alert_text):
    """Log everything AccentHRP shows after Import Data. Returns message evidence.

    Diagnostics only - the return value is the ordered list of (source, text)
    candidates the verdict is drawn from.
    """
    logging.info("-" * 25 + " POST-IMPORT PAGE STATE " + "-" * 25)
    logging.info("1. current URL : %s", driver.current_url)
    logging.info("2. page title  : %r", driver.title)
    logging.info("3. frame       : mainFrame1 (upload screen)")
    logging.info("6. JS alert    : %r", alert_text)

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception as exc:
        body_text = ""
        logging.warning("Could not read page text: %s", exc)
    logging.info("4. visible page text (%d chars):\n%s", len(body_text), body_text)

    logging.info("5. message holders:")
    evidence = list(_message_elements(driver))
    if not evidence:
        logging.info("  (every message holder was empty)")

    logging.info("7. elements containing result keywords:")
    seen = set()
    for keyword in DIAGNOSTIC_KEYWORDS:
        xpath = (
            "//*[not(self::script or self::style)]"
            "[contains(translate(normalize-space(text()),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{keyword}')]"
        )
        for element in driver.find_elements(By.XPATH, xpath):
            try:
                text = (element.text or "").strip()
                key = (element.tag_name, element.get_attribute("id"), text[:60])
                if text and key not in seen:
                    seen.add(key)
                    logging.info(
                        "  [%s] <%s id=%r class=%r> %r",
                        keyword, element.tag_name, element.get_attribute("id"),
                        element.get_attribute("class"), text[:200],
                    )
            except Exception:
                continue
    if not seen:
        logging.info("  (no element carried any of the result keywords)")

    logging.info("8. HTML around the import result:")
    for element_id in ("Panel1", "UpdatePanel1"):
        for element in driver.find_elements(By.ID, element_id):
            html = (element.get_attribute("outerHTML") or "")[:4000]
            logging.info("  #%s outerHTML:\n%s", element_id, html)

    frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(
        By.TAG_NAME, "frame"
    )
    logging.info("9. nested frames on the result page: %d", len(frames))
    for frame in frames:
        logging.info(
            "  <%s id=%r src=%r>", frame.tag_name,
            frame.get_attribute("id"), frame.get_attribute("src"),
        )
    logging.info("-" * 74)
    return evidence


def evaluate_import(driver, alert_text, rejected_count):
    """Decide whether HRMS actually accepted the import.

    Returns (succeeded, reason, hrms_message), where hrms_message is what HRMS
    said verbatim, or None when it said nothing usable - the failed-employee
    report records the real message and only falls back when there is none.

    Silence is not success: with no decisive message the import is reported as a
    failure, because claiming success would leave the file marked delivered when
    nothing is known to have been saved.
    """
    evidence = log_post_import_state(driver, alert_text)

    candidates = []
    if alert_text:
        candidates.append(("javascript alert", alert_text))
    candidates.extend(evidence)

    for source, text in candidates:
        verdict = classify(text)
        if verdict is True:
            logging.info("HRMS confirmed the import via %s: %r", source, text)
            return True, text, text
        if verdict is False:
            logging.error("HRMS reported a failure via %s: %r", source, text)
            return False, f"HRMS reported: {text}", text

    if candidates:
        joined = " | ".join(f"{s}={t!r}" for s, t in candidates)
        logging.error("HRMS message was not decisive: %s", joined)
        return False, f"HRMS gave no clear confirmation ({joined})", candidates[0][1]

    logging.error(
        "HRMS displayed no message at all after Import Data "
        "(%d rejected row(s) reported).", rejected_count,
    )
    return False, "HRMS displayed no import confirmation", None


def main():
    started = time.time()
    logging.info("=" * 30 + f" START {datetime.now():%Y-%m-%d %H:%M:%S} " + "=" * 30)

    dry_run = "--dry-run" in sys.argv
    argv = [a for a in sys.argv if a != "--dry-run"]

    if not PORTAL_USER or not PORTAL_PASSWORD:
        fail("HRMS_PORTAL_USER / HRMS_PORTAL_PASSWORD are not set in .env")

    csv_path = resolve_target_csv(argv)
    if not csv_path.is_file():
        fail(f"L2-approved CSV not found: {csv_path}")
    logging.info("Uploading L2-approved file: %s", csv_path)

    driver = None
    retry_path = None
    try:
        driver = build_driver()
        open_upload_screen(driver)
        alert_text = submit_file(driver, csv_path, dry_run=dry_run)

        if dry_run:
            logging.info("DRY RUN complete; nothing was imported.")
            print("Dry run complete: upload screen reached, no data imported.")
            return 0

        # The approved file as submitted. Counting is per row, not per distinct
        # EmpCode: one agent with six dated entries is six uploaded records, and
        # that is what the attached uploaded_agents.csv lists.
        try:
            submitted = pd.read_csv(csv_path)
            submitted_codes = (
                submitted["EmpCode"].astype(str).str.strip().str.upper()
            )
        except Exception:
            submitted, submitted_codes = None, None

        rejected = extract_rejected_rows(driver)
        if not rejected.empty:
            report_path = save_rejected_report(rejected)
            copy_report_to_ops(report_path)
            # Named on stdout so upload_to_hrms can attach it to the
            # notification. "Rejected" is deliberate - "failed" anywhere in
            # stdout is read as a crash by the calling task.
            print("Rejected report: %s" % report_path)

            retry_path, remaining = filtered_copy(csv_path, rejected)
            if retry_path is None:
                logging.info(
                    "Every row was rejected by HRMS; nothing remains to import."
                )
                # Column 0 of the preview grid is HRMS's message for each
                # row. Naming it here is what lets the L2 page tell a locked
                # attendance period from any other refusal; the count alone
                # cannot. Nothing about the import, retry or report changes.
                reasons = sorted(
                    {str(r).strip() for r in rejected[0] if str(r).strip()}
                ) if rejected.shape[1] else []
                print(
                    "Upload failed: HRMS rejected all %d record(s). Reason: %s"
                    % (len(rejected), "; ".join(reasons) or "not reported")
                )
                return 1

            logging.info("Re-importing %d accepted row(s).", remaining)
            alert_text = submit_file(driver, retry_path)

        parsed = preview_row_count(driver)
        if parsed == 0:
            logging.error("HRMS parsed no rows; there is nothing to save.")
            # Whatever HRMS put on the screen explains why it parsed nothing;
            # prefer it over a description of our own.
            evidence = log_post_import_state(driver, alert_text)
            detail = next((text for _, text in evidence), None) or alert_text
            save_failed_employees(
                csv_path, detail or "HRMS parsed no rows out of the CSV."
            )
            print("Upload failed: HRMS parsed no rows out of the CSV.")
            return 1

        logging.info("Committing %d previewed row(s) to HRMS.", parsed)
        alert_text = commit_import(driver) or alert_text

        succeeded, reason, hrms_message = evaluate_import(
            driver, alert_text, len(rejected)
        )
        if succeeded:
            # Nothing is written to failed_employees on a clean upload.
            rejected_codes = set()
            if not rejected.empty and rejected.shape[1] > 1:
                rejected_codes = set(
                    rejected[1].astype(str).str.strip().str.upper()
                )
            # filtered_copy drops every row of a rejected EmpCode, so the two
            # row counts partition the submitted file exactly.
            if submitted_codes is not None:
                rejected_rows = int(submitted_codes.isin(rejected_codes).sum())
                uploaded_rows = int(len(submitted) - rejected_rows)
            else:
                rejected_rows = len(rejected)
                uploaded_rows = max(parsed, 0)
            print(SUCCESS_MESSAGE)
            # A second line the calling task parses for the notification email.
            # Deliberately worded without "failed": upload_to_hrms treats that
            # word anywhere in stdout as a crash, so "Rejected agents" it is.
            print(
                "Uploaded agents: %d | Rejected agents: %d"
                % (uploaded_rows, rejected_rows)
            )
            logging.info(
                "Upload complete: %d row(s) uploaded, %d rejected "
                "(%d distinct EmpCode(s) refused).",
                uploaded_rows, rejected_rows, len(rejected_codes),
            )
            return 0

        save_failed_employees(csv_path, hrms_message or reason)

        # stdout must stay a single line: upload_to_hrms scans it for markers.
        print(f"Upload failed: {' '.join(reason.split())[:300]}")
        return 1

    except Exception as exc:
        logging.critical("Upload aborted: %s", exc, exc_info=True)
        print(f"Upload failed: {exc}")
        return 1

    finally:
        if driver is not None:
            driver.quit()
        if retry_path is not None:
            try:
                retry_path.unlink(missing_ok=True)
            except OSError:
                pass
        logging.info("Total execution time: %.2f seconds", time.time() - started)


if __name__ == "__main__":
    sys.exit(main())