from typing import Any

from django.http import HttpRequest

from borrowd_users.request import get_authenticated_user

from .models import CommunityRequest


def community_request_count(request: HttpRequest) -> dict[str, Any]:
    """
    Adds the count of open community requests the user could act on
    for the nav badge — requests visible to the user, excluding their
    own, matching the "Requests" tab on the listing page.
    """
    if not request.user.is_authenticated:
        return {}

    user = get_authenticated_user(request)
    count = CommunityRequest.objects.visible_to(user).exclude(requester=user).count()
    return {"community_request_count": count}
