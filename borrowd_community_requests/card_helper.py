from typing import Any

from django.utils.html import format_html
from django.utils.timesince import timesince

from borrowd_items.card_helpers import BANNER_ICONS, BANNER_STYLES
from borrowd_users.models import BorrowdUser

from .models import CommunityRequest


def build_commmunity_request_card(
    request: CommunityRequest, viewing_user: BorrowdUser
) -> dict[str, Any]:
    user_whose_name_should_be_shown_in_banner = request.requester
    time_ago = timesince(request.updated_at).split(",")[0]

    banner_type = "requested"

    banner_style = BANNER_STYLES.get(banner_type, {})
    banner_icon = format_html(BANNER_ICONS.get(banner_type, ""))
    person_name = (
        "you"
        if viewing_user == request.requester
        else request.requester.first_name.capitalize()
    )
    belongs_to_viewer = viewing_user == request.requester

    card_context = {
        "banner_type": "requested",
        "banner_bg": banner_style.get("bg", ""),
        "banner_text": banner_style.get("text", ""),
        "banner_icon": banner_icon,
        "is_yours": belongs_to_viewer,
        "person_name": person_name,
        "person_url": f"/profile/{user_whose_name_should_be_shown_in_banner.pk}/",
        "time_ago": time_ago,
    }

    return {"request": request} | card_context
