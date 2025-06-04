from django import template

register = template.Library()


# Should probably use type or group names e.g. success, warning, etc
# Being direct for now until color palette/usage decisions are made
@register.filter
def label_bg_color(color: str) -> str:
    return {
        "blue": "bg-blue-200",
        "green": "bg-green-200",
        "red": "bg-red-200",
    }.get(color, "bg-blue-200")


@register.filter
def label_text_color(color: str) -> str:
    return {
        "blue": "text-blue-500",
        "green": "text-green-500",
        "red": "text-red-500",
    }.get(color, "text-blue-500")
