from functools import cache
from typing import Any

from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

from borrowd_users.request import get_authenticated_user

from .group_actions import group_action_count, memberships_in_groups_without_moderator


def groups_needing_moderator(
    request: HttpRequest,
) -> dict[str, Any]:
    """
    Adds a flag indicating whether the user belongs to a group that
    currently has no moderator, and the count of group actions waiting
    on the user for the Groups nav badge.

    Both are lazy, so pages that render neither run no queries, and they
    share one count of the user's groups without a moderator.
    """
    if not request.user.is_authenticated:
        return {}

    user = get_authenticated_user(request)

    @cache
    def groups_without_moderator() -> int:
        return memberships_in_groups_without_moderator(user).count()

    return {
        "has_groups_needing_moderator": SimpleLazyObject(
            lambda: groups_without_moderator() > 0
        ),
        "group_action_count": SimpleLazyObject(
            lambda: group_action_count(
                user, groups_without_moderator=groups_without_moderator()
            )
        ),
    }
