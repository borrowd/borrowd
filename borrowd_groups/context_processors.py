from typing import Any

from django.db.models import Exists, OuterRef
from django.http import HttpRequest

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_users.request import get_authenticated_user


def groups_needing_moderator(
    request: HttpRequest,
) -> dict[str, Any]:
    """
    Adds a flag indicating whether the user belongs to a group
    that currently has no moderator.
    """
    if not request.user.is_authenticated:
        return {}

    active_moderator_memberships = Membership.objects.filter(
        group_id=OuterRef("group_id"),
        status=MembershipStatus.ACTIVE,
        is_moderator=True,
    )

    has_groups_needing_moderator = (
        Membership.objects.filter(
            user=get_authenticated_user(request),
            status=MembershipStatus.ACTIVE,
            is_moderator=False,
        )
        .annotate(has_active_moderator=Exists(active_moderator_memberships))
        .filter(has_active_moderator=False)
        .exists()
    )

    return {"has_groups_needing_moderator": has_groups_needing_moderator}
