# templatetags/days_since.py
import re
from datetime import date

from django import template
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def days_since(value: date) -> str:
    """
    Returns the number of days since 'value', e.g., '2 days'
    """
    raw = timesince(value)
    match = re.match(r"(\d+) day", raw)
    if match:
        return f"{match.group(1)} days"
    return "Today"
