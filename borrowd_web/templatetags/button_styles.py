from django import template

register = template.Library()

"""
    Button styling filters.
    With future UI/UX designs, add additional styling here beyond just colors.
"""


@register.filter
def button_bg_color(color: str) -> str:
    """Get background color classes for buttons."""
    return {
        "blue": "bg-borrowd-indigo-300 hover:bg-borrowd-indigo-600",
        "green": "bg-borrowd-fern-300 hover:bg-borrowd-fern-600",
        "red": "bg-borrowd-plum-300 hover:bg-borrowd-plum-600",
        "yellow": "bg-borrowd-honey-300 hover:bg-borrowd-honey-600",
        "gray": "bg-gray-600 hover:bg-gray-700",  # Keep gray as standard since no borrowd equivalent
    }.get(color, "bg-borrowd-indigo-300 hover:bg-borrowd-indigo-600")


@register.filter
def button_text_color(color: str) -> str:
    """Get text color classes for buttons."""
    # Note: reverse of button_bg_color above
    return {
        "blue": "text-borrowd-indigo-600 hover:text-borrowd-indigo-300",
        "green": "text-borrowd-fern-600 hover:text-borrowd-fern-300",
        "red": "text-borrowd-plum-600 hover:text-borrowd-plum-300",
        "yellow": "text-borrowd-honey-600 hover:text-borrowd-honey-300",
        "gray": "text-white",
    }.get(color, "text-white")


@register.filter
def button_border_color(color: str) -> str:
    """Get border color classes for outlined buttons."""
    # Note: looks weird to inverse on hover so keeping it consistent with darker text color
    return {
        "blue": "border-borrowd-indigo-600",
        "green": "border-borrowd-fern-600",
        "red": "border-borrowd-plum-600",
        "yellow": "border-borrowd-honey-600",
        "gray": "border-gray-600",
    }.get(color, "border-borrowd-indigo-600")
