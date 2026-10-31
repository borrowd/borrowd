from typing import Any

from django.http import HttpRequest

from borrowd_users.request import get_authenticated_user

from .group_actions import group_action_count, memberships_in_groups_without_moderator


def groups_needing_moderator(
    request: HttpRequest,
) -> dict[str, Any]:
    """
    Adds a flag indicating whether the user belongs to a group that
    currently has no moderator, and the count of group actions waiting
    on the user for the Groups nav badge.
    """
    if not request.user.is_authenticated:
        return {}

    user = get_authenticated_user(request)
    return {
        "has_groups_needing_moderator": memberships_in_groups_without_moderator(
            user
        ).exists(),
        "group_action_count": group_action_count(user),
    }
