from typing import Any

from django.utils.html import format_html
from django.utils.timesince import timesince

from borrowd_items.card_helpers import BANNER_ICONS, BANNER_STYLES
from borrowd_users.models import BorrowdUser

from .models import CommunityRequest


def build_commmunity_request_card(
    request: CommunityRequest, viewing_user: BorrowdUser
) -> dict[str, Any]:
    time_ago = timesince(request.created_at).split(",")[0]
    belongs_to_viewer = viewing_user == request.requester

    banner_type = "requested"
    # The viewer's own request is tinted like the "borrowed" banner instead
    # of "requested", to set it apart from everyone else's open requests.
    banner_style = BANNER_STYLES.get(
        "borrowed" if belongs_to_viewer else banner_type, {}
    )
    banner_icon = format_html(BANNER_ICONS.get(banner_type, ""))
    person_name = (
        "you" if belongs_to_viewer else request.requester.first_name.capitalize()
    )

    card_context = {
        "banner_type": banner_type,
        "banner_bg": banner_style.get("bg", ""),
        "banner_text": banner_style.get("text", ""),
        "banner_icon": banner_icon,
        "person_name": person_name,
        "person_url": f"/profile/{request.requester.pk}/",
        "time_ago": time_ago,
    }

    return {"request": request} | card_context
