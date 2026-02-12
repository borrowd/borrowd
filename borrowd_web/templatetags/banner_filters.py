from dataclasses import dataclass

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


# Banner configuration for item cards
BANNER_ICONS = {
    "request": '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
    "available": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"/></svg>',
    "reserved": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z" clip-rule="evenodd"/></svg>',
}

BANNER_STYLES = {
    "request": {"bg": "bg-borrowd-plum-300", "text": "text-borrowd-plum-600"},
    "available": {"bg": "bg-borrowd-fern-300", "text": "text-borrowd-fern-600"},
    "reserved": {"bg": "bg-borrowd-honey-300", "text": "text-borrowd-honey-600"},
}


@dataclass
class BannerConfig:
    """Configuration for item card banner display."""

    banner_type: str
    bg_class: str
    text_class: str
    icon: str
    text: str


@register.filter
def get_banner_config(banner_type: str, context_str: str = "") -> BannerConfig | None:
    """
    Get banner configuration for a given banner type.

    Usage: {{ banner_type|get_banner_config:context_str }}

    context_str format for 'request': "requester_name|time_ago"
    """
    if not banner_type or banner_type not in BANNER_STYLES:
        return None

    style = BANNER_STYLES[banner_type]
    icon = BANNER_ICONS.get(banner_type, "")

    # Build text based on banner type
    if banner_type == "request" and context_str:
        parts = context_str.split("|")
        requester_name = parts[0] if len(parts) > 0 else ""
        time_ago = parts[1] if len(parts) > 1 else ""
        text = f"Requested {time_ago} by {requester_name}"
    elif banner_type == "available":
        text = "Available"
    elif banner_type == "reserved":
        text = "Reserved"
    else:
        text = banner_type.capitalize()

    return BannerConfig(
        banner_type=banner_type,
        bg_class=style["bg"],
        text_class=style["text"],
        icon=mark_safe(icon),
        text=text,
    )
