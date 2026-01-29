from datetime import datetime
from typing import TYPE_CHECKING

from django import template
from django.utils import timezone

if TYPE_CHECKING:
    from borrowd_items.models import Item, ItemAction, ItemActionContext
    from borrowd_users.models import BorrowdUser

register = template.Library()


@register.filter
def get_actions_for(item: "Item", user: "BorrowdUser") -> tuple["ItemAction", ...]:
    """
    Template filter to get available actions for an item for a specific user.
    Usage: {{ item|get_actions_for:request.user }}
    """
    return item.get_actions_for(user)


@register.filter
def get_action_context_for(item: "Item", user: "BorrowdUser") -> "ItemActionContext":
    """
    Template filter to get action context for an item for a specific user.
    Returns ItemActionContext with .actions and .status_text.
    Usage: {{ item|get_action_context_for:request.user }}
    """
    return item.get_action_context_for(user)


@register.filter
def timesince_short(value: datetime) -> str:
    """
    Returns a short human-readable time since 'value', e.g., '2h ago', '3d ago'.
    Abbreviates units: h=hours, d=days, w=weeks, m=months, y=years.
    For times less than 1 hour, returns 'Just now'.
    """
    if not value:
        return ""

    now = timezone.now()
    diff = now - value

    total_seconds = diff.total_seconds()

    if total_seconds < 3600:  # Less than 1 hour
        return "Just now"

    hours = total_seconds / 3600
    if hours < 24:
        return f"{int(hours)}h ago"

    days = hours / 24
    if days < 7:
        return f"{int(days)}d ago"

    weeks = days / 7
    if weeks < 4:
        return f"{int(weeks)}w ago"

    months = days / 30
    if months < 12:
        return f"{int(months)}m ago"

    years = days / 365
    return f"{int(years)}y ago"
