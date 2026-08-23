from typing import Any

from django.conf import settings
from django.http import HttpRequest


def messaging_enabled(request: HttpRequest) -> dict[str, Any]:
    """
    Lets the sidebar hide its Messages link while the feature is off
    """
    return {"messaging_enabled": settings.MESSAGING_ENABLED}
