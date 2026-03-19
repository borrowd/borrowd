from django import template

register = template.Library()

@register.filter
def first_unit(value):
    if not value:
        return value
    return value.split(",")[0]