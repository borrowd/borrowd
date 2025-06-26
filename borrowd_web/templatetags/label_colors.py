from django import template

register = template.Library()


# Should probably use type or group names e.g. success, warning, etc
# Being direct for now until color palette/usage decisions are made
@register.filter
def label_bg_color(color: str) -> str:
    return {
        "blue": "bg-borrowd-indigo-300",
        "green": "bg-borrowd-fern-300",
        "red": "bg-borrowd-plum-300",
        "yellow": "bg-borrowd-honey-300",
    }.get(color, "bg-borrowd-indigo-300")


@register.filter
def label_text_color(color: str) -> str:
    return {
        "blue": "text-borrowd-indigo-600",
        "green": "text-borrowd-fern-600",
        "red": "text-borrowd-plum-600",
        "yellow": "text-borrowd-honey-600",
    }.get(color, "text-borrowd-indigo-600")
