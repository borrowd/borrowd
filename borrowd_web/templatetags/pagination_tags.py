from typing import Any

from django import template
from django.core.paginator import Page

register = template.Library()


@register.simple_tag
def elided_page_range(page_obj: Page[Any]) -> list[int | None]:
    """Keep the current page and its neighbors while shortening long ranges."""
    return [
        page_number if isinstance(page_number, int) else None
        for page_number in page_obj.paginator.get_elided_page_range(
            page_obj.number,
            on_each_side=1,
            on_ends=1,
        )
    ]
