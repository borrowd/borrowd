"""
Lifecycle vocabulary: the statuses, actions and status sets for Items and
Transactions, and the projection from a Transaction's status to its Item's.

Imports nothing from the models at runtime, so both the models and the
transition rules can depend on it.
"""

from typing import TYPE_CHECKING

from django.db.models import IntegerChoices, TextChoices

if TYPE_CHECKING:
    from .models import Item, Transaction


class ItemAction(TextChoices):
    """
    Represents the actions that can be performed on an Item.
    This is used to determine which actions are available to the
    user when viewing an Item.
    """

    REQUEST_ITEM = "REQUEST_ITEM", "Request Item"
    ACCEPT_REQUEST = "ACCEPT_REQUEST", "Accept Request"
    REJECT_REQUEST = "REJECT_REQUEST", "Reject Request"
    MARK_COLLECTED = "MARK_COLLECTED", "Mark Collected"
    CONFIRM_COLLECTED = "CONFIRM_COLLECTED", "Confirm Collected"
    NOTIFY_WHEN_AVAILABLE = "NOTIFY_WHEN_AVAILABLE", "Notify when available"
    CANCEL_NOTIFICATION_REQUEST = (
        "CANCEL_NOTIFICATION_REQUEST",
        "Cancel notification request",
    )
    MARK_RETURNED = "MARK_RETURNED", "Mark Returned"
    CONFIRM_RETURNED = "CONFIRM_RETURNED", "Confirm Returned"
    CANCEL_REQUEST = "CANCEL_REQUEST", "Cancel Request"
    RESOLVE_TRANSACTION = "RESOLVE_TRANSACTION", "Close Out Transaction"
    REQUEST_RETURN = "REQUEST_RETURN", "Request Return"
    FLAG_CANNOT_RETURN = "FLAG_CANNOT_RETURN", "Cannot Return Item"
    RAISE_DISPUTE = "RAISE_DISPUTE", "Raise Dispute"
    RESOLVE_DISPUTE_RETURNED = (
        "RESOLVE_DISPUTE_RETURNED",
        "Resolve Dispute: Item Returned",
    )
    RESOLVE_DISPUTE_NOT_RETURNED = (
        "RESOLVE_DISPUTE_NOT_RETURNED",
        "Resolve Dispute: Item Not Returned",
    )
    OFFER_GIVEAWAY = "OFFER_GIVEAWAY", "Give Away"
    ACCEPT_GIVEAWAY = "ACCEPT_GIVEAWAY", "Accept Gift"
    DECLINE_GIVEAWAY = "DECLINE_GIVEAWAY", "Decline Gift"
    REQUEST_GIVEAWAY = "REQUEST_GIVEAWAY", "Request Gift"
    APPROVE_GIVEAWAY_REQUEST = (
        "APPROVE_GIVEAWAY_REQUEST",
        "Approve Giveaway Request",
    )
    DECLINE_GIVEAWAY_REQUEST = (
        "DECLINE_GIVEAWAY_REQUEST",
        "Decline Giveaway Request",
    )


class ItemStatus(IntegerChoices):
    """
    Represents the status of an Item. This is used to track the
    current state of an Item, and to determine which actions are
    available to the user.
    """

    # Paranoia forcing to me to use value increments of at least 10,
    # for when we later realize we need to add more in between...
    AVAILABLE = 10, "Available"
    REQUESTED = 15, "Requested"
    RESERVED = 20, "Reserved"
    BORROWED = 30, "Borrowed"


class TransactionStatus(IntegerChoices):
    """
    Represents the status of a Transaction. This is used to track
    the current state of a Transaction, and to determine which
    actions are available to the user.
    """

    # Paranoia forcing to me to use value increments of at least 10,
    # for when we later realize we need to add more in between...
    REQUESTED = 10, "Requested"
    GIVEAWAY_REQUESTED = 15, "Giveaway Requested"
    REJECTED = 20, "Rejected"
    ACCEPTED = 30, "Accepted"
    COLLECTION_ASSERTED = 40, "Collection Asserted"
    COLLECTED = 50, "Collected"
    GIVEAWAY_OFFERED = 52, "Giveaway Offered"
    RETURN_REQUESTED = 55, "Return Requested"
    RETURN_ASSERTED = 60, "Return Asserted"
    DISPUTED = 65, "Disputed"
    RETURNED = 70, "Returned"
    CANCELLED = 80, "Cancelled"
    RESOLVED = 90, "Resolved"  # any force-resolved transaction, regardless of reason
    OWNERSHIP_TRANSFERRED = 95, "Ownership Transferred"


# A transaction in one of these statuses is done; it no longer counts as the
# item's current transaction.
TERMINAL_TRANSACTION_STATUSES = (
    TransactionStatus.RETURNED,
    TransactionStatus.REJECTED,
    TransactionStatus.CANCELLED,
    TransactionStatus.RESOLVED,
    TransactionStatus.OWNERSHIP_TRANSFERRED,
)

# A transaction in one of these statuses is an open borrow or giveaway
# request awaiting the owner's decision.
REQUEST_TRANSACTION_STATUSES = (
    TransactionStatus.REQUESTED,
    TransactionStatus.GIVEAWAY_REQUESTED,
)

# Everything that still counts as the item's current transaction. Derived, so
# classifying a new status means adding it to TERMINAL or leaving it out,
# never editing a second list.
OPEN_TRANSACTION_STATUSES = tuple(
    status
    for status in TransactionStatus
    if status not in TERMINAL_TRANSACTION_STATUSES
)

# A transaction in one of these statuses has an assigned borrower (party2)
# holding, or about to hold, the item.
BORROWER_TRANSACTION_STATUSES = tuple(
    status
    for status in OPEN_TRANSACTION_STATUSES
    if status not in REQUEST_TRANSACTION_STATUSES
)

# Collection has started, so every remaining step needs both parties to act.
# Neither one can finish the transaction on their own.
DUAL_CONFIRMATION_TRANSACTION_STATUSES = tuple(
    status
    for status in BORROWER_TRANSACTION_STATUSES
    if status != TransactionStatus.ACCEPTED
)

# Nothing has changed hands yet, so these can be cancelled outright without
# anyone having to hand an item back.
PRE_COLLECTION_TRANSACTION_STATUSES = tuple(
    status
    for status in OPEN_TRANSACTION_STATUSES
    if status not in DUAL_CONFIRMATION_TRANSACTION_STATUSES
)

# A member cannot leave a group while they share a transaction in one of these statuses with another member.
GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES = (
    TransactionStatus.COLLECTED,
    TransactionStatus.RETURN_ASSERTED,
)


# Item.status is a summary of the item's current transaction, not state of its
# own. This is the whole mapping; no caller should pick an ItemStatus by hand.
ITEM_STATUS_FOR_TRANSACTION: dict[TransactionStatus, ItemStatus] = {
    **{status: ItemStatus.AVAILABLE for status in TERMINAL_TRANSACTION_STATUSES},
    TransactionStatus.REQUESTED: ItemStatus.REQUESTED,
    TransactionStatus.GIVEAWAY_REQUESTED: ItemStatus.REQUESTED,
    TransactionStatus.ACCEPTED: ItemStatus.RESERVED,
    TransactionStatus.COLLECTION_ASSERTED: ItemStatus.RESERVED,
    TransactionStatus.COLLECTED: ItemStatus.BORROWED,
    TransactionStatus.GIVEAWAY_OFFERED: ItemStatus.BORROWED,
    TransactionStatus.RETURN_REQUESTED: ItemStatus.BORROWED,
    TransactionStatus.RETURN_ASSERTED: ItemStatus.BORROWED,
    TransactionStatus.DISPUTED: ItemStatus.BORROWED,
}


def sync_item_status(item: "Item", tx: "Transaction") -> None:
    """
    Point item.status at whatever its transaction now says it should be.

    A soft-deleted item keeps the status it had. It is out of circulation
    either way, and a departed owner's items are deleted while their
    transactions are still being closed out.
    """
    if item.deleted_at is not None:
        return
    status = ITEM_STATUS_FOR_TRANSACTION[TransactionStatus(tx.status)]
    if item.status != status:
        item.status = status
        item.save(update_fields=("status", "updated_at"))


class ResolutionReason(TextChoices):
    """
    Why a Transaction was force-resolved instead of completing the normal flow.
    Set alongside TransactionStatus.RESOLVED.
    """

    OWNER_ACCOUNT_DELETED = ("owner_account_deleted", "Owner closed their account")
    MODERATOR_OVERRIDE = ("moderator_override", "Resolved by a moderator")
    COUNTERPARTY_UNRESPONSIVE = (
        "counterparty_unresponsive",
        "Other party was unresponsive",
    )
    DISPUTE_ITEM_NOT_RETURNED = (
        "dispute_item_not_returned",
        "Disputed item was not returned",
    )
