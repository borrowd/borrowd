"""
Helper functions for building item card context and related utilities.

These functions provide consistent context building for item card rendering
used throughout the application.
"""

from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import capfirst

from .models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemAction,
    ItemActionContext,
    ItemStatus,
    PrecomputedItemState,
    Transaction,
    TransactionStatus,
)

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser


# Giveaway listings, offers, and pending requests share the gift icon.
_GIVEAWAY_ICON = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M21 11.25v8.25a1.5 1.5 0 0 1-1.5 1.5H5.25a1.5 1.5 0 0 1-1.5-1.5v-8.25M12 4.875A2.625 2.625 0 1 0 9.375 7.5H12m0-2.625V7.5m0-2.625A2.625 2.625 0 1 1 14.625 7.5H12m0 0V21m-8.625-9.75h18c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125h-18c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" /></svg>'

# Banner styling configuration
BANNER_ICONS = {
    "available": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"/></svg>',
    "requested": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 4.13401 4.13401 1 8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8ZM8.75 3.75C8.75 3.33579 8.41421 3 8 3C7.58579 3 7.25 3.33579 7.25 3.75V8C7.25 8.41421 7.58579 8.75 8 8.75H11.25C11.6642 8.75 12 8.41421 12 8C12 7.58579 11.6642 7.25 11.25 7.25H8.75V3.75Z" fill="#8E6900"/></svg>',
    "reserved": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z" clip-rule="evenodd"/></svg>',
    "borrowed": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 4.13401 4.13401 1 8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8ZM8.75 3.75C8.75 3.33579 8.41421 3 8 3C7.58579 3 7.25 3.33579 7.25 3.75V8C7.25 8.41421 7.58579 8.75 8 8.75H11.25C11.6642 8.75 12 8.41421 12 8C12 7.58579 11.6642 7.25 11.25 7.25H8.75V3.75Z" fill="#2C51A1"/></svg>',
    "pending": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 4.13401 4.13401 1 8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8ZM8.75 3.75C8.75 3.33579 8.41421 3 8 3C7.58579 3 7.25 3.33579 7.25 3.75V8C7.25 8.41421 7.58579 8.75 8 8.75H11.25C11.6642 8.75 12 8.41421 12 8C12 7.58579 11.6642 7.25 11.25 7.25H8.75V3.75Z" fill="#73325b"/></svg>',
    "waitlisted": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none"><path fill-rule="evenodd" clip-rule="evenodd" d="M8 1.75C6.20507 1.75 4.75 3.20507 4.75 5V5.76393C4.75 6.40114 4.54563 7.02157 4.16672 7.53394L3.23959 8.7877C2.6945 9.52485 3.22081 10.5625 4.13655 10.5625H11.8634C12.7792 10.5625 13.3055 9.52485 12.7604 8.7877L11.8333 7.53394C11.4544 7.02157 11.25 6.40114 11.25 5.76393V5C11.25 3.20507 9.79493 1.75 8 1.75ZM6.5 11.75C6.5 12.5784 7.17157 13.25 8 13.25C8.82843 13.25 9.5 12.5784 9.5 11.75H6.5Z" fill="#6B7280"/><path d="M12.25 4.5C13.2165 4.5 14 3.7165 14 2.75C14 1.7835 13.2165 1 12.25 1C11.2835 1 10.5 1.7835 10.5 2.75C10.5 3.7165 11.2835 4.5 12.25 4.5Z" fill="#6B7280"/></svg>',
    "return_requested": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5"><path fill-rule="evenodd" d="M7.793 2.232a.75.75 0 0 1-.025 1.06L3.622 7.25h10.003a5.375 5.375 0 0 1 0 10.75H10.75a.75.75 0 0 1 0-1.5h2.875a3.875 3.875 0 0 0 0-7.75H3.622l4.146 3.957a.75.75 0 0 1-1.036 1.085l-5.5-5.25a.75.75 0 0 1 0-1.085l5.5-5.25a.75.75 0 0 1 1.06.025Z" clip-rule="evenodd" /></svg>',
    "disputed": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5"><path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 5Zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>',
    "removed": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5"><path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 5Zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>',
    "giveaway_offered": _GIVEAWAY_ICON,
    "giveaway_listing": _GIVEAWAY_ICON,
    "giveaway_requested": _GIVEAWAY_ICON,
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
    # "pending" is what non-owners see instead of "requested" or "reserved".
    "pending": {"bg": "bg-secondary/15", "text": "text-secondary"},
    "waitlisted": {"bg": "bg-gray-400/15", "text": "text-[#6B7280]"},
    # item has been removed from borrow'd
    "removed": {"bg": "bg-warning/15", "text": "text-[#8E6900]"},
    "return_requested": {"bg": "bg-primary/15", "text": "text-primary"},
    "disputed": {"bg": "bg-warning/15", "text": "text-[#8E6900]"},
    "giveaway_offered": {"bg": "bg-primary/15", "text": "text-primary"},
    "giveaway_listing": {"bg": "bg-primary/15", "text": "text-primary"},
    "giveaway_requested": {"bg": "bg-primary/15", "text": "text-primary"},
}

_TERMINAL_TRANSACTION_STATUSES = (
    TransactionStatus.RETURNED,
    TransactionStatus.REJECTED,
    TransactionStatus.CANCELLED,
    TransactionStatus.RESOLVED,
    TransactionStatus.OWNERSHIP_TRANSFERRED,
)

_REQUEST_TRANSACTION_STATUSES = (
    TransactionStatus.REQUESTED,
    TransactionStatus.GIVEAWAY_REQUESTED,
)

_BORROWER_TRANSACTION_STATUSES = (
    TransactionStatus.ACCEPTED,
    TransactionStatus.COLLECTION_ASSERTED,
    TransactionStatus.COLLECTED,
    TransactionStatus.GIVEAWAY_OFFERED,
    TransactionStatus.RETURN_REQUESTED,
    TransactionStatus.RETURN_ASSERTED,
    TransactionStatus.DISPUTED,
)

_TRANSACTION_SELECT_RELATED = (
    "party1",
    "party1__profile",
    "party2",
    "party2__profile",
    "updated_by",
)

_ITEM_SELECT_RELATED = ("owner", "owner__profile")

_CARD_TRANSACTION_SELECT_RELATED = (
    *_TRANSACTION_SELECT_RELATED,
    "item",
    "item__owner",
    "item__owner__profile",
)


def with_card_relations(queryset: "QuerySet[Item]") -> "QuerySet[Item]":
    """
    Apply the select_related/prefetch_related an item card needs.

    Callers building a queryset of Items destined for
    build_item_cards_for_items() should wrap it with this before
    evaluating it, so owner/profile/photo access doesn't cost a query
    per card. If a caller forgets, cards still render correctly -- just
    with a query per card instead of one for the whole list.
    """
    return queryset.select_related(*_ITEM_SELECT_RELATED).prefetch_related("photos")


def with_card_relations_for_transactions(
    queryset: "QuerySet[Transaction]",
) -> "QuerySet[Transaction]":
    """
    Apply the select_related/prefetch_related an item card needs when
    rendering from a Transaction queryset.

    Callers building a queryset of Transactions destined for
    build_item_cards_for_transactions() should wrap it with this before
    evaluating it. If a caller forgets, cards still render correctly --
    just with a query per card instead of one for the whole list.
    """
    return queryset.select_related(*_CARD_TRANSACTION_SELECT_RELATED).prefetch_related(
        "item__photos"
    )


def _state_from_transaction(
    transaction: Transaction | None,
    *,
    has_active_subscription: bool = False,
) -> PrecomputedItemState:
    """
    Derive card state from an already-loaded transaction without querying the db.

    Both action context and banner rendering need borrower/requester/current
    transaction state, so centralizing the derivation lets them share the same
    in-memory facts.
    """
    current_borrower = None
    requesting_user = None

    if transaction is not None:
        if transaction.status in _REQUEST_TRANSACTION_STATUSES:
            requesting_user = transaction.party2
        elif transaction.status in _BORROWER_TRANSACTION_STATUSES:
            current_borrower = transaction.party2

    return PrecomputedItemState(
        current_borrower=current_borrower,
        requesting_user=requesting_user,
        current_transaction=transaction,
        has_active_subscription=has_active_subscription,
    )


def _active_subscription_item_ids(
    item_ids: list[int],
    user: "BorrowdUser",
) -> set[int]:
    """
    Fetch active subscription flags for all card items in one query.

    Without this batch lookup, unavailable item cards can each check whether
    the viewing user has an active notify-me subscription.
    """
    if not item_ids:
        return set()

    return set(
        AvailabilitySubscription.objects.filter(
            item_id__in=item_ids,
            user=user,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        ).values_list("item_id", flat=True)
    )


def _precompute_item_states_for_items(
    items: list["Item"],
    user: "BorrowdUser",
) -> dict[int, PrecomputedItemState]:
    """
    Build per-item card state (cache-like) for an item list with batch queries.

    This replaces repeated get_current_borrower/get_requesting_user/
    get_current_transaction/subscription calls while rendering item grids.
    """
    item_ids = [item.pk for item in items]
    if not item_ids:
        return {}

    current_transactions: dict[int, Transaction] = {}
    for transaction in (
        Transaction.objects.filter(item_id__in=item_ids)
        .exclude(status__in=_TERMINAL_TRANSACTION_STATUSES)
        .select_related(*_TRANSACTION_SELECT_RELATED)
        .order_by("item_id", "-created_at")
    ):
        current_transactions.setdefault(transaction.item_id, transaction)

    subscription_item_ids = _active_subscription_item_ids(item_ids, user)

    return {
        item_id: _state_from_transaction(
            current_transactions.get(item_id),
            has_active_subscription=item_id in subscription_item_ids,
        )
        for item_id in item_ids
    }


def _precompute_item_states_for_transactions(
    transactions: list[Transaction],
    user: "BorrowdUser",
) -> dict[int, PrecomputedItemState]:
    """
    Build per-transaction card state (cache-like) from the loaded transaction rows.

    Transaction sections already know the active transaction, so this avoids
    asking the database to rediscover the same current transaction per card.
    """
    item_ids = [transaction.item_id for transaction in transactions]
    if not item_ids:
        return {}

    subscription_item_ids = _active_subscription_item_ids(item_ids, user)

    return {
        transaction.pk: _state_from_transaction(
            transaction,
            has_active_subscription=transaction.item_id in subscription_item_ids,
        )
        for transaction in transactions
    }


def _precompute_item_state(
    item: "Item",
    user: "BorrowdUser",
) -> PrecomputedItemState:
    """
    Build card state for a single item when no batch state was cached or supplied.

    This preserves the standalone build_item_card_context() API while keeping
    its action-context and banner paths on one shared state object.
    """
    current_transaction = item.get_current_transaction()
    needs_subscription_state = item.owner_id != user.id and (
        current_transaction is not None or item.status != ItemStatus.AVAILABLE
    )
    has_active_subscription = (
        bool(
            AvailabilitySubscription.objects.filter(
                item=item,
                user=user,
                status=AvailabilitySubscriptionStatus.ACTIVE,
            ).exists()
        )
        if needs_subscription_state
        else False
    )
    return _state_from_transaction(
        current_transaction,
        has_active_subscription=has_active_subscription,
    )


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
    item: "Item",
    viewing_user: "BorrowdUser",
    precomputed: "PrecomputedItemState | None" = None,
) -> dict[str, str]:
    """
    Get banner type and request info, checking for pending requests.

    Determines the appropriate banner to display for an item card based on:
    1. Whether there's a pending request transaction
    2. The item's current status (available, reserved, borrowed)
    3. The viewer's relationship to the item (owner, borrower, or neither)

    Privacy rules:
    - Owner sees full detail: banner type, borrower name (linked), time
    - Borrower/requester sees their own involvement: "me", time
    - Everyone else sees a generic label only ("Pending" or "Borrowed")

    Args:
        item: The Item to get banner info for
        viewing_user: The user viewing the card
            for "me" substitution
            determines what info is shown
        precomputed: current_borrower/requesting_user, if the caller
            already derived them (e.g. alongside action context for the
            same item) and wants to skip re-deriving them here.

    Returns:
        Dict with banner_type (str),
        and optionally person_name, person_url, and time_ago
        depending on the viewer's relationship to the item.

    Examples:
        - Owner viewing item with pending request:
          {'banner_type': 'requested', 'person_name': 'John',
           'person_url': '/profile/5/', 'time_ago': '2 hours'}
        - Borrower viewing their own request:
          {'banner_type': 'requested', 'person_name': 'me', 'time_ago': '2 hours'}
        - Non-owner viewing item with pending request:
          {'banner_type': 'pending'}
        - Non-owner viewing borrowed item:
          {'banner_type': 'borrowed'}
        - Available item (any viewer):
          {'banner_type': 'available'}
    """
    from django.utils.timesince import timesince

    from .models import ListingType

    # Check for active transaction to determine banner state
    if precomputed is None:
        precomputed = _precompute_item_state(item, viewing_user)

    current_borrower = precomputed.current_borrower
    requesting_user = precomputed.requesting_user
    current_transaction = precomputed.current_transaction

    if not current_transaction:
        # No active transaction; a giveaway listing advertises itself.
        if item.listing_type == ListingType.GIVEAWAY:
            return {"banner_type": "giveaway_listing"}
        # No active transaction or subscription, item is available by default
        return {"banner_type": "available"}

    if (
        requesting_user != viewing_user
        and current_borrower != viewing_user
        and precomputed.has_active_subscription
    ):
        return {"banner_type": "waitlisted"}

    # Return-request, giveaway, and dispute banners only concern the two
    # parties; everyone else sees the generic borrowed label.
    if current_transaction.status == TransactionStatus.DISPUTED:
        if item.owner_id == viewing_user.id or current_borrower == viewing_user:
            return {"banner_type": "disputed"}
        return {"banner_type": "borrowed"}

    # giveaway banner: owner sees "Giveaway Offered",
    # borrower sees the offer with the lender's name.
    if current_transaction.status == TransactionStatus.GIVEAWAY_OFFERED:
        if item.owner_id == viewing_user.id:
            return {"banner_type": "giveaway_offered"}
        if current_borrower == viewing_user:
            return {
                "banner_type": "giveaway_offered",
                "person_name": item.owner.first_name.capitalize(),
            }
        return {"banner_type": "borrowed"}

    # giveaway-request banner: owner sees who's asking, the requester sees
    # their request is pending, everyone else sees the generic pending label.
    if current_transaction.status == TransactionStatus.GIVEAWAY_REQUESTED:
        if item.owner_id == viewing_user.id:
            return {
                "banner_type": "giveaway_requested",
                "person_name": capfirst(current_transaction.party2.first_name),
                "person_url": reverse(
                    "public-profile", args=[current_transaction.party2.pk]
                ),
            }
        if requesting_user == viewing_user:
            return {"banner_type": "giveaway_requested"}
        return {"banner_type": "pending"}

    # The return-request banner stays up while the borrower's return
    # assertion awaits the lender's confirmation.
    return_request_open = (
        current_transaction.status == TransactionStatus.RETURN_REQUESTED
        or (
            current_transaction.status == TransactionStatus.RETURN_ASSERTED
            and current_transaction.return_requested_at is not None
        )
    )
    if return_request_open:
        if item.owner_id == viewing_user.id:
            return {"banner_type": "return_requested", "person_name": "you"}
        if current_borrower == viewing_user:
            return {
                "banner_type": "return_requested",
                "person_name": item.owner.first_name.capitalize(),
            }
        return {"banner_type": "borrowed"}

    # Determine banner based on transaction status
    if current_transaction.status == TransactionStatus.REQUESTED:
        banner_type = "requested"
    elif current_transaction.status in [
        TransactionStatus.ACCEPTED,
        TransactionStatus.COLLECTION_ASSERTED,
    ]:
        banner_type = "reserved"
    elif current_transaction.status in [
        TransactionStatus.COLLECTED,
        TransactionStatus.RETURN_ASSERTED,
    ]:
        banner_type = "borrowed"
    else:
        # Fallback to available
        return {"banner_type": "available"}

    # Build person display info.

    #  requesting_user for a REQUESTED transaction
    #  current_borrower for an ACCEPTED/COLLECTED or RETURN_ASSERTED transaction
    user_whose_name_should_be_shown_in_banner = requesting_user or current_borrower
    if user_whose_name_should_be_shown_in_banner is None:
        """ This should never happen, as we already have a fallback above to
        handle a no transaction case, and all transactions should have users,
        but it's here for type safety since I'm getting errors when
        defining `person_name` and `person_url` below"""
        return {"banner_type": "available"}

    viewing_user_is_item_owner = item.owner_id == viewing_user.id
    viewing_user_is_borrower = user_whose_name_should_be_shown_in_banner == viewing_user

    # Everyone except the owner and the person in the transaction gets a
    # generic label with no name, link, or timestamp detail.
    if not viewing_user_is_item_owner and not viewing_user_is_borrower:
        if banner_type in ("requested", "reserved"):
            return {"banner_type": "pending"}
        return {"banner_type": "borrowed"}

    time_ago = timesince(current_transaction.updated_at).split(",")[0]

    # Borrower sees "me" with no profile link.
    if viewing_user_is_borrower:
        return {
            "banner_type": banner_type,
            "person_name": "me",
            "time_ago": time_ago,
        }

    # At this point, the viewer is the owner, so they get the other person's
    # name and a link to that person's profile.
    person_name = user_whose_name_should_be_shown_in_banner.first_name.capitalize()
    person_url = f"/profile/{user_whose_name_should_be_shown_in_banner.pk}/"

    return {
        "banner_type": banner_type,
        "person_name": person_name,
        "person_url": person_url,
        "time_ago": time_ago,
    }


def build_item_card_context(
    item: "Item",
    user: "BorrowdUser",
    context: str,
    action_context: "ItemActionContext | None" = None,
    precomputed: "PrecomputedItemState | None" = None,
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
        precomputed: Pre-computed item state, or None to compute it
        error_message: Optional error message to display
        error_type: Optional error type (e.g., "already_requested")

    Returns:
        Dict with all context variables needed by item_card.html template.
    """
    # current_borrower/requesting_user are viewer-independent, so computing
    # them once here lets both get_action_context_for and
    # get_banner_info_for_item skip re-deriving them below.
    if action_context is None:
        if precomputed is None:
            precomputed = _precompute_item_state(item, user)
        action_context = item.get_action_context_for(
            user=user,
            precomputed=precomputed,
        )

    # Once the request is approved, the card only shows "Confirm picked up".
    # Cancel is still accessible on the item detail page.
    if (
        ItemAction.CANCEL_REQUEST in action_context.actions
        and ItemAction.MARK_COLLECTED in action_context.actions
        and context != "item-details"
    ):
        action_context = ItemActionContext(
            actions=tuple(
                a for a in action_context.actions if a != ItemAction.CANCEL_REQUEST
            ),
            status_text=action_context.status_text,
            waiting_text=action_context.waiting_text,
        )

    # item.photos.first() would build a fresh ordered queryset and bypass
    # any prefetch_related("photos") the caller set up; this reads the
    # prefetch cache when present.
    first_photo = next(iter(item.photos.all()), None)
    banner_info = get_banner_info_for_item(item, user, precomputed=precomputed)
    card_ids = build_card_ids(context, item.pk)

    # Get banner styling
    banner_type = banner_info.get("banner_type", "")
    # if the item has been deleted
    is_removed = item.deleted_at is not None
    if is_removed:
        banner_type = "removed"
    banner_style = BANNER_STYLES.get(banner_type, {})
    # format_html necessary to display svg, otherwise it just gets shown as plaintext
    # https://docs.djangoproject.com/en/6.0/ref/utils/#django.utils.html.format_html
    banner_icon = format_html(BANNER_ICONS.get(banner_type, ""))

    try:
        image = first_photo.thumbnail.url if first_photo else ""
    except FileNotFoundError:
        image = ""

    ctx: dict[str, Any] = {
        "item": item,
        "action_context": action_context,
        "pk": item.pk,
        "context": context,
        "name": item.name,
        "description": item.description,
        "image": image,
        "is_yours": item.owner_id == user.id,
        "is_removed": is_removed,
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
        items: List of Item objects to render. Build the queryset this list
            came from with with_card_relations() so owner/profile/photo
            access doesn't cost a query per card.
        user: The viewing user
        context: The card context/section (e.g., "search", "my-items")

    Returns:
        List of context dicts for item_card.html template.
    """
    precomputed_by_item_id = _precompute_item_states_for_items(items, user)
    return [
        build_item_card_context(
            item,
            user,
            context,
            precomputed=precomputed_by_item_id[item.pk],
        )
        for item in items
    ]


def build_item_cards_for_transactions(
    transactions: list["Transaction"], user: "BorrowdUser", context: str
) -> list[dict[str, Any]]:
    """
    Build card contexts for a list of transactions.

    Extracts the item from each transaction and builds card context.

    Args:
        transactions: List of Transaction objects. Build the queryset this
            list came from with with_card_relations_for_transactions() so
            party/item/photo access doesn't cost a query per card.
        user: The viewing user
        context: The card context/section (e.g., "incoming-borrow-requests")

    Returns:
        List of context dicts for item_card.html template.
    """
    precomputed_by_transaction_id = _precompute_item_states_for_transactions(
        transactions,
        user,
    )
    return [
        # ForeignKey type not fully resolved without django-stubs mypy plugin
        # Ref: https://forum.djangoproject.com/t/mypy-and-type-checking/15787,
        # Ref: https://github.com/typeddjango/django-stubs
        build_item_card_context(
            transaction.item,
            user,
            context,
            precomputed=precomputed_by_transaction_id[transaction.pk],
        )
        for transaction in transactions
    ]
