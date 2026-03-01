"""
Helper functions for building item card context and related utilities.

These functions provide consistent context building for item card rendering
used throughout the application.
"""

from typing import TYPE_CHECKING, Any

from django.utils.html import format_html

from .models import ItemAction, ItemActionContext

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

    from .models import Item, Transaction


# Banner styling configuration
BANNER_ICONS = {
    "available": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"/></svg>',
    "requested": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 4.13401 4.13401 1 8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8ZM8.75 3.75C8.75 3.33579 8.41421 3 8 3C7.58579 3 7.25 3.33579 7.25 3.75V8C7.25 8.41421 7.58579 8.75 8 8.75H11.25C11.6642 8.75 12 8.41421 12 8C12 7.58579 11.6642 7.25 11.25 7.25H8.75V3.75Z" fill="#8E6900"/></svg>',
    "reserved": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z" clip-rule="evenodd"/></svg>',
    "borrowed": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 4.13401 4.13401 1 8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8ZM8.75 3.75C8.75 3.33579 8.41421 3 8 3C7.58579 3 7.25 3.33579 7.25 3.75V8C7.25 8.41421 7.58579 8.75 8 8.75H11.25C11.6642 8.75 12 8.41421 12 8C12 7.58579 11.6642 7.25 11.25 7.25H8.75V3.75Z" fill="#2C51A1"/></svg>',
}

BANNER_STYLES = {
    "available": {"bg": "bg-success/15", "text": "text-success"},
    # hardcoding the dark yellow text here because there is no themed name for
    # the color and it would change internal daisy colors (warning badge, etc)
    # if I changed the warning-content var in main.css
    # https://www.figma.com/design/wMliTL8KGBlUACk0d8fkZ3/Borrow-d---Mobile-App--mid-fidelity-?node-id=716-14698&m=dev
    "requested": {"bg": "bg-warning/15", "text": "text-[#8E6900]"},
    "reserved": {"bg": "bg-secondary/15", "text": "text-secondary"},
    "borrowed": {"bg": "bg-primary/15", "text": "text-primary"},
}


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
        request_modal_id, accept_modal_id.

    Example:
        >>> build_card_ids("search", 123)
        {
            'card_id': 'item-card-search-123',
            'modal_suffix': '-search-123',
            'actions_container_id': 'item-card-actions-search-123',
            'request_modal_id': 'request-item-modal-search-123',
            'accept_modal_id': 'accept-request-modal-search-123',
        }
    """
    return {
        "card_id": f"item-card-{context}-{pk}",
        "modal_suffix": f"-{context}-{pk}",
        "actions_container_id": f"item-card-actions-{context}-{pk}",
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

    from .models import TransactionStatus

    # Check for active transaction to determine banner state
    current_borrower = item.get_current_borrower()
    requesting_user = item.get_requesting_user()

    # Get current transaction for this item
    current_tx = None
    if current_borrower or requesting_user:
        from .models import TransactionStatus

        current_tx = item.transactions.filter(
            status__in=[
                TransactionStatus.REQUESTED,
                TransactionStatus.ACCEPTED,
                TransactionStatus.COLLECTION_ASSERTED,
                TransactionStatus.COLLECTED,
                TransactionStatus.RETURN_ASSERTED,
            ]
        ).first()

    if current_tx:
        # Determine banner based on transaction status
        if current_tx.status == TransactionStatus.REQUESTED:
            banner_type = "requested"
            person = current_tx.party2
        elif current_tx.status in [
            TransactionStatus.ACCEPTED,
            TransactionStatus.COLLECTION_ASSERTED,
        ]:
            banner_type = "reserved"
            person = current_tx.party2
        elif current_tx.status in [
            TransactionStatus.COLLECTED,
            TransactionStatus.RETURN_ASSERTED,
        ]:
            banner_type = "borrowed"
            person = current_tx.party2
        else:
            # Fallback to available
            return {"banner_type": "available"}

        # Build person display info
        if person == viewing_user:
            person_name = "me"
        else:
            person_name = person.first_name.capitalize()  # type: ignore[attr-defined]

        person_url = f"/profile/{person.pk}/"  # type: ignore[attr-defined]
        time_ago = timesince(current_tx.updated_at).split(",")[0]

        return {
            "banner_type": banner_type,
            "person_name": person_name,
            "person_url": person_url,
            "time_ago": time_ago,
        }

    # No active transaction - item is available
    return {"banner_type": "available"}


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

    # Once the request is approved, the card only shows "Confirm picked up".
    # Cancel is still accessible on the item detail page.
    if (
        ItemAction.CANCEL_REQUEST in action_context.actions
        and ItemAction.MARK_COLLECTED in action_context.actions
    ):
        action_context = ItemActionContext(
            actions=tuple(
                a for a in action_context.actions if a != ItemAction.CANCEL_REQUEST
            ),
            status_text=action_context.status_text,
        )

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
        "person_name": banner_info.get("person_name", ""),
        "person_url": banner_info.get("person_url", ""),
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
    transactions: list["Transaction"], user: "BorrowdUser", context: str
) -> list[dict[str, Any]]:
    """
    Build card contexts for a list of transactions.

    Extracts the item from each transaction and builds card context.

    Args:
        transactions: List of Transaction objects
        user: The viewing user
        context: The card context/section (e.g., "incoming-borrow-requests")

    Returns:
        List of context dicts for item_card.html template.
    """
    return [
        # ForeignKey type not fully resolved without django-stubs mypy plugin
        build_item_card_context(transaction.item, user, context)  # type: ignore[arg-type]
        for transaction in transactions
    ]
