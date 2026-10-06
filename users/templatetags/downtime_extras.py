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
