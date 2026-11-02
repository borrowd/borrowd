from typing import Any

from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

from borrowd_users.request import get_authenticated_user

from .group_actions import group_action_count


def groups_needing_moderator(
    request: HttpRequest,
) -> dict[str, Any]:
    """
    Adds the count of group actions waiting on the user for the Groups nav
    badge, including each of the user's groups that has no moderator.

    The count is lazy, so pages that don't render it run no queries.
    """
    if not request.user.is_authenticated:
        return {}

    user = get_authenticated_user(request)

    return {
        "group_action_count": SimpleLazyObject(lambda: group_action_count(user)),
    }
