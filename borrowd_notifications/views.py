from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Func, TextField, Value
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from notifications.models import Notification

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
            (
                NotificationType.REQUEST_CANCELLED_BORROWER_LEFT,
                "Request cancelled - borrower left",
            ),
            (
                NotificationType.REQUEST_CANCELLED_OWNER_LEFT,
                "Request cancelled - owner left",
            ),
            (NotificationType.LOAN_ENDED_OWNER_LEFT, "Loan ended - owner left"),
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


def _all_types_for_scope(scope: str) -> list[NotificationType]:
    if scope == "master":
        return [ntype for cat in NOTIFICATION_CATEGORIES for ntype, _ in cat["types"]]
    for cat in NOTIFICATION_CATEGORIES:
        if cat["slug"] == scope:
            return [ntype for ntype, _ in cat["types"]]
    return []


def _build_preferences_context(user: BorrowdUser) -> dict[str, Any]:
    mandatory = NotificationType.mandatory_types()
    prefs: dict[str, NotificationPreference] = {
        p.notification_type: p for p in NotificationPreference.objects.filter(user=user)
    }

    categories = []

    for cat in NOTIFICATION_CATEGORIES:
        cat_optional_app = True
        cat_optional_email = True
        cat_optional_push = True

        types_ctx = []

        for ntype, label in cat["types"]:
            is_mandatory = ntype in mandatory
            pref = prefs.get(ntype.value)
            app_on = is_mandatory or (pref is not None and pref.in_app_enabled)
            email_on = is_mandatory or (pref is not None and pref.email_enabled)
            push_on = pref is not None and pref.push_enabled

            if not is_mandatory:
                if not app_on:
                    cat_optional_app = False
                if not email_on:
                    cat_optional_email = False

            # push are not mendatory
            if not push_on:
                cat_optional_push = False

            types_ctx.append(
                {
                    "type_value": ntype.value,
                    "label": label,
                    "is_mandatory": is_mandatory,
                    "app_enabled": app_on,
                    "email_enabled": email_on,
                    "push_enabled": push_on,
                }
            )

        categories.append(
            {
                "name": cat["name"],
                "slug": cat["slug"],
                "types": types_ctx,
                "all_optional_app_enabled": cat_optional_app,
                "all_optional_email_enabled": cat_optional_email,
                "all_optional_push_enabled": cat_optional_push,
            }
        )

    prefs_json: dict[str, Any] = {}
    for cat_ctx in categories:
        for type_ctx in cat_ctx["types"]:
            prefs_json[type_ctx["type_value"]] = {
                "in_app": type_ctx["app_enabled"],
                "email": type_ctx["email_enabled"],
                "push": type_ctx["push_enabled"],
                "is_mandatory": type_ctx["is_mandatory"],
                "category": cat_ctx["slug"],
            }

    return {
        "categories": categories,
        "prefs_json": prefs_json,
    }


@login_required
def notification_preferences_view(request: HttpRequest) -> HttpResponse:
    from django.conf import settings

    user: BorrowdUser = request.user  # type: ignore[assignment]
    context = _build_preferences_context(user)
    context["vapid_public_key"] = settings.VAPID_PUBLIC_KEY
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

    if (
        ntype in NotificationType.mandatory_types()
        and channel_value != ChannelType.PUSH
    ):
        return HttpResponse(status=403)

    field_name = ChannelType(channel_value).label
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

    if channel == ChannelType.PUSH:
        types_to_update = _all_types_for_scope(scope)
    else:
        types_to_update = _optional_types_for_scope(scope)
    if not types_to_update:
        return HttpResponse(status=400)

    field_name = channel.label
    NotificationPreference.objects.filter(
        user=user,
        notification_type__in=[t.value for t in types_to_update],
    ).update(**{field_name: enabled})

    return HttpResponse(status=204)


# ── Inbox ──────────────────────────────────────────────────────────────────

_INBOX_PAGE_SIZE = 25


def _format_notification(notification: Notification) -> str:
    try:
        template = NotificationType(notification.verb).message_template
    except ValueError:
        return str(notification.verb)
    context: dict[str, Any] = {}
    if isinstance(notification.data, dict):
        context = notification.data.get("context", {})
    try:
        return template.format(**context)
    except KeyError:
        return str(notification.verb)


def _notification_target_url(notification: Notification) -> str | None:
    if not isinstance(notification.data, dict):
        return None
    ctx = notification.data.get("context", {})
    return ctx.get("respond_url") or ctx.get("item_url") or ctx.get("group_url") or None


@login_required
def notification_inbox_view(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]

    # only show the notifications that where sent through the in-app channel
    qs = user.notifications.annotate(
        app_channel=Func(
            "data",
            Value("$.channels.APP"),
            function="JSON_TYPE",
            output_field=TextField(),
        )
    ).filter(app_channel__isnull=False)
    paginator = Paginator(qs, _INBOX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    for notification in page_obj:
        notification.formatted_message = _format_notification(notification)
        notification.target_url = _notification_target_url(notification)

    return render(
        request,
        "notifications/inbox.html",
        {
            "page_obj": page_obj,
            "unread_count": user.notifications.unread().count(),
        },
    )


@login_required
@require_POST
def mark_notification_read(request: HttpRequest, pk: int) -> HttpResponse:
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.mark_as_read()
    target_url = _notification_target_url(notification)
    return redirect(target_url or "notification-inbox")


@login_required
@require_POST
def mark_all_notifications_read(request: HttpRequest) -> HttpResponse:
    user: BorrowdUser = request.user  # type: ignore[assignment]
    user.notifications.mark_all_as_read()
    return redirect("notification-inbox")
