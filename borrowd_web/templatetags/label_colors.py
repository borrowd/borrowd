from django import template

register = template.Library()


# Should probably use type or group names e.g. success, warning, etc
# Being direct for now until color palette/usage decisions are made
@register.filter
def label_bg_color(color: str) -> str:
    return {
        "blue": "bg-blue-100",
        "green": "bg-green-100",
        "red": "bg-red-100",
    }.get(color, "bg-blue-100")


@register.filter
def label_text_color(color: str) -> str:
    return {
        "blue": "text-blue-600",
        "green": "text-green-600",
        "red": "text-red-600",
    }.get(color, "text-blue-600")
