"""The Transaction lifecycle as a table: who may take each edge, and what it writes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Final

from django.db import transaction

from .exceptions import InvalidItemAction
from .statuses import (
    DUAL_CONFIRMATION_TRANSACTION_STATUSES,
    ItemAction,
    ResolutionReason,
    TransactionStatus,
    sync_item_status,
)

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

    from .models import Item, Transaction


class Actor(Enum):
    """Roles come from the Transaction's parties, not from who owns the Item."""

    EITHER = "either"
    LENDER = "lender"  # Transaction.party1
    BORROWER = "borrower"  # Transaction.party2


Guard = Callable[["Transaction", "BorrowdUser", datetime], bool]


def _counterparty_of(tx: Transaction, user: BorrowdUser) -> BorrowdUser:
    return tx.party2 if user.pk == tx.party1_id else tx.party1


def _other_party_acted_last(tx: Transaction, user: BorrowdUser, now: datetime) -> bool:
    return tx.updated_by_id != user.pk


def _dispute_wait_elapsed(tx: Transaction, user: BorrowdUser, now: datetime) -> bool:
    return tx.dispute_wait_has_elapsed(now)


def _counterparty_inactive(tx: Transaction, user: BorrowdUser, now: datetime) -> bool:
    return not _counterparty_of(tx, user).is_active


# Sets Transaction fields before the save.
Prepare = Callable[["Transaction", "BorrowdUser", datetime], None]
# Runs after the save, in the same database transaction.
AfterSave = Callable[["Item", "Transaction", "BorrowdUser"], None]


def _stamp_return_requested(tx: Transaction, user: BorrowdUser, now: datetime) -> None:
    tx.return_requested_at = now


def _stamp_dispute(tx: Transaction, user: BorrowdUser, now: datetime) -> None:
    tx.disputed_at = now
    tx.dispute_raised_by = user


def _record_item_not_returned(
    tx: Transaction, user: BorrowdUser, now: datetime
) -> None:
    tx.resolution_reason = ResolutionReason.DISPUTE_ITEM_NOT_RETURNED


def _record_why_resolved_alone(
    tx: Transaction, user: BorrowdUser, now: datetime
) -> None:
    counterparty = _counterparty_of(tx, user)
    owner_deleted = (
        counterparty.pk == tx.party1_id and counterparty.deleted_at is not None
    )
    tx.resolution_reason = (
        ResolutionReason.OWNER_ACCOUNT_DELETED
        if owner_deleted
        else ResolutionReason.COUNTERPARTY_UNRESPONSIVE
    )


def _give_item_to_actor(item: Item, tx: Transaction, user: BorrowdUser) -> None:
    item._transfer_ownership(new_owner=user, by=user)


def _give_item_to_borrower(item: Item, tx: Transaction, user: BorrowdUser) -> None:
    item._transfer_ownership(new_owner=tx.party2, by=user)


def _remove_lost_item(item: Item, tx: Transaction, user: BorrowdUser) -> None:
    # After the save, so the thread archives as resolved, not as item-deleted.
    item.soft_delete(deleted_by=user)


@dataclass(frozen=True)
class Transition:
    source: TransactionStatus
    action: ItemAction
    target: TransactionStatus
    actor: Actor = Actor.EITHER
    guard: Guard | None = None
    # When eligible, this is the only transition offered from its source.
    preempts: bool = False
    prepare: Prepare | None = None
    after_save: AfterSave | None = None


# Order within a source is the order the actions are shown to the user.
TRANSITIONS: Final[tuple[Transition, ...]] = (
    # The counterparty's account is gone, so the other party may close out alone.
    *(
        Transition(
            source,
            ItemAction.RESOLVE_TRANSACTION,
            TransactionStatus.RESOLVED,
            guard=_counterparty_inactive,
            preempts=True,
            prepare=_record_why_resolved_alone,
        )
        for source in DUAL_CONFIRMATION_TRANSACTION_STATUSES
    ),
    # A borrow request awaiting the owner's decision.
    Transition(
        TransactionStatus.REQUESTED,
        ItemAction.REJECT_REQUEST,
        TransactionStatus.REJECTED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.REQUESTED,
        ItemAction.ACCEPT_REQUEST,
        TransactionStatus.ACCEPTED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.REQUESTED,
        ItemAction.CANCEL_REQUEST,
        TransactionStatus.CANCELLED,
        Actor.BORROWER,
    ),
    # A giveaway request awaiting the owner's decision.
    Transition(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.DECLINE_GIVEAWAY_REQUEST,
        TransactionStatus.REJECTED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.APPROVE_GIVEAWAY_REQUEST,
        TransactionStatus.OWNERSHIP_TRANSFERRED,
        Actor.LENDER,
        after_save=_give_item_to_borrower,
    ),
    Transition(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.CANCEL_REQUEST,
        TransactionStatus.CANCELLED,
        Actor.BORROWER,
    ),
    # Accepted, not yet handed over.
    Transition(
        TransactionStatus.ACCEPTED,
        ItemAction.CANCEL_REQUEST,
        TransactionStatus.CANCELLED,
    ),
    Transition(
        TransactionStatus.ACCEPTED,
        ItemAction.MARK_COLLECTED,
        TransactionStatus.COLLECTION_ASSERTED,
    ),
    Transition(
        TransactionStatus.COLLECTION_ASSERTED,
        ItemAction.CONFIRM_COLLECTED,
        TransactionStatus.COLLECTED,
        guard=_other_party_acted_last,
    ),
    # On loan. The lender has the item back in hand when they mark it
    # returned, so their mark closes the loan; the borrower's only asserts.
    Transition(
        TransactionStatus.COLLECTED,
        ItemAction.CONFIRM_RETURNED,
        TransactionStatus.RETURNED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.COLLECTED,
        ItemAction.REQUEST_RETURN,
        TransactionStatus.RETURN_REQUESTED,
        Actor.LENDER,
        prepare=_stamp_return_requested,
    ),
    Transition(
        TransactionStatus.COLLECTED,
        ItemAction.OFFER_GIVEAWAY,
        TransactionStatus.GIVEAWAY_OFFERED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.COLLECTED,
        ItemAction.MARK_RETURNED,
        TransactionStatus.RETURN_ASSERTED,
        Actor.BORROWER,
    ),
    # The lender has offered the item as a gift; the borrower decides.
    Transition(
        TransactionStatus.GIVEAWAY_OFFERED,
        ItemAction.ACCEPT_GIVEAWAY,
        TransactionStatus.OWNERSHIP_TRANSFERRED,
        Actor.BORROWER,
        after_save=_give_item_to_actor,
    ),
    Transition(
        TransactionStatus.GIVEAWAY_OFFERED,
        ItemAction.DECLINE_GIVEAWAY,
        TransactionStatus.COLLECTED,
        Actor.BORROWER,
    ),
    # The lender has asked for the item back.
    Transition(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.RAISE_DISPUTE,
        TransactionStatus.DISPUTED,
        Actor.LENDER,
        _dispute_wait_elapsed,
        prepare=_stamp_dispute,
    ),
    Transition(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.CONFIRM_RETURNED,
        TransactionStatus.RETURNED,
        Actor.LENDER,
    ),
    Transition(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.MARK_RETURNED,
        TransactionStatus.RETURN_ASSERTED,
        Actor.BORROWER,
    ),
    Transition(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.FLAG_CANNOT_RETURN,
        TransactionStatus.DISPUTED,
        Actor.BORROWER,
        prepare=_stamp_dispute,
    ),
    # The borrower says it is back; the lender confirms or denies.
    Transition(
        TransactionStatus.RETURN_ASSERTED,
        ItemAction.RAISE_DISPUTE,
        TransactionStatus.DISPUTED,
        Actor.LENDER,
        _other_party_acted_last,
        prepare=_stamp_dispute,
    ),
    Transition(
        TransactionStatus.RETURN_ASSERTED,
        ItemAction.CONFIRM_RETURNED,
        TransactionStatus.RETURNED,
        guard=_other_party_acted_last,
    ),
    # The lender settles a dispute one way or the other.
    Transition(
        TransactionStatus.DISPUTED,
        ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
        TransactionStatus.RESOLVED,
        Actor.LENDER,
        prepare=_record_item_not_returned,
        after_save=_remove_lost_item,
    ),
    Transition(
        TransactionStatus.DISPUTED,
        ItemAction.RESOLVE_DISPUTE_RETURNED,
        TransactionStatus.RETURNED,
        Actor.LENDER,
    ),
)


def _actor_matches(spec: Transition, tx: Transaction, user: BorrowdUser) -> bool:
    if spec.actor is Actor.LENDER:
        return user.pk == tx.party1_id
    if spec.actor is Actor.BORROWER:
        return user.pk == tx.party2_id
    return True


def eligible_transitions(
    tx: Transaction, user: BorrowdUser, *, now: datetime
) -> tuple[Transition, ...]:
    """Transitions `user` may take on `tx` as of `now`, in display order."""
    if user.pk not in (tx.party1_id, tx.party2_id):
        return ()
    eligible = tuple(
        spec
        for spec in TRANSITIONS
        if spec.source == tx.status
        and _actor_matches(spec, tx, user)
        and (spec.guard is None or spec.guard(tx, user, now))
    )
    preempting = tuple(spec for spec in eligible if spec.preempts)
    return preempting or eligible


def available_actions(
    tx: Transaction, user: BorrowdUser, *, now: datetime
) -> tuple[ItemAction, ...]:
    """The action names behind `eligible_transitions`."""
    return tuple(spec.action for spec in eligible_transitions(tx, user, now=now))


def execute_transition(
    item: Item,
    tx: Transaction,
    user: BorrowdUser,
    action: ItemAction,
    *,
    now: datetime,
) -> Transition:
    """Apply `action` atomically. Raises InvalidItemAction unless it is eligible."""
    spec = next(
        (
            candidate
            for candidate in eligible_transitions(tx, user, now=now)
            if candidate.action == action
        ),
        None,
    )
    if spec is None:
        raise InvalidItemAction(
            f"User '{user}' cannot perform action '{action}' on "
            f"Item '{item}' at this time."
        )

    with transaction.atomic():
        tx.status = spec.target
        tx.updated_by = user
        if spec.prepare is not None:
            spec.prepare(tx, user, now)
        tx.save()
        if spec.after_save is not None:
            spec.after_save(item, tx, user)
        sync_item_status(item, tx)
    return spec
