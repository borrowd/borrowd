from typing import Any

from django.http import HttpRequest

from borrowd_groups.models import Membership


def groups_needing_moderator(request: HttpRequest) -> dict[str, Any]:
    """
    Adds a flag to templates indicating whether the current user
    is part of any group that needs a moderator.
    """
    if not request.user.is_authenticated:
        return {}

    has_groups_needing_moderator = Membership.objects.filter(
        user=request.user,
        status="ACTIVE",
        group__needs_moderator=True,
        is_moderator=False,
    ).exists()

    return {"has_groups_needing_moderator": has_groups_needing_moderator}
