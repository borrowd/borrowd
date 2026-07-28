from collections.abc import Iterable
from datetime import timedelta
from string import Formatter
from typing import Any, TypedDict

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.prefetch import GenericPrefetch
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from notifications.models import Notification

from borrowd.util import is_safe_back_url
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user

from .models import (
    ChannelType,
    NotificationMetadata,
    NotificationPreference,
    NotificationType,
)

# Categories shown on the settings page, in display order.
# Each entry is (NotificationType, human-readable label).
NOTIFICATION_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "Lending Lifecycle",
        "slug": "lending",
        "icon": "arrows-right-left",
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
            (NotificationType.ITEM_RETURN_REQUESTED, "Item return requested"),
            (NotificationType.ITEM_DISPUTED, "Item disputed"),
        ],
    },
    {
        "name": "Group & Membership",
        "slug": "membership",
        "icon": "user-group",
        "types": [
            (
                NotificationType.GROUP_MEMBER_JOINED,
                "A member joined a group you're part of",
            ),
            (NotificationType.GROUP_NEEDS_MODERATOR, "Group needs moderator"),
            (NotificationType.MEMBERSHIP_PENDING, "New member join request"),
            (NotificationType.MEMBERSHIP_APPROVED, "Membership approved"),
        ],
    },
    {
        "name": "Item Availability",
        "slug": "availability",
        "icon": "bell-alert",
        "types": [
            (NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE, "Item now available"),
            (NotificationType.ITEM_SUBSCRIPTION, "Item subscription"),
        ],
    },
    {
        "name": "Ownership Transfer",
        "slug": "giveaway",
        "icon": "gift",
        "types": [
            (NotificationType.GIVEAWAY_OFFER_SENT, "Giveaway offer received"),
            (NotificationType.GIVEAWAY_ACCEPTED, "Giveaway accepted"),
            (NotificationType.GIVEAWAY_DECLINED, "Giveaway declined"),
            (
                NotificationType.GIVEAWAY_REQUEST_RECEIVED,
                "Giveaway request received",
            ),
            (
                NotificationType.GIVEAWAY_REQUEST_APPROVED,
                "Giveaway request approved",
            ),
            (
                NotificationType.GIVEAWAY_REQUEST_DECLINED,
                "Giveaway request declined",
            ),
            (NotificationType.GIVEAWAY_COMPLETED, "Giveaway completed"),
        ],
    },
]


def _optional_types_for_scope(scope: str) -> list[NotificationType]:
    """Returns the non-mandatory notification types in scope (a category
    slug, or "master" for every category) — the ones a user can actually
    toggle off for the app/email channels.
    """
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
    """Returns every notification type in scope, including mandatory ones.

    Used for the push channel: unlike app/email, push has no mandatory-type
    carve-out, so bulk push toggles must cover the full category rather
    than just the optional types.
    """
    if scope == "master":
        return [ntype for cat in NOTIFICATION_CATEGORIES for ntype, _ in cat["types"]]
    for cat in NOTIFICATION_CATEGORIES:
        if cat["slug"] == scope:
            return [ntype for ntype, _ in cat["types"]]
    return []


def _build_preferences_context(user: BorrowdUser) -> dict[str, Any]:
    """Builds the template context for the notification preferences page:
    per-category, per-channel toggle state for every notification type,
    plus a flat `prefs_json` blob the page's JS reads to drive the
    category-level "select all" switches.
    """
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
    """Renders the notification preferences page."""
    user = get_authenticated_user(request)
    context = _build_preferences_context(user)
    context["vapid_public_key"] = settings.VAPID_PUBLIC_KEY
    return render(request, "notifications/preferences.html", context)


@login_required
@require_POST
def toggle_preference(request: HttpRequest) -> HttpResponse:
    """Toggles a single (notification_type, channel) preference on/off for
    the current user. Rejects disabling a mandatory type on a non-push
    channel — those must always stay on.
    """
    user = get_authenticated_user(request)
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
        and ChannelType(channel_value) != ChannelType.PUSH
    ):
        return HttpResponse(status=403)

    field_name = str(ChannelType(channel_value).label)
    obj, _ = NotificationPreference.objects.get_or_create(
        user=user,
        notification_type=type_value,
        defaults={
            "in_app_enabled": False,
            "email_enabled": False,
            "push_enabled": False,
        },
    )
    setattr(obj, field_name, enabled)
    obj.save(update_fields=[field_name])

    return HttpResponse(status=204)


@login_required
@require_POST
def bulk_toggle_preferences(request: HttpRequest) -> HttpResponse:
    """Toggles every applicable type in a scope (a category slug, or
    "master" for all categories) for one channel at once — backs the
    preferences page's category-level and global "select all" switches.
    """
    user = get_authenticated_user(request)
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

    field_name = str(channel.label)

    for ntype in types_to_update:
        NotificationPreference.objects.update_or_create(
            user=user,
            notification_type=ntype.value,
            defaults={field_name: enabled},
        )

    return HttpResponse(status=204)


# ── Inbox ──────────────────────────────────────────────────────────────────

_INBOX_PAGE_SIZE = 25
_RELATIVE_TIMESTAMP_MAX_AGE = timedelta(days=7)


class NotificationMessagePart(TypedDict):
    text: str
    is_emphasized: bool


def app_channel_qs(qs: QuerySet[Notification]) -> QuerySet[Notification]:
    """Filter to notifications currently visible in the in-app inbox.

    Also prefetches action_object (a GenericForeignKey, so a plain
    select_related/prefetch_related can't cover it): every notify.send()
    call sets it to an Item, Membership, or BorrowdGroup (see signals.py), and
    display helpers read it for every row on the page, so
    without this each row costs its own query.
    """
    return qs.filter(borrowd_metadata__visible_in_app=True).prefetch_related(
        GenericPrefetch(
            "action_object",
            [
                Item.objects.prefetch_related("photos"),
                Membership.objects.select_related("group", "user__profile"),
                BorrowdGroup.objects.all(),
            ],
        )
    )


def _notification_message_template_and_context(
    notification: Notification,
) -> tuple[str, dict[str, Any]]:
    """Looks up the message template registered for a notification's verb
    (NotificationType.message_template) and the interpolation context
    stored on the notification by the notify.send() call that created it.
    """
    try:
        template = NotificationType(notification.verb).message_template
    except ValueError:
        return str(notification.verb), {}

    context: dict[str, Any] = {}
    if isinstance(notification.data, dict):
        raw_context = notification.data.get("context", {})
        if isinstance(raw_context, dict):
            context = {str(key): value for key, value in raw_context.items()}
    return template, context


def _notification_message_parts(
    template: str, context: dict[str, Any], fallback_text: str
) -> list[NotificationMessagePart]:
    """Splits a message template into literal and interpolated parts so the
    notification card can render the interpolated values (e.g. an item
    name) in bold. Falls back to `fallback_text` as a single plain part if
    the template or context is malformed.
    """
    formatter = Formatter()
    parts: list[NotificationMessagePart] = []

    try:
        parsed_template = list(formatter.parse(template))
    except ValueError:
        return [{"text": fallback_text, "is_emphasized": False}]

    for literal_text, field_name, format_spec, _conversion in parsed_template:
        if literal_text:
            parts.append({"text": literal_text, "is_emphasized": False})

        if field_name is None:
            continue

        if field_name not in context:
            return [{"text": fallback_text, "is_emphasized": False}]

        try:
            text = formatter.format_field(context[field_name], format_spec or "")
        except (KeyError, ValueError, TypeError):
            return [{"text": fallback_text, "is_emphasized": False}]

        parts.append({"text": text, "is_emphasized": True})

    return parts or [{"text": fallback_text, "is_emphasized": False}]


def _get_notification_category(
    notification_type: NotificationType,
) -> tuple[str | None, str | None]:
    """Finds the NOTIFICATION_CATEGORIES entry a notification type belongs
    to, returning its display title and category dict, or None if the
    type isn't registered in any category.
    """
    for cat in NOTIFICATION_CATEGORIES:
        for ntype, title in cat["types"]:
            if ntype == notification_type:
                try:
                    return (str(title), str(cat["slug"]))
                except ValueError:
                    return (None, None)
    return (None, None)


def _get_category_icon(slug: str | None) -> str | None:
    """Returns the heroicon name (see `templates/notifications/preferences.html`
    and `{% heroicon_outline %}`) for a NOTIFICATION_CATEGORIES slug, or
    None if no category has that slug.
    """

    if not slug:
        return None

    for cat in NOTIFICATION_CATEGORIES:
        if cat["slug"] == slug:
            return str(cat["icon"])
    return None


def _notification_action_object(
    notification: Notification,
) -> Item | Membership | BorrowdGroup | None:
    action_object = notification.action_object
    if isinstance(action_object, (Item, Membership, BorrowdGroup)):
        return action_object
    return None


def _notification_action_url(notification: Notification) -> str | None:
    """Resolves where clicking a notification should land, based on the
    action_object set by notify.send() calls across the app (see signals.py
    in this app, borrowd_groups, and borrowd_users/services.py): an Item
    goes to its detail page, a Membership or BorrowdGroup to the group's
    detail page.
    """
    action_object = _notification_action_object(notification)
    if isinstance(action_object, Item):
        # A soft-deleted item's detail page 404s (ItemDetailView uses the
        # default active-only manager). item_card.html already treats
        # `is_removed` items as non-clickable elsewhere in the app
        # (pointer-events-none); match that instead of linking to a dead page.
        if action_object.deleted_at is not None:
            return None
        return reverse("item-detail", kwargs={"pk": action_object.pk})
    if isinstance(action_object, Membership):
        group = action_object.group
        # Same soft-delete guard as above, one hop out via the membership.
        if group.deleted_at is not None:
            return None
        return reverse("borrowd_groups:group-detail", kwargs={"pk": group.pk})
    if isinstance(action_object, BorrowdGroup):
        if action_object.deleted_at is not None:
            return None
        return reverse("borrowd_groups:group-detail", kwargs={"pk": action_object.pk})
    return None


def _image_url(image: Any) -> str | None:
    if not image:
        return None
    try:
        return str(image.url)
    except (FileNotFoundError, ValueError):
        return None


def _item_avatar_url(item: Item) -> str | None:
    first_photo = item.photos.first()
    if first_photo is None:
        return None
    return _image_url(first_photo.thumbnail)


def _group_avatar_url(group: BorrowdGroup) -> str | None:
    return _image_url(group.banner or group.logo)


def _membership_avatar_url(
    notification: Notification, membership: Membership
) -> str | None:
    if notification.verb in {
        NotificationType.GROUP_MEMBER_JOINED.value,
        NotificationType.MEMBERSHIP_PENDING.value,
    }:
        return _image_url(membership.user.profile.image)
    return _group_avatar_url(membership.group)


def _notification_avatar_content(notification: Notification) -> str | None:
    """Resolves the image URL shown in a notification card."""
    action_object = _notification_action_object(notification)
    if isinstance(action_object, Item):
        return _item_avatar_url(action_object)
    if isinstance(action_object, Membership):
        return _membership_avatar_url(notification, action_object)
    if isinstance(action_object, BorrowdGroup):
        return _group_avatar_url(action_object)
    return None


def _annotate_for_display(notifications: Iterable[Notification]) -> None:
    """Sets display-only fields (not persisted) read by the notification card partial."""
    relative_timestamp_cutoff = timezone.now() - _RELATIVE_TIMESTAMP_MAX_AGE
    for notification in notifications:
        message_template, message_context = _notification_message_template_and_context(
            notification
        )
        notification.message_template = message_template
        notification.message_context = message_context
        notification.message_parts = _notification_message_parts(
            message_template, message_context, str(notification.verb)
        )

        notification_type: NotificationType | None = None
        try:
            notification_type = NotificationType(notification.verb)
        except ValueError:
            pass

        notification_title, category = (None, None)
        if notification_type is not None:
            notification_title, category = _get_notification_category(notification_type)

        notification.title = (
            notification_title if notification_title else "Notification"
        )
        notification.category = category if category else "borrowd"

        notification.show_absolute_timestamp = (
            notification.timestamp <= relative_timestamp_cutoff
        )
        notification.action_url = _notification_action_url(notification)
        notification.avatar_content = _notification_avatar_content(notification)
        notification.category_icon = _get_category_icon(category)


@login_required
def notification_inbox_view(request: HttpRequest) -> HttpResponse:
    """Renders the paginated in-app notification inbox for the current user."""
    user = get_authenticated_user(request)

    # only show the notifications that where sent through the in-app channel
    # notifications is untyped (see mypy.ini): user.notifications is invisible to mypy.
    qs: QuerySet[Notification] = app_channel_qs(user.notifications.all())  # type: ignore[attr-defined]
    paginator = Paginator(qs, _INBOX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    _annotate_for_display(page_obj)

    # unread_notification_count comes from the unread_notification_count context
    # processor (borrowd_notifications/context_processors.py), which every
    # authenticated page already computes for the header bell — no need to
    # run the same count query again here.
    return render(
        request,
        "notifications/inbox.html",
        {"page_obj": page_obj},
    )


def _redirect_to_caller(request: HttpRequest) -> HttpResponse:
    """Sends the user back to wherever they submitted the form from (the
    inbox page or the header's notification popup), rather than always
    landing on the inbox.
    """
    fallback_url = reverse("notification-inbox")
    referer = request.META.get("HTTP_REFERER", "")
    if referer and is_safe_back_url(referer, request):
        return redirect(referer)
    return redirect(fallback_url)


@login_required
@require_POST
def mark_notification_read(request: HttpRequest, pk: int) -> HttpResponse:
    """Marks a notification as read. For htmx requests, returns the
    updated card partial so it can be swapped in place; otherwise redirects
    back to wherever the form was submitted from.
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
        borrowd_metadata__visible_in_app=True,
    )
    notification.mark_as_read()
    if request.headers.get("HX-Request") == "true":
        _annotate_for_display([notification])
        return render(
            request,
            "notifications/_notification_card.html",
            {"notification": notification},
        )
    return _redirect_to_caller(request)


@login_required
@require_POST
def open_notification(request: HttpRequest, pk: int) -> HttpResponse:
    """Marks a notification read and sends the user to the page it's about
    (see _notification_action_url); falls back to the inbox if it has
    nothing to link to.

    POST rather than GET: marking read is a state change, and a bare GET
    link has no CSRF protection, so any cross-site request (an <img> tag,
    a prefetched link) could silently mark a guessed notification pk as
    read. A form matches the other per-notification actions in this card.
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
        borrowd_metadata__visible_in_app=True,
    )
    notification.mark_as_read()
    action_url = _notification_action_url(notification)
    return redirect(action_url or reverse("notification-inbox"))


@login_required
@require_POST
def mark_all_notifications_read(request: HttpRequest) -> HttpResponse:
    user = get_authenticated_user(request)
    # notifications is untyped (see mypy.ini): user.notifications is invisible to mypy.
    app_channel_qs(user.notifications.all()).update(unread=False)  # type: ignore[attr-defined]
    return _redirect_to_caller(request)


def delete_app_notification(notification: Notification) -> None:
    """Hides a notification from the in-app inbox by flipping its metadata's
    `visible_in_app` off, without touching its email/push delivery history.
    Also clears `unread` so it stops counting toward the header badge.
    """
    if NotificationMetadata.objects.filter(
        notification=notification,
        visible_in_app=True,
    ).update(visible_in_app=False):
        notification.unread = False
        notification.save(update_fields=["unread"])


@login_required
@require_POST
def remove_app_notification(request: HttpRequest, pk: int) -> HttpResponse:
    """Removes a single notification from the in-app inbox. For htmx
    requests, returns an empty response so the card's outerHTML swap
    deletes it in place; otherwise redirects back to the caller.
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
        borrowd_metadata__visible_in_app=True,
    )

    delete_app_notification(notification=notification)
    if request.headers.get("HX-Request") == "true":
        return HttpResponse("")
    return _redirect_to_caller(request)


@login_required
@require_POST
def remove_all_app_notifications(request: HttpRequest) -> HttpResponse:
    """Clears the current user's entire in-app inbox: marks every visible
    notification read and hides it from the in-app channel.
    """
    user = get_authenticated_user(request)
    # notifications is untyped (see mypy.ini): user.notifications is invisible to mypy.
    visible_notifications = app_channel_qs(user.notifications.all())  # type: ignore[attr-defined]
    visible_notifications.update(unread=False)
    NotificationMetadata.objects.filter(
        notification__recipient=user,
        visible_in_app=True,
    ).update(visible_in_app=False)
    return redirect("notification-inbox")


_POPUP_NOTIFICATION_LIMIT = 10


@login_required
@require_GET
def notification_popup_view(request: HttpRequest) -> HttpResponse:
    """Renders the header bell's dropdown popup with the user's most
    recent notifications (see _POPUP_NOTIFICATION_LIMIT).
    """
    user = get_authenticated_user(request)

    # notifications is untyped (see mypy.ini): user.notifications is invisible to mypy.
    qs: QuerySet[Notification] = app_channel_qs(
        user.notifications.all()  # type: ignore[attr-defined]
    )

    notifications = qs.order_by("-timestamp")[:_POPUP_NOTIFICATION_LIMIT]

    _annotate_for_display(notifications)

    # unread_notification_count comes from the unread_notification_count context
    # processor (borrowd_notifications/context_processors.py), which every
    # authenticated page already computes for the header bell — no need to
    # run the same count query again here.
    return render(
        request,
        "notifications/popup.html",
        {"notifications": notifications},
    )


@login_required
@require_GET
def notification_bell_count(request: HttpRequest) -> HttpResponse:
    """Renders the header bell's icon/badge fragment. Polled every 30s by
    `#notification-indicator` (notification_bell.html) to keep the unread
    count fresh without a full page reload.
    """
    return render(request, "notifications/_notification_count_indicator.html")
