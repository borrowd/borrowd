from uuid import uuid4

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString

from borrowd_items.models import Item

register = template.Library()


@register.simple_tag
def command_fields(item: Item) -> SafeString:
    """
    Hidden fields for a lifecycle action form: the item revision it was
    rendered at, so a stale page is refused, and a fresh command key, so a
    double submit is only done once.
    """
    return format_html(
        '<input type="hidden" name="revision" value="{}">'
        '<input type="hidden" name="command_key" value="{}">',
        item.revision,
        uuid4(),
    )
