"""
Runs the hand-written action rules beside the transition table and reports any
disagreement between them. The hand-written answer is the one that is served.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

import sentry_sdk
from django.conf import settings
from django.utils import timezone

from .flow import available_actions
from .statuses import ItemAction, TransactionStatus

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

    from .models import Item, Transaction

# Under the project logger, which is configured at INFO.
logger = logging.getLogger("borrowd.items.flow_parity")

# The two rule sets name the lender differently: the table by the
# Transaction's party1, the hand-written rules by the Item's owner. When those
# are not the same user the data is inconsistent, which is a different problem
# from a wrong table row.
LENDER_IS_NOT_OWNER = "lender_is_not_owner"
ACTIONS_DIFFER = "actions_differ"

Actions = tuple[ItemAction, ...]

_REPORT_TTL_SECONDS = 60 * 60
_REPORT_CACHE_SIZE = 256
_reported_until: dict[tuple[object, ...], float] = {}
_comparisons: Counter[tuple[str, str, Actions]] = Counter()


def actions_for_open_transaction(
    item: Item, tx: Transaction, user: BorrowdUser
) -> Actions:
    """
    The actions `user`, a party to `tx`, may take on it.

    Both rule sets see the same Transaction and the same captured time, so a
    disagreement is about the rules and never about when each one looked.
    """
    now = timezone.now()
    served = legacy_actions_for(item, tx, user, now=now)
    if settings.ITEMS_FLOW_PARITY_CHECK:
        _compare_with_table(item, tx, user, now, served)
    return served


def legacy_actions_for(
    item: Item, tx: Transaction, user: BorrowdUser, *, now: datetime
) -> Actions:
    """
    The hand-written rules. Only ever asked about a party to `tx`.

    The status tuple below is spelled out on purpose: this is the reference
    the table is checked against, so it shares no derived set with it.
    """
    # If the other party's account is inactive (they closed it), the
    # dual-confirmation handshake can never complete.
    # therefore, let the remaining party close the loan out single-handed.
    if tx.status in (
        TransactionStatus.COLLECTION_ASSERTED,
        TransactionStatus.COLLECTED,
        TransactionStatus.GIVEAWAY_OFFERED,
        TransactionStatus.RETURN_REQUESTED,
        TransactionStatus.RETURN_ASSERTED,
        TransactionStatus.DISPUTED,
    ):
        counterparty = tx.party1 if tx.party2 == user else tx.party2
        if not counterparty.is_active:
            return (ItemAction.RESOLVE_TRANSACTION,)

    if tx.status == TransactionStatus.REQUESTED:
        if item.owner_id == user.id:
            # The User is the owner of the Item, and the current
            # Transaction is a Request from another User.
            # The owner can either Accept or Reject the Request.
            return (
                ItemAction.REJECT_REQUEST,
                ItemAction.ACCEPT_REQUEST,
            )
        else:
            # The User is the requestor and the current
            # Transaction is a Request from them.
            # No next steps until owner confirms,
            # but may cancel.
            return (ItemAction.CANCEL_REQUEST,)
    elif tx.status == TransactionStatus.GIVEAWAY_REQUESTED:
        if item.owner_id == user.id:
            # The owner decides whether to hand the item over.
            return (
                ItemAction.DECLINE_GIVEAWAY_REQUEST,
                ItemAction.APPROVE_GIVEAWAY_REQUEST,
            )
        # The requester waits on the owner, but may cancel.
        return (ItemAction.CANCEL_REQUEST,)
    elif tx.status == TransactionStatus.ACCEPTED:
        # Either borrower or lender can assert collection.
        return (
            ItemAction.CANCEL_REQUEST,
            ItemAction.MARK_COLLECTED,
        )
    elif tx.status == TransactionStatus.COLLECTION_ASSERTED:
        # Make sure the same person doesn't confirm the assertion
        if tx.updated_by_id != user.id:
            # TODO: What's the escape hatch if a dispute arises?
            return (ItemAction.CONFIRM_COLLECTED,)
        else:
            # Otherwise, nothing to do but wait...
            return tuple()
    elif tx.status == TransactionStatus.COLLECTED:
        # Either borrower or lender can mark the item returned. The lender
        # has it back in hand, so their mark closes the loan immediately;
        # the borrower's is only an assertion pending the lender's
        # confirmation. The lender can also request the item back, or
        # give it away.
        if item.owner_id == user.id:
            return (
                ItemAction.CONFIRM_RETURNED,
                ItemAction.REQUEST_RETURN,
                ItemAction.OFFER_GIVEAWAY,
            )
        return (ItemAction.MARK_RETURNED,)
    elif tx.status == TransactionStatus.GIVEAWAY_OFFERED:
        # The borrower decides whether to accept the gift.
        # The lender waits on that decision.
        if item.owner_id == user.id:
            return tuple()
        return (ItemAction.ACCEPT_GIVEAWAY, ItemAction.DECLINE_GIVEAWAY)
    elif tx.status == TransactionStatus.RETURN_REQUESTED:
        if item.owner_id == user.id:
            # The lender can escalate to a dispute only if the wait window has passed
            if tx.dispute_wait_has_elapsed(now):
                return (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED)
            return (ItemAction.CONFIRM_RETURNED,)
        # The borrower confirms the return or flags that they can't return the item.
        return (ItemAction.MARK_RETURNED, ItemAction.FLAG_CANNOT_RETURN)
    elif tx.status == TransactionStatus.RETURN_ASSERTED:
        # Reached only via the borrower's assertion -- the lender's
        # mark closes the loan directly without passing through this
        # status. Make sure the same person doesn't confirm the assertion.
        if tx.updated_by_id != user.id:
            if item.owner_id == user.id:
                # The lender can deny the borrower's return claim.
                return (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED)
            return (ItemAction.CONFIRM_RETURNED,)
        else:
            # Otherwise, nothing to do but wait...
            return tuple()
    elif tx.status == TransactionStatus.DISPUTED:
        if item.owner_id == user.id:
            # The lender settles the dispute one way or the other.
            return (
                ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
                ItemAction.RESOLVE_DISPUTE_RETURNED,
            )
        # The borrower waits on the lender. (no options for borrower)
        return tuple()
    else:
        # We shouldn't get here...
        raise ValueError(
            f"Unexpected Transaction status '{tx.status}' for Item '{item}' and User '{user}'"
        )


def comparison_counts() -> dict[tuple[str, str, Actions], int]:
    """How often each (status, role, served actions) has been compared here."""
    return dict(_comparisons)


def _raises_on_divergence() -> bool:
    # Django's test runner forces DEBUG off, so tests need their own signal.
    return bool(settings.DEBUG or settings.IS_RUNNING_MANAGE_PY_TESTS)


def _compare_with_table(
    item: Item, tx: Transaction, user: BorrowdUser, now: datetime, served: Actions
) -> None:
    strict = _raises_on_divergence()
    try:
        from_table = available_actions(tx, user, now=now)
    except Exception as exc:
        if strict:
            raise
        sentry_sdk.capture_exception(exc)
        return

    status = TransactionStatus(tx.status).name
    role = "lender" if user.pk == tx.party1_id else "borrower"
    _count_comparison(status, role, served, log=not strict)
    if from_table == served:
        return

    kind = LENDER_IS_NOT_OWNER if tx.party1_id != item.owner_id else ACTIONS_DIFFER
    context = {
        "kind": kind,
        "item_id": item.pk,
        "transaction_id": tx.pk,
        "status": status,
        "role": role,
        "served": [action.value for action in served],
        "table": [action.value for action in from_table],
    }
    if strict:
        raise AssertionError(f"Item flow divergence: {context}")
    if _should_report((kind, status, role, served, from_table)):
        with sentry_sdk.new_scope() as scope:
            scope.set_context("item_flow_parity", context)
            sentry_sdk.capture_message(f"Item flow divergence: {kind}", level="error")


def _count_comparison(status: str, role: str, served: Actions, *, log: bool) -> None:
    key = (status, role, served)
    _comparisons[key] += 1
    if log and _comparisons[key] == 1:
        # One line per combination per process: enough to tell afterwards
        # which states real traffic actually exercised.
        logger.info(
            "item flow parity first compared: status=%s role=%s served=%s",
            status,
            role,
            ",".join(action.value for action in served) or "-",
        )


def _should_report(shape: tuple[object, ...]) -> bool:
    """One report per divergence shape per hour, so a list page cannot flood."""
    moment = time.monotonic()
    if _reported_until.get(shape, 0.0) > moment:
        return False
    if len(_reported_until) >= _REPORT_CACHE_SIZE:
        for stale in [k for k, until in _reported_until.items() if until <= moment]:
            del _reported_until[stale]
        if len(_reported_until) >= _REPORT_CACHE_SIZE:
            _reported_until.clear()
    _reported_until[shape] = moment + _REPORT_TTL_SECONDS
    return True
