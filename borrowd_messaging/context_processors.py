from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

from borrowd_users.request import get_authenticated_user

from .read_state import unread_threads_for


def messaging_enabled(request: HttpRequest) -> dict[str, Any]:
    """Expose the feature flag and count unread threads only if a template needs it."""
    context: dict[str, Any] = {"messaging_enabled": settings.MESSAGING_ENABLED}
    if settings.MESSAGING_ENABLED and request.user.is_authenticated:
        viewer = get_authenticated_user(request)
        # A plain int wrapped in SimpleLazyObject fails the `pluralize` filter:
        # it calls float(value), which SimpleLazyObject doesn't support, so the
        # label is derived here instead and shares the same cached count.
        count = SimpleLazyObject(lambda: unread_threads_for(viewer).count())
        context["unread_conversation_count"] = count
        context["unread_conversation_label"] = SimpleLazyObject(
            lambda: "conversation" if count == 1 else "conversations"
        )
    return context
