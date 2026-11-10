from typing import Any

from django.http import HttpRequest

from borrowd_users.request import get_authenticated_user

from .models import CommunityRequest


def community_request_count(request: HttpRequest) -> dict[str, Any]:
    """
    Adds the count of community requests that are new to the user for the
    nav badge -- see `CommunityRequestQuerySet.menu_badge_for`.
    """
    if not request.user.is_authenticated:
        return {}

    user = get_authenticated_user(request)
    count = CommunityRequest.objects.menu_badge_for(user).count()
    return {"community_request_count": count}
