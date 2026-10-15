"""
Tests for TransactionStatusChange: the history row process_action() writes
whenever a Transaction is created or its status changes.
"""

from django.test import TestCase

from borrowd_items.flow import TRANSITIONS
from borrowd_items.models import (
    DUAL_CONFIRMATION_TRANSACTION_STATUSES,
    Item,
    ItemAction,
    ListingType,
    Transaction,
    TransactionStatus,
    TransactionStatusChange,
)
from borrowd_users.models import BorrowdUser

from .test_item_lifecycle_writes import EXPECTED_WRITES


class TransactionCreationHistoryTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="tsh_owner", email="tsh_owner@example.com", password="password"
        )
        self.requester = BorrowdUser.objects.create_user(
            username="tsh_requester",
            email="tsh_requester@example.com",
            password="password",
        )

    def _item(self, listing_type: int) -> Item:
        return Item.objects.create(
            name="Drill",
            description="A useful thing",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            listing_type=listing_type,
        )

    def test_request_item_writes_one_creation_row(self) -> None:
        item = self._item(ListingType.LEND)
        item.process_action(user=self.requester, action=ItemAction.REQUEST_ITEM)

        txn = Transaction.objects.get(item=item)
        history = list(TransactionStatusChange.objects.filter(transaction=txn))
        self.assertEqual(len(history), 1)
        change = history[0]
        self.assertIsNone(change.from_status)
        self.assertEqual(change.to_status, TransactionStatus.REQUESTED)
        self.assertEqual(change.action, ItemAction.REQUEST_ITEM)
        self.assertEqual(change.actor_id, self.requester.pk)
        self.assertIsNone(change.resolution_reason)
        self.assertFalse(change.backfilled)

    def test_request_giveaway_writes_one_creation_row(self) -> None:
        item = self._item(ListingType.GIVEAWAY)
        item.process_action(user=self.requester, action=ItemAction.REQUEST_GIVEAWAY)

        txn = Transaction.objects.get(item=item)
        history = list(TransactionStatusChange.objects.filter(transaction=txn))
        self.assertEqual(len(history), 1)
        change = history[0]
        self.assertIsNone(change.from_status)
        self.assertEqual(change.to_status, TransactionStatus.GIVEAWAY_REQUESTED)
        self.assertEqual(change.action, ItemAction.REQUEST_GIVEAWAY)
        self.assertEqual(change.actor_id, self.requester.pk)


class TransitionCoverageTests(TestCase):
    """
    Every transition in the flow.py rules table must be exercised, with
    history-row assertions, by one of the driving tests elsewhere. This
    doesn't run process_action() itself -- it only checks that no transition
    was added to TRANSITIONS without a corresponding driving case, so a
    future transition can't silently go untested.
    """

    def test_every_transition_is_exercised_somewhere(self) -> None:
        covered = {(write.source, write.action) for write in EXPECTED_WRITES}
        covered |= {
            (status, ItemAction.RESOLVE_TRANSACTION)
            for status in DUAL_CONFIRMATION_TRANSACTION_STATUSES
        }

        gaps = {
            (t.source, t.action)
            for t in TRANSITIONS
            if (t.source, t.action) not in covered
        }
        self.assertEqual(
            gaps,
            set(),
            "Transitions in flow.TRANSITIONS with no driving test case for "
            "TransactionStatusChange coverage. Add a case to EXPECTED_WRITES "
            "in test_item_lifecycle_writes.py, or to the inactive-counterparty "
            "states if it's a RESOLVE_TRANSACTION transition.",
        )
