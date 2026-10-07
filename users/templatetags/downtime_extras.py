"""Small presentation helpers for the downtime templates."""

import os

from django import template

register = template.Library()


@register.filter
def basename(value):
    """Just the file name, without its media sub-folder.

    Every row in a given table sits in the same folder, so repeating
    "L1_approved/" on each one only costs width. The full path is kept in the
    cell's title attribute for anyone who needs it.
    """
    return os.path.basename(str(value).replace("\\", "/"))


# Checked in order; the first phrase found in the lower-cased error wins. Matched
# on HRMS's own wording, so the specific business states come before the
# generic "lock" and "error" catch-alls.
_SHORT_ERRORS = (
    ("already processed", "Attendance already processed"),
    ("lock", "HRMS locked"),
    ("login", "HRMS login failed"),
    ("could not be copied", "Transfer to HRMS host failed"),
    ("could not be queued", "Upload not queued"),
    ("parsed no rows", "HRMS read no rows"),
    ("rejected all", "All records rejected"),
    ("confirmation", "No HRMS confirmation"),
    ("database", "Database error"),
)


@register.filter
def short_error(value, length=40):
    """A few words for a delivery error, for a table cell.

    The full text belongs in the cell's title attribute; this is only the label.
    """
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    lowered = text.lower()
    for phrase, label in _SHORT_ERRORS:
        if phrase in lowered:
            return label
    length = int(length)
    return text if len(text) <= length else text[:length - 1].rstrip() + "…"
