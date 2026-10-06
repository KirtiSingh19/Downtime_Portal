# users/tasks.py
from celery import shared_task
import subprocess
import ntpath
import os
import posixpath
import sys
from django.conf import settings
import pandas as pd
import time 
from django.core.mail import EmailMultiAlternatives, send_mail
from users.models import UploadedFile  # Import your model
from django.utils.timezone import now
import logging
import re
import tempfile
from django.db import InterfaceError, OperationalError
from django.utils.html import escape
from django.utils.timezone import localtime
from pytz import timezone as _timezone

from users.utils import clean_hrms_dump_and_update_mapping

ist = _timezone("Asia/Kolkata")

hrms_logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Daily reminders for files still waiting on someone
# --------------------------------------------------------------------------
# A regular user's upload is not mailed about when it lands. These run at 10:00
# and list what is still outstanding, so a file uploaded today is first reported
# tomorrow morning and keeps being reported until it is actioned.
#
# There is also a dormant `notify_l1_pending` management command that mails each
# L1 user a count. Nothing triggers it; these tasks are the scheduled path.

# Everything not yet finished with. The stage-specific filters are added below.
_PENDING_BASE = dict(
    is_split=True,
    rejected_by_l1=False,
    approved_by_l2=False,
    rejected_by_l2=False,
)


def _pending_rows(queryset):
    """The columns the reminder lists, newest upload first."""
    rows = []
    for record in queryset.select_related('uploaded_by').order_by('-timestamp'):
        rows.append({
            'name': os.path.basename(record.file.name),
            'process': record.process or '-',
            'location': record.location or '-',
            'uploaded_by': record.uploaded_by.username if record.uploaded_by else '-',
            'uploaded': localtime(record.timestamp, ist).strftime('%d-%m-%Y %H:%M'),
        })
    return rows


def _send_pending_reminder(subject, intro, recipient, rows):
    """One mail per recipient listing every outstanding file."""
    if not recipient:
        hrms_logger.warning("No recipient configured for %r; nothing sent.", subject)
        return "Skipped: no recipient configured."

    header = ('File', 'Process', 'Location', 'Uploaded by', 'Uploaded')
    plain = [intro, ""]
    for row in rows:
        plain.append(" | ".join(str(row[k]) for k in
                                ('name', 'process', 'location', 'uploaded_by', 'uploaded')))

    cells = "".join(
        "<tr>" + "".join(
            "<td>%s</td>" % escape(row[k]) for k in
            ('name', 'process', 'location', 'uploaded_by', 'uploaded')
        ) + "</tr>"
        for row in rows
    )
    html = """
    <html><body>
        <p>%s</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background-color: #f2f2f2;">%s</tr>
            %s
        </table>
        <p>Total pending: <strong>%s</strong></p>
    </body></html>
    """ % (
        escape(intro),
        "".join("<th>%s</th>" % escape(h) for h in header),
        cells,
        len(rows),
    )

    send_mail(
        subject=subject,
        message="\n".join(plain),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        html_message=html,
    )
    hrms_logger.info(
        "Sent %r to %s listing %s pending file(s).", subject, recipient, len(rows)
    )
    return "Sent: %s pending file(s) to %s" % (len(rows), recipient)


@shared_task
def notify_l1_pending_files():
    """Files waiting for an L1 user to press Unlock and Save."""
    pending = UploadedFile.objects.filter(**_PENDING_BASE, l1_status='')
    rows = _pending_rows(pending)

    if not rows:
        hrms_logger.info("No files pending L1 lock/unlock; no mail sent.")
        return "Nothing pending for L1."

    return _send_pending_reminder(
        subject="Pending Files - Lock/Unlock Required",
        intro=(
            "This is a reminder that the following files are pending for "
            "Lock/Unlock action. Please review and update the status."
        ),
        recipient=settings.L1_PENDING_NOTIFY_EMAIL,
        rows=rows,
    )


@shared_task
def notify_l2_pending_files():
    """Files L1 has unlocked that are still waiting on an L2 decision."""
    pending = UploadedFile.objects.filter(**_PENDING_BASE, l1_status='unlock')
    rows = _pending_rows(pending)

    if not rows:
        hrms_logger.info("No files pending L2 approval; no mail sent.")
        return "Nothing pending for L2."

    return _send_pending_reminder(
        subject="Pending Files - Approval Required",
        intro=(
            "This is a reminder that the following files are pending for "
            "approval. Please review and approve the pending files."
        ),
        recipient=settings.L2_PENDING_NOTIFY_EMAIL,
        rows=rows,
    )


# --------------------------------------------------------------------------
# HRMS dump -> mapping.csv
# --------------------------------------------------------------------------
# The lock lives beside the dump rather than in memory: the watcher and the
# worker are separate processes, so a threading primitive would not be seen by
# both. O_CREAT|O_EXCL makes the check-and-create one atomic step, which a
# separate exists()-then-create could not guarantee.
HRMS_DUMP_LOCK = "hrms_dump.lock"


@shared_task(bind=True)
def process_hrms_dump(self):
    """Clean the newest HRMS dump and replace media/mapping/mapping.csv.

    Returns a short status string. Failures are logged and returned rather than
    raised: there is nothing to retry automatically, because a dump that fails
    validation will fail identically on a retry, and mapping.csv is left
    untouched either way.
    """
    lock_dir = os.path.join(settings.MEDIA_ROOT, "hrms_dump")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, HRMS_DUMP_LOCK)

    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # A run is already under way. Several events can fire for one arriving
        # file, and processing it twice would race on mapping.csv.
        hrms_logger.info("HRMS dump already being processed; skipping.")
        return "Skipped: another HRMS dump run is in progress."

    try:
        os.write(handle, str(self.request.id or "manual").encode())
        os.close(handle)

        hrms_logger.info("HRMS dump processing started.")
        result = clean_hrms_dump_and_update_mapping()
        hrms_logger.info(
            "HRMS dump processed: %s rows -> %s (%s invalid EmpCode(s) dropped, "
            "removed %s)",
            result["rows"], result["mapping_file"],
            result.get("invalid_empcodes", 0),
            ", ".join(result.get("removed_files") or ["nothing"]),
        )
        return "OK: %s rows written to %s" % (result["rows"], result["mapping_file"])

    except FileNotFoundError as exc:
        # Nothing to do - the dump was already processed, or never arrived.
        hrms_logger.info("No HRMS dump to process: %s", exc)
        return "Nothing to process: %s" % exc

    except Exception as exc:
        hrms_logger.exception("HRMS dump processing failed: %s", exc)
        return "Failed: %s" % exc

    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            hrms_logger.warning("Could not remove the HRMS lock at %s", lock_path)


# A database that was briefly unavailable is worth another attempt; a bad file
# or a broken script is not, and would fail the same way on every retry.
TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


def _describe_failure(stdout, stderr):
    """The most useful one-line reason out of a failed script run."""
    for stream in (stdout or "", stderr or ""):
        for line in stream.splitlines():
            line = line.strip()
            if line.startswith("Upload failed:"):
                return line[len("Upload failed:"):].strip()
    for stream in (stderr or "", stdout or ""):
        lines = [l.strip() for l in stream.splitlines() if l.strip()]
        if lines:
            return lines[-1][:400]
    return "The HRMS upload script failed without reporting a reason."


def _rejected_report_path(stdout):
    """Where hrms.py saved HRMS's per-row rejection report, if it saved one."""
    match = re.search(r"^Rejected report:\s*(.+)$", stdout or "", re.M)
    if not match:
        return None
    path = match.group(1).strip()
    return path if path and os.path.exists(path) else None


def _build_agent_attachments(source_csv, rejected_report, workdir):
    """Write the uploaded and rejected agent lists for the notification.

    Returns a list of (filename, path). The uploaded list is the approved CSV
    minus every EmpCode HRMS refused - filtered_copy drops all of a rejected
    agent's rows, so the two lists partition the file rather than overlapping.
    Never raises: an attachment problem must not stop the mail going out.
    """
    attachments = []
    stem = os.path.splitext(os.path.basename(source_csv or "upload"))[0]

    rejected_codes = set()
    try:
        if rejected_report:
            frame = pd.read_csv(rejected_report)
            if "EmpCode" in frame.columns:
                rejected_codes = set(
                    frame["EmpCode"].astype(str).str.strip().str.upper()
                )
            out = os.path.join(workdir, "%s_rejected_agents.csv" % stem)
            frame.to_csv(out, index=False)
            attachments.append((os.path.basename(out), out))
    except Exception as exc:
        hrms_logger.warning("Could not prepare the rejected-agent list: %s", exc)

    try:
        if source_csv and os.path.exists(source_csv):
            frame = pd.read_csv(source_csv)
            if "EmpCode" in frame.columns:
                codes = frame["EmpCode"].astype(str).str.strip().str.upper()
                uploaded = frame[~codes.isin(rejected_codes)]
                if not uploaded.empty:
                    out = os.path.join(workdir, "%s_uploaded_agents.csv" % stem)
                    uploaded.to_csv(out, index=False)
                    attachments.append((os.path.basename(out), out))
    except Exception as exc:
        hrms_logger.warning("Could not prepare the uploaded-agent list: %s", exc)

    return attachments


def _agent_counts(stdout):
    """The uploaded/rejected agent counts hrms.py prints after a success.

    Returns (uploaded, rejected) or (None, None) when the line is absent - an
    older script, or a run that failed before it got that far.
    """
    match = re.search(
        r"Uploaded agents:\s*(\d+)\s*\|\s*Rejected agents:\s*(\d+)",
        stdout or "",
    )
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _notify_hrms_outcome(file_record, original_file, success, hrms_status,
                         error="", task_id="", l2_user=None, l2_at=None,
                         uploaded_agents=None, rejected_agents=None,
                         attachments=None):
    """Mail the HRMS outcome to the standing recipients and the file's uploader.

    Sent once per outcome per task run. A Celery retry keeps its task id, so a
    retried run does not mail twice; a fresh L2 approval is a new run and does.

    Never raises: a mail problem must not change what happened to the file, nor
    mask the error being reported.
    """
    outcome = "success" if success else "failure"
    key = "%s:%s" % (outcome, task_id or "manual")

    if file_record is not None and file_record.hrms_notified_key == key:
        hrms_logger.info(
            "HRMS %s for %s already notified (%s); not sending again.",
            outcome, original_file, key,
        )
        return False

    recipients = list(settings.HRMS_NOTIFY_EMAILS)
    # The MIS user who uploaded it, taken from the record rather than a list.
    uploader = getattr(getattr(file_record, "uploaded_by", None), "email", "") or ""
    uploader = uploader.strip()
    if uploader:
        if uploader not in recipients:
            recipients.append(uploader)
    else:
        # Not an error - the mail still goes to the standing recipients - but
        # the person who uploaded the file will not hear about it, and that is
        # worth seeing in the log rather than discovering later.
        hrms_logger.warning(
            "No email address on the account that uploaded %s (%s); the HRMS "
            "%s notice goes only to the standing recipients.",
            original_file,
            getattr(getattr(file_record, "uploaded_by", None), "username", "unknown"),
            outcome,
        )
    if not recipients:
        hrms_logger.warning("No recipients configured for HRMS notifications.")
        return False

    when = localtime(now(), ist).strftime("%d-%m-%Y %H:%M:%S")
    process = getattr(file_record, "process", "") or "-"

    if success:
        l2_state = "Approved by L2%s%s" % (
            " by %s" % l2_user if l2_user else "",
            " on %s" % localtime(l2_at, ist).strftime("%d-%m-%Y %H:%M") if l2_at else "",
        )
    else:
        # The approval has already been rolled back by this point, so saying
        # only "not approved" would misdescribe what the L2 user actually did.
        l2_state = "Approved by L2%s, then released because the file was not delivered" % (
            " by %s" % l2_user if l2_user else "",
        )

    rows = [
        ("Process", process),
        ("File name", original_file),
        ("L2 approval status", l2_state),
        ("HRMS status", hrms_status),
    ]
    if uploaded_agents is not None:
        rows.append(("Total agents uploaded", uploaded_agents))
    if rejected_agents is not None:
        rows.append(("Total agents rejected", rejected_agents))
    if not success:
        rows.append(("Error", error or "No reason reported."))
    rows.append(("Completion time" if success else "Failure time", when))

    subject = "HRMS Upload %s: %s" % (
        "Successful" if success else "Failed", original_file,
    )
    plain = "\n".join("%s: %s" % (label, value) for label, value in rows)
    html = """
    <html><body>
        <p>%s</p>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
        %s
        </table>
    </body></html>
    """ % (
        escape(
            "The file below was uploaded to HRMS successfully."
            if success else
            "The file below was approved by L2 but could not be delivered to "
            "HRMS. The approval has been released and the file is pending again."
        ),
        "".join(
            "<tr><th align='left'>%s</th><td>%s</td></tr>" % (escape(l), escape(str(v)))
            for l, v in rows
        ),
    )

    try:
        # EmailMultiAlternatives rather than send_mail: the same HTML-plus-text
        # body, but this one can carry the agent lists as attachments.
        message = EmailMultiAlternatives(
            subject=subject,
            body=plain,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(html, "text/html")
        for name, path in (attachments or []):
            try:
                with open(path, "rb") as handle:
                    message.attach(name, handle.read(), "text/csv")
            except OSError as exc:
                hrms_logger.warning("Could not attach %s: %s", path, exc)
        message.send(fail_silently=False)
        hrms_logger.info(
            "HRMS %s notice for %s sent to %s with %d attachment(s).",
            outcome, original_file, ", ".join(recipients),
            len(attachments or []),
        )
    except Exception as exc:
        hrms_logger.error(
            "Could not send the HRMS %s notice for %s: %s",
            outcome, original_file, exc,
        )
        return False

    if file_record is not None:
        UploadedFile.objects.filter(pk=file_record.pk).update(hrms_notified_key=key)
    return True


def _release_l2_approval(file_record, reason="", attempts=3):
    """Return a file to the L2 queue after a failed HRMS upload.

    Nothing reached HRMS, so the L2 approval must not stand. L1 approval is left
    intact: the file only needs re-approving at the stage that failed.

    Never raises. This runs inside error handling, and a write that fails here
    must not mask the original error or stop the retry being scheduled - which
    is exactly what happened when the database was locked.
    """
    if not file_record:
        return False

    for attempt in range(attempts):
        try:
            file_record.approved_by_l2 = False
            file_record.approved_by_l2_user = None
            file_record.approved_at_l2 = None
            # Recorded so the L2 page can say why the file is back, instead of
            # it silently reappearing as though nothing had happened.
            if reason:
                file_record.last_delivery_error = reason
                file_record.last_delivery_attempt_at = now()
                file_record.delivery_attempts = (file_record.delivery_attempts or 0) + 1
            file_record.save(update_fields=[
                'approved_by_l2', 'approved_by_l2_user', 'approved_at_l2',
                'last_delivery_error', 'last_delivery_attempt_at',
                'delivery_attempts',
            ])
            return True

        except TRANSIENT_DB_ERRORS as exc:
            if attempt == attempts - 1:
                hrms_logger.error(
                    "Could not release the L2 approval for %s after %s attempts: "
                    "%s. The file is recorded as approved but was not delivered.",
                    file_record.file.name, attempts, exc,
                )
                return False
            time.sleep(2 ** attempt)

        except Exception as exc:
            hrms_logger.exception(
                "Could not release the L2 approval for %s: %s",
                file_record.file.name, exc,
            )
            return False

    return False


@shared_task(bind=True, max_retries=5)
def upload_to_hrms(self, file_path):
    file_record = None
    # The producer and this worker need not share an OS. A Windows path arriving
    # at a Linux worker contains no separator POSIX recognises, so basename()
    # would hand back the whole string and the record lookup below could never
    # match - leaving a failed upload silently still approved.
    original_file = ntpath.basename(posixpath.basename(str(file_path)))
    try:
        # media/L2_approved/<stem>.csv was produced from L1_approved/<stem>.xlsx,
        # so match on the stem. Matching the full filename would compare a .csv
        # name against the .xlsx path stored on the record and never hit.
        file_stem = os.path.splitext(original_file)[0]
        file_record = UploadedFile.objects.filter(
            file__icontains=file_stem, is_split=True
        ).first()

        # Read the approval before anything can roll it back, so the notices
        # can still say who approved the file and when.
        l2_user = getattr(getattr(file_record, "approved_by_l2_user", None),
                          "username", None)
        l2_at = getattr(file_record, "approved_at_l2", None)
        task_id = getattr(getattr(self, "request", None), "id", "") or ""

        # The file is uploaded exactly as L2 approved it. It is never converted,
        # de-duplicated or rewritten here; approve_file_and_copy already produced
        # the final CSV, and rewriting it would destroy the approved artifact.
        script_path = os.path.join(settings.BASE_DIR, 'users', 'scripts', 'hrms.py')
        command = [sys.executable, script_path, file_path]
        dry_run = os.environ.get(
            'HRMS_UPLOAD_DRY_RUN', ''
        ).strip().lower() in ('1', 'true', 'yes')
        if dry_run:
            command.append('--dry-run')

        for attempt in range(5):
            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )
            stdout = result.stdout
            stderr = result.stderr

            # A dry run deliberately stops before Import, so it never prints the
            # success banner. Treat it as terminal: retrying it five times and
            # un-approving the file would be wrong.
            if dry_run and result.returncode == 0 and "Dry run complete" in stdout:
                return f"Dry run OK: {original_file}\n{stdout}"

            # Check if subprocess crashed or stderr contains any exception
            if (
                result.returncode != 0
                or "Script failed" in stdout
                or "CRITICAL" in stdout
                or "failed" in stdout.lower()
                or "Traceback" in stderr
                or "Exception" in stderr
                or "NameError" in stderr
            ):

                reason = _describe_failure(stdout, stderr)
                _release_l2_approval(file_record, reason)
                with tempfile.TemporaryDirectory() as workdir:
                    _notify_hrms_outcome(
                        file_record, original_file, success=False,
                        hrms_status="Failed - the upload script reported an error",
                        error=reason, task_id=task_id,
                        l2_user=l2_user, l2_at=l2_at,
                        attachments=_build_agent_attachments(
                            file_path, _rejected_report_path(stdout), workdir,
                        ),
                    )
                return f"Script crash or error detected for file: {original_file}"

            if "Record Saved Successfully!" in stdout:
                uploaded, rejected = _agent_counts(stdout)
                with tempfile.TemporaryDirectory() as workdir:
                    _notify_hrms_outcome(
                        file_record, original_file, success=True,
                        hrms_status="Success - HRMS confirmed the import",
                        task_id=task_id, l2_user=l2_user, l2_at=l2_at,
                        uploaded_agents=uploaded, rejected_agents=rejected,
                        attachments=_build_agent_attachments(
                            file_path, _rejected_report_path(stdout), workdir,
                        ),
                    )
                return f"Success: {original_file}\n{stdout}"
            else:
                if attempt < 4:
                    time.sleep(5)
                    continue
                else:

                    _release_l2_approval(
                        file_record,
                        _describe_failure(stdout, stderr)
                        or "HRMS did not confirm the import after 5 attempts.",
                    )

                    _notify_hrms_outcome(
                        file_record, original_file, success=False,
                        hrms_status="Failed - HRMS did not confirm the import after 5 attempts",
                        error=_describe_failure(stdout, stderr),
                        task_id=task_id, l2_user=l2_user, l2_at=l2_at,
                    )
                    return f"Failed after 5 attempts: {original_file}\nSTDOUT: {stdout}\nSTDERR: {stderr}"

    except subprocess.CalledProcessError as e:
        _release_l2_approval(file_record, _describe_failure(e.stdout, e.stderr))


        _notify_hrms_outcome(
            file_record, original_file, success=False,
            hrms_status="Failed - the upload script could not be run",
            error=_describe_failure(e.stdout, e.stderr),
            task_id=task_id, l2_user=l2_user, l2_at=l2_at,
        )
        return f"Script failed: {original_file}\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"

    except Exception as e:
        transient = isinstance(e, TRANSIENT_DB_ERRORS)
        hrms_logger.exception(
            "HRMS upload task failed for %s (%s): %s",
            original_file, "transient" if transient else "not retryable", e,
        )

        _release_l2_approval(file_record, str(e)[:400])

        _notify_hrms_outcome(
            file_record, original_file, success=False,
            hrms_status=(
                "Failed - the upload task raised an error and will be retried"
                if transient else
                "Failed - the upload task raised an error and was not retried"
            ),
            error=str(e)[:400],
            task_id=locals().get("task_id", ""),
            l2_user=locals().get("l2_user"), l2_at=locals().get("l2_at"),
        )

        # Retry only what a retry can fix. Each retry re-runs the whole task,
        # and the task runs the Selenium upload up to five times - so retrying a
        # deterministic failure five more times costs twenty-five HRMS sessions
        # and cannot succeed.
        if transient:
            self.retry(exc=e, countdown=10, max_retries=5)

        return f"Failed (not retried): {original_file}: {str(e)}"
