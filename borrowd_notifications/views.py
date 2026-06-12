from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from borrowd_users.models import BorrowdUser

from .models import ChannelType, NotificationPreference, NotificationType

# Categories shown on the settings page, in display order.
# Each entry is (NotificationType, human-readable label).
NOTIFICATION_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "Lending Lifecycle",
        "slug": "lending",
        "types": [
            (NotificationType.ITEM_REQUESTED, "Borrow request received"),
            (NotificationType.ITEM_REQUEST_ACCEPTED, "Request accepted"),
            (NotificationType.ITEM_REQUEST_DENIED, "Request declined"),
            (NotificationType.COLLECTION_ASSERTED, "Borrower says they've collected"),
            (NotificationType.COLLECTION_CONFIRMED, "Collection confirmed"),
            (NotificationType.RETURN_ASSERTED, "Borrower says they've returned"),
            (NotificationType.RETURN_CONFIRMED, "Return confirmed"),
        ],
    },
    {
        "name": "Group & Membership",
        "slug": "membership",
        "types": [
            (NotificationType.MEMBERSHIP_PENDING, "New member join request"),
            (NotificationType.MEMBERSHIP_APPROVED, "Membership approved"),
        ],
    },
    {
        "name": "Wishlist & Community",
        "slug": "wishlist",
        "types": [
            (
                NotificationType.COMMUNITY_REQUEST_POSTED,
                "Community item request posted",
            ),
            (
                NotificationType.COMMUNITY_REQUEST_FULFILLED,
                "Community request fulfilled",
            ),
        ],
    },
    {
        "name": "Item Availability",
        "slug": "availability",
        "types": [
            (NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE, "Item now available"),
        ],
    },
]


def _optional_types_for_scope(scope: str) -> list[NotificationType]:
    mandatory = NotificationType.mandatory_types()
    if scope == "master":
        return [
            ntype
            for cat in NOTIFICATION_CATEGORIES
            for ntype, _ in cat["types"]
            if ntype not in mandatory
        ]
    for cat in NOTIFICATION_CATEGORIES:
        if cat["slug"] == scope:
            return [ntype for ntype, _ in cat["types"] if ntype not in mandatory]
    return []


_CHANNEL_FIELD: dict[ChannelType, str] = {
    ChannelType.APP: "in_app_enabled",
    ChannelType.EMAIL: "email_enabled",
    ChannelType.PUSH: "push_enabled",
}


def _build_preferences_context(user: BorrowdUser) -> dict[str, Any]:
    mandatory = NotificationType.mandatory_types()
    prefs: dict[str, NotificationPreference] = {
        p.notification_type: p for p in NotificationPreference.objects.filter(user=user)
    }

    categories = []
    all_optional_app = True
    all_optional_email = True

    for cat in NOTIFICATION_CATEGORIES:
        cat_optional_app = True
        cat_optional_email = True
        types_ctx = []

        for ntype, label in cat["types"]:
            is_mandatory = ntype in mandatory
            pref = prefs.get(ntype.value)
            app_on = is_mandatory or (pref is not None and pref.in_app_enabled)
            email_on = is_mandatory or (pref is not None and pref.email_enabled)

            if not is_mandatory:
                if not app_on:
                    cat_optional_app = False
                    all_optional_app = False
                if not email_on:
                    cat_optional_email = False
                    all_optional_email = False

            types_ctx.append(
                {
                    "type_value": ntype.value,
                    "label": label,
                    "is_mandatory": is_mandatory,
                    "app_enabled": app_on,
                    "email_enabled": email_on,
                }
            )

        categories.append(
            {
                "name": cat["name"],
                "slug": cat["slug"],
                "types": types_ctx,
                "all_optional_app_enabled": cat_optional_app,
                "all_optional_email_enabled": cat_optional_email,
            }
        )

    return {
        "categories": categories,
        "master_app_enabled": all_optional_app,
        "master_email_enabled": all_optional_email,
    }


@login_required
def notification_preferences_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    context = _build_preferences_context(user)
    return render(request, "notifications/preferences.html", context)


@login_required
@require_POST
def toggle_preference(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    type_value = request.POST.get("notification_type", "")
    channel_value = request.POST.get("channel", "")
    enabled = request.POST.get("enabled") == "true"

    try:
        ntype = NotificationType(type_value)
        ChannelType(channel_value)
    except ValueError:
        return HttpResponse(status=400)

    if ntype in NotificationType.mandatory_types():
        return HttpResponse(status=403)

    channel = ChannelType(channel_value)
    field_name = _CHANNEL_FIELD[channel]
    obj, _ = NotificationPreference.objects.get_or_create(
        user=user,
        notification_type=type_value,
        defaults={"in_app_enabled": True, "email_enabled": True, "push_enabled": False},
    )
    setattr(obj, field_name, enabled)
    obj.save(update_fields=[field_name])

    return HttpResponse(status=204)


@login_required
@require_POST
def bulk_toggle_preferences(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    scope = request.POST.get("scope", "")
    channel_value = request.POST.get("channel", "")
    enabled = request.POST.get("enabled") == "true"

    try:
        channel = ChannelType(channel_value)
    except ValueError:
        return HttpResponse(status=400)

    types_to_update = _optional_types_for_scope(scope)
    if not types_to_update:
        return HttpResponse(status=400)

    field_name = _CHANNEL_FIELD[channel]
    NotificationPreference.objects.filter(
        user=user,
        notification_type__in=[t.value for t in types_to_update],
    ).update(**{field_name: enabled})

    return HttpResponse(status=204)
