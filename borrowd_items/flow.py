"""The Transaction lifecycle as a table: who may take each edge, and when."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Final

from .statuses import (
    DUAL_CONFIRMATION_TRANSACTION_STATUSES,
    ItemAction,
    TransactionStatus,
)

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

    from .models import Transaction


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


@dataclass(frozen=True)
class Transition:
    source: TransactionStatus
    action: ItemAction
    target: TransactionStatus
    actor: Actor = Actor.EITHER
    guard: Guard | None = None
    # When eligible, this is the only transition offered from its source.
    preempts: bool = False


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
    ),
    # The borrower says it is back; the lender confirms or denies.
    Transition(
        TransactionStatus.RETURN_ASSERTED,
        ItemAction.RAISE_DISPUTE,
        TransactionStatus.DISPUTED,
        Actor.LENDER,
        _other_party_acted_last,
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
