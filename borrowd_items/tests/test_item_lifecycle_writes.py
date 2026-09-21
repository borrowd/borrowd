"""
What each lifecycle action writes, pinned.

`Item.status` is a summary of the item's current transaction, but every action
has historically set it by hand, which is how the two drift. This table is the
record of what the hand-written version does, so that routing those writes
through a single projection can be shown to change nothing.

Arranging a starting state by assigning `status` directly is fine here; the
assertions are about what `process_action` writes, not how we got there.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from borrowd_items.models import (
    Item,
    ItemAction,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser

LENDER = "lender"
BORROWER = "borrower"


@contextmanager
def rolled_back() -> Iterator[None]:
    """Undo a case's rows so the next one starts from a clean item."""
    with transaction.atomic():
        yield
        transaction.set_rollback(True)


@dataclass(frozen=True)
class LifecycleWrite:
    """One action applied to one starting state, and everything it writes."""

    source: TransactionStatus
    action: ItemAction
    actor: str
    item_status_before: ItemStatus
    transaction_status_after: TransactionStatus
    item_status_after: ItemStatus
    # Who touched the transaction last. Dual-confirmation steps refuse to let
    # the same party both assert and confirm.
    updated_by: str = LENDER
    # Set return_requested_at this far in the past, for the dispute wait.
    return_requested_days_ago: int | None = None
    # Transaction fields that must be non-null once the action has run.
    stamps: tuple[str, ...] = ()
    item_soft_deleted_after: bool = False
    owner_after: str = LENDER
    label: str = field(default="", compare=False)


EXPECTED_WRITES: tuple[LifecycleWrite, ...] = (
    # -- a request awaiting the owner's decision -------------------------
    LifecycleWrite(
        TransactionStatus.REQUESTED,
        ItemAction.REJECT_REQUEST,
        LENDER,
        ItemStatus.REQUESTED,
        TransactionStatus.REJECTED,
        ItemStatus.AVAILABLE,
    ),
    LifecycleWrite(
        TransactionStatus.REQUESTED,
        ItemAction.ACCEPT_REQUEST,
        LENDER,
        ItemStatus.REQUESTED,
        TransactionStatus.ACCEPTED,
        ItemStatus.RESERVED,
    ),
    LifecycleWrite(
        TransactionStatus.REQUESTED,
        ItemAction.CANCEL_REQUEST,
        BORROWER,
        ItemStatus.REQUESTED,
        TransactionStatus.CANCELLED,
        ItemStatus.AVAILABLE,
    ),
    # -- a giveaway request ----------------------------------------------
    LifecycleWrite(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.DECLINE_GIVEAWAY_REQUEST,
        LENDER,
        ItemStatus.REQUESTED,
        TransactionStatus.REJECTED,
        ItemStatus.AVAILABLE,
    ),
    LifecycleWrite(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.APPROVE_GIVEAWAY_REQUEST,
        LENDER,
        ItemStatus.REQUESTED,
        TransactionStatus.OWNERSHIP_TRANSFERRED,
        ItemStatus.AVAILABLE,
        owner_after=BORROWER,
    ),
    LifecycleWrite(
        TransactionStatus.GIVEAWAY_REQUESTED,
        ItemAction.CANCEL_REQUEST,
        BORROWER,
        ItemStatus.REQUESTED,
        TransactionStatus.CANCELLED,
        ItemStatus.AVAILABLE,
    ),
    # -- accepted, item not yet handed over ------------------------------
    LifecycleWrite(
        TransactionStatus.ACCEPTED,
        ItemAction.MARK_COLLECTED,
        LENDER,
        ItemStatus.RESERVED,
        TransactionStatus.COLLECTION_ASSERTED,
        ItemStatus.RESERVED,
    ),
    LifecycleWrite(
        TransactionStatus.ACCEPTED,
        ItemAction.MARK_COLLECTED,
        BORROWER,
        ItemStatus.RESERVED,
        TransactionStatus.COLLECTION_ASSERTED,
        ItemStatus.RESERVED,
    ),
    LifecycleWrite(
        TransactionStatus.ACCEPTED,
        ItemAction.CANCEL_REQUEST,
        BORROWER,
        ItemStatus.RESERVED,
        TransactionStatus.CANCELLED,
        ItemStatus.AVAILABLE,
    ),
    # -- collection asserted, awaiting the other party --------------------
    LifecycleWrite(
        TransactionStatus.COLLECTION_ASSERTED,
        ItemAction.CONFIRM_COLLECTED,
        BORROWER,
        ItemStatus.RESERVED,
        TransactionStatus.COLLECTED,
        ItemStatus.BORROWED,
        updated_by=LENDER,
    ),
    # -- collected --------------------------------------------------------
    LifecycleWrite(
        TransactionStatus.COLLECTED,
        ItemAction.CONFIRM_RETURNED,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURNED,
        ItemStatus.AVAILABLE,
        updated_by=BORROWER,
    ),
    LifecycleWrite(
        TransactionStatus.COLLECTED,
        ItemAction.REQUEST_RETURN,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURN_REQUESTED,
        ItemStatus.BORROWED,
        stamps=("return_requested_at",),
    ),
    LifecycleWrite(
        TransactionStatus.COLLECTED,
        ItemAction.OFFER_GIVEAWAY,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.GIVEAWAY_OFFERED,
        ItemStatus.BORROWED,
    ),
    LifecycleWrite(
        TransactionStatus.COLLECTED,
        ItemAction.MARK_RETURNED,
        BORROWER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURN_ASSERTED,
        ItemStatus.BORROWED,
    ),
    # -- giveaway offered mid-loan ----------------------------------------
    LifecycleWrite(
        TransactionStatus.GIVEAWAY_OFFERED,
        ItemAction.ACCEPT_GIVEAWAY,
        BORROWER,
        ItemStatus.BORROWED,
        TransactionStatus.OWNERSHIP_TRANSFERRED,
        ItemStatus.AVAILABLE,
        owner_after=BORROWER,
    ),
    LifecycleWrite(
        TransactionStatus.GIVEAWAY_OFFERED,
        ItemAction.DECLINE_GIVEAWAY,
        BORROWER,
        ItemStatus.BORROWED,
        TransactionStatus.COLLECTED,
        ItemStatus.BORROWED,
    ),
    # -- return requested --------------------------------------------------
    LifecycleWrite(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.CONFIRM_RETURNED,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURNED,
        ItemStatus.AVAILABLE,
        updated_by=BORROWER,
        return_requested_days_ago=0,
    ),
    LifecycleWrite(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.MARK_RETURNED,
        BORROWER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURN_ASSERTED,
        ItemStatus.BORROWED,
        return_requested_days_ago=0,
    ),
    LifecycleWrite(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.FLAG_CANNOT_RETURN,
        BORROWER,
        ItemStatus.BORROWED,
        TransactionStatus.DISPUTED,
        ItemStatus.BORROWED,
        return_requested_days_ago=0,
        stamps=("disputed_at", "dispute_raised_by"),
    ),
    LifecycleWrite(
        TransactionStatus.RETURN_REQUESTED,
        ItemAction.RAISE_DISPUTE,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.DISPUTED,
        ItemStatus.BORROWED,
        return_requested_days_ago=settings.RETURN_DISPUTE_WAIT_DAYS + 1,
        stamps=("disputed_at", "dispute_raised_by"),
    ),
    # -- return asserted ---------------------------------------------------
    LifecycleWrite(
        TransactionStatus.RETURN_ASSERTED,
        ItemAction.CONFIRM_RETURNED,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURNED,
        ItemStatus.AVAILABLE,
        updated_by=BORROWER,
    ),
    LifecycleWrite(
        TransactionStatus.RETURN_ASSERTED,
        ItemAction.RAISE_DISPUTE,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.DISPUTED,
        ItemStatus.BORROWED,
        updated_by=BORROWER,
        stamps=("disputed_at", "dispute_raised_by"),
    ),
    # -- disputed ----------------------------------------------------------
    LifecycleWrite(
        TransactionStatus.DISPUTED,
        ItemAction.RESOLVE_DISPUTE_RETURNED,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RETURNED,
        ItemStatus.AVAILABLE,
    ),
    LifecycleWrite(
        TransactionStatus.DISPUTED,
        ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
        LENDER,
        ItemStatus.BORROWED,
        TransactionStatus.RESOLVED,
        ItemStatus.BORROWED,
        item_soft_deleted_after=True,
    ),
)


class ItemLifecycleWriteTests(TestCase):
    def setUp(self) -> None:
        self.lender = BorrowdUser.objects.create_user(
            username="lw_lender", email="lw_lender@example.com", password="password"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="lw_borrower", email="lw_borrower@example.com", password="password"
        )

    def _party(self, name: str) -> BorrowdUser:
        return self.lender if name == LENDER else self.borrower

    def test_every_open_status_has_at_least_one_recorded_action(self) -> None:
        """A status nobody can act on is a dead end; catch that here."""
        from borrowd_items.models import OPEN_TRANSACTION_STATUSES

        covered = {write.source for write in EXPECTED_WRITES}
        self.assertEqual(covered, set(OPEN_TRANSACTION_STATUSES))

    def test_recorded_writes(self) -> None:
        for write in EXPECTED_WRITES:
            name = f"{write.source.name} + {write.action} by {write.actor}"
            with self.subTest(name), rolled_back():
                item = Item.objects.create(
                    name="Drill",
                    description="A useful thing",
                    owner=self.lender,
                    status=write.item_status_before,
                    created_by=self.lender,
                    updated_by=self.lender,
                )
                txn = Transaction.objects.create(
                    item=item,
                    party1=self.lender,
                    party2=self.borrower,
                    status=write.source,
                    created_by=self.lender,
                    updated_by=self._party(write.updated_by),
                )
                if write.return_requested_days_ago is not None:
                    txn.return_requested_at = timezone.now() - timedelta(
                        days=write.return_requested_days_ago
                    )
                    txn.save(update_fields=("return_requested_at",))

                item.process_action(user=self._party(write.actor), action=write.action)

                txn.refresh_from_db()
                item.refresh_from_db()
                self.assertEqual(
                    txn.status, write.transaction_status_after, f"{name}: tx status"
                )
                self.assertEqual(
                    item.status, write.item_status_after, f"{name}: item status"
                )
                self.assertEqual(
                    item.owner_id,
                    self._party(write.owner_after).pk,
                    f"{name}: item owner",
                )
                self.assertEqual(
                    item.deleted_at is not None,
                    write.item_soft_deleted_after,
                    f"{name}: item soft-deleted",
                )
                for stamp in write.stamps:
                    self.assertIsNotNone(getattr(txn, stamp), f"{name}: {stamp}")
