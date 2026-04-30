from django import template

register = template.Library()


@register.filter
def first_unit(value: str) -> str:  # mypy error: func missing a type annotation
    if not value:
        return value
    return value.split(",")[0]
