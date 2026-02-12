"""
Helper functions for building item card context and related utilities.

These functions support the HTMX-driven item card rendering used throughout
the application, providing consistent context building for item cards.
"""

from typing import TYPE_CHECKING, Any

from django.utils.html import format_html

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

    from .models import Item, ItemActionContext


# Banner styling configuration
BANNER_ICONS = {
    "request": '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
    "available": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"/></svg>',
    "reserved": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z" clip-rule="evenodd"/></svg>',
}

BANNER_STYLES = {
    "request": {"bg": "bg-borrowd-plum-300", "text": "text-borrowd-plum-600"},
    "available": {"bg": "bg-borrowd-fern-300", "text": "text-borrowd-fern-600"},
    "reserved": {"bg": "bg-borrowd-honey-300", "text": "text-borrowd-honey-600"},
}


def parse_card_target(hx_target: str) -> tuple[bool, str]:
    """
    Parse HX-Target header to determine if request is from an item card.

    Args:
        hx_target: The HX-Target header value (e.g., "item-card-search-123")

    Returns:
        Tuple of (is_card_request, card_context).
        card_context is the section identifier (e.g., "search", "my-items").

    Examples:
        >>> parse_card_target("item-card-search-123")
        (True, 'search')
        >>> parse_card_target("item-card-my-items-456")
        (True, 'my-items')
        >>> parse_card_target("some-other-target")
        (False, '')
    """
    is_card_request = hx_target.startswith("item-card-")
    card_context = ""
    if is_card_request:
        # Split "item-card-search-123" -> ["item", "card", "search", "123"]
        parts = hx_target.split("-")
        if len(parts) >= 4:
            # Context is everything between "card" and the pk (last element)
            card_context = "-".join(parts[2:-1])
    return is_card_request, card_context


def build_card_ids(context: str, pk: int) -> dict[str, str]:
    """
    Generate pre-computed IDs for item card template.

    These IDs are needed because Django template filters don't work
    reliably inside {% include %} tags.

    Args:
        context: The card context/section (e.g., "search", "my-items")
        pk: The item's primary key

    Returns:
        Dict with card_id, modal_suffix, actions_container_id,
        card_id_selector, request_modal_id, accept_modal_id.

    Example:
        >>> build_card_ids("search", 123)
        {
            'card_id': 'item-card-search-123',
            'modal_suffix': '-search-123',
            'actions_container_id': 'item-card-actions-search-123',
            'card_id_selector': '#item-card-search-123',
            'request_modal_id': 'request-item-modal-search-123',
            'accept_modal_id': 'accept-request-modal-search-123',
        }
    """
    return {
        "card_id": f"item-card-{context}-{pk}",
        "modal_suffix": f"-{context}-{pk}",
        "actions_container_id": f"item-card-actions-{context}-{pk}",
        "card_id_selector": f"#item-card-{context}-{pk}",
        "request_modal_id": f"request-item-modal-{context}-{pk}",
        "accept_modal_id": f"accept-request-modal-{context}-{pk}",
    }


def get_banner_info_for_item(
    item: "Item", viewing_user: "BorrowdUser"
) -> dict[str, Any]:
    """
    Get banner type and request info, checking for pending requests.

    Determines the appropriate banner to display for an item card based on:
    1. Whether there's a pending request transaction
    2. The item's current status (available, reserved, borrowed)

    Args:
        item: The Item to get banner info for
        viewing_user: The user viewing the card (for "me" substitution)

    Returns:
        Dict with banner_type (str), and optionally requester_name and time_ago
        if there's a pending request.

    Examples:
        - Item with pending request from viewing_user:
          {'banner_type': 'request', 'requester_name': 'me', 'time_ago': '2 hours'}
        - Item with pending request from another user:
          {'banner_type': 'request', 'requester_name': 'John Doe', 'time_ago': '1 day'}
        - Available item:
          {'banner_type': 'available'}
    """
    from django.utils.timesince import timesince

    from .models import ItemStatus, TransactionStatus

    # Check for pending request using item's method
    requesting_user = item.get_requesting_user()
    if requesting_user:
        # There's a pending request - show request banner
        if requesting_user == viewing_user:
            requester_name = "me"
        else:
            requester_name = requesting_user.profile.full_name()

        # Get transaction for timestamp
        pending_tx = item.transactions.filter(
            status=TransactionStatus.REQUESTED
        ).first()
        time_ago = timesince(pending_tx.created_at).split(",")[0] if pending_tx else ""

        return {
            "banner_type": "request",
            "requester_name": requester_name,
            "time_ago": time_ago,
        }

    # Fall back to item status
    status_to_banner: dict[int, str] = {
        ItemStatus.AVAILABLE: "available",
        ItemStatus.RESERVED: "reserved",
        ItemStatus.BORROWED: "reserved",
    }
    return {"banner_type": status_to_banner.get(item.status, "")}


def build_item_card_context(
    item: "Item",
    user: "BorrowdUser",
    context: str,
    action_context: "ItemActionContext | None" = None,
    error_message: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    """
    Build the full template context for rendering an item card.

    This is the main entry point for building card context, combining
    banner info, card IDs, and item data into a single context dict.

    Args:
        item: The Item to render
        user: The viewing user (for permissions and "me" substitution)
        context: The card context/section (e.g., "search", "my-items")
        action_context: Pre-computed action context, or None to compute it
        error_message: Optional error message to display
        error_type: Optional error type (e.g., "already_requested")

    Returns:
        Dict with all context variables needed by item_card.html template.
    """
    if action_context is None:
        action_context = item.get_action_context_for(user=user)

    first_photo = item.photos.first()
    banner_info = get_banner_info_for_item(item, user)
    card_ids = build_card_ids(context, item.pk)

    # Get banner styling
    banner_type = banner_info.get("banner_type", "")
    banner_style = BANNER_STYLES.get(banner_type, {})
    # format_html necessary to display svg, otherwise it just gets shown as plaintext
    # https://docs.djangoproject.com/en/6.0/ref/utils/#django.utils.html.format_html
    banner_icon = format_html(BANNER_ICONS.get(banner_type, ""))

    ctx: dict[str, Any] = {
        "item": item,
        "action_context": action_context,
        "pk": item.pk,
        "context": context,
        "name": item.name,
        "description": item.description,
        "image": first_photo.thumbnail.url if first_photo else "",
        "is_yours": item.owner == user,
        "banner_type": banner_type,
        "banner_bg": banner_style.get("bg", ""),
        "banner_text": banner_style.get("text", ""),
        "banner_icon": banner_icon,
        "requester_name": banner_info.get("requester_name", ""),
        "time_ago": banner_info.get("time_ago", ""),
        "show_actions": True,
        **card_ids,
    }

    if error_message:
        ctx["error_message"] = error_message
        ctx["error_type"] = error_type

    return ctx


def build_item_cards_for_items(
    items: list["Item"], user: "BorrowdUser", context: str
) -> list[dict[str, Any]]:
    """
    Build card contexts for a list of items.

    Args:
        items: List of Item objects to render
        user: The viewing user
        context: The card context/section (e.g., "search", "my-items")

    Returns:
        List of context dicts for item_card.html template.
    """
    return [build_item_card_context(item, user, context) for item in items]


def build_item_cards_for_transactions(
    transactions: list[Any], user: "BorrowdUser", context: str
) -> list[dict[str, Any]]:
    """
    Build card contexts for a list of transactions.

    Extracts the item from each transaction and builds card context,
    using transaction metadata for banner info.

    Args:
        transactions: List of Transaction objects
        user: The viewing user
        context: The card context/section (e.g., "my-requests")

    Returns:
        List of context dicts for item_card.html template.
    """
    from django.utils.timesince import timesince

    from .models import TransactionStatus

    cards = []
    for tx in transactions:
        item = tx.item
        action_context = item.get_action_context_for(user=user)

        # Get banner type from transaction status
        status_to_banner: dict[int, str] = {
            TransactionStatus.REQUESTED: "request",
            TransactionStatus.ACCEPTED: "reserved",
            TransactionStatus.COLLECTION_ASSERTED: "reserved",
            TransactionStatus.COLLECTED: "reserved",
            TransactionStatus.RETURN_ASSERTED: "reserved",
        }
        banner_type = status_to_banner.get(tx.status, "")

        # Get requester info
        requester_name = tx.party2.profile.full_name()
        time_ago = timesince(tx.created_at).split(",")[0]

        first_photo = item.photos.first()
        card_ids = build_card_ids(context, item.pk)

        # Get banner styling
        banner_style = BANNER_STYLES.get(banner_type, {})
        # format_html necessary to display svg, otherwise it just gets shown as plaintext
        # https://docs.djangoproject.com/en/6.0/ref/utils/#django.utils.html.format_html
        banner_icon = format_html(BANNER_ICONS.get(banner_type, ""))

        ctx: dict[str, Any] = {
            "item": item,
            "action_context": action_context,
            "pk": item.pk,
            "context": context,
            "name": item.name,
            "description": item.description,
            "image": first_photo.thumbnail.url if first_photo else "",
            "is_yours": item.owner == user,
            "banner_type": banner_type,
            "banner_bg": banner_style.get("bg", ""),
            "banner_text": banner_style.get("text", ""),
            "banner_icon": banner_icon,
            "requester_name": requester_name,
            "time_ago": f"{time_ago} ago",
            "show_actions": True,
            **card_ids,
        }
        cards.append(ctx)

    return cards
