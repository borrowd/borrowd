from typing import Any

from django.http import HttpRequest

from borrowd_groups.models import Membership, MembershipStatus


def groups_needing_moderator(
    request: HttpRequest,
) -> dict[str, Any]:
    """
    Adds a flag indicating whether the user belongs to a group
    that currently has no moderator.
    """
    if not request.user.is_authenticated:
        return {}

    memberships = Membership.objects.filter(
        user=request.user,
        status=MembershipStatus.ACTIVE,
        is_moderator=False,
    ).select_related("group")

    has_groups_needing_moderator = any(
        membership.group.needs_moderator for membership in memberships
    )

    return {"has_groups_needing_moderator": has_groups_needing_moderator}
