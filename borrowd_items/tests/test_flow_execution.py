"""Verify transition writes, invalid actions, and database rollback."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.conf import settings
from django.test import TestCase

from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.flow import TRANSITIONS, Actor, Transition, execute_transition
from borrowd_items.models import (
    ITEM_STATUS_FOR_TRANSACTION,
    Item,
    ItemAction,
    ItemStatus,
    ResolutionReason,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc)
WAIT = timedelta(days=settings.RETURN_DISPUTE_WAIT_DAYS)


class ExecutionTestCase(TestCase):
    lender: BorrowdUser
    borrower: BorrowdUser
    bystander: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.lender = BorrowdUser.objects.create_user(
            username="fx_lender", email="fx_lender@example.com", password="password"
        )
        cls.borrower = BorrowdUser.objects.create_user(
            username="fx_borrower", email="fx_borrower@example.com", password="password"
        )
        cls.bystander = BorrowdUser.objects.create_user(
            username="fx_bystander",
            email="fx_bystander@example.com",
            password="password",
        )

    def open_transaction(
        self,
        status: TransactionStatus,
        *,
        updated_by: BorrowdUser | None = None,
    ) -> tuple[Item, Transaction]:
        item = Item.objects.create(
            name="Drill",
            description="A useful thing",
            owner=self.lender,
            status=ITEM_STATUS_FOR_TRANSACTION[status],
            created_by=self.lender,
            updated_by=self.lender,
        )
        tx = Transaction.objects.create(
            item=item,
            party1=self.lender,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=updated_by or self.borrower,
            return_requested_at=NOW - WAIT,
        )
        return item, tx

    def assert_untouched(self, tx: Transaction, status: TransactionStatus) -> None:
        stored = Transaction.objects.get(pk=tx.pk)
        self.assertEqual(stored.status, status)
        self.assertIsNone(stored.resolution_reason)


class ExecuteTransitionTests(ExecutionTestCase):
    def test_returns_the_transition_it_applied(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.REQUESTED)
        applied = execute_transition(
            item, tx, self.lender, ItemAction.ACCEPT_REQUEST, now=NOW
        )
        self.assertIsInstance(applied, Transition)
        self.assertEqual(applied.source, TransactionStatus.REQUESTED)
        self.assertEqual(applied.target, TransactionStatus.ACCEPTED)
        tx.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.ACCEPTED)
        self.assertEqual(tx.updated_by_id, self.lender.pk)
        self.assertEqual(item.status, ItemStatus.RESERVED)

    def test_refuses_an_action_that_belongs_to_the_other_party(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.REQUESTED)
        with self.assertRaises(InvalidItemAction):
            execute_transition(
                item, tx, self.borrower, ItemAction.ACCEPT_REQUEST, now=NOW
            )
        self.assert_untouched(tx, TransactionStatus.REQUESTED)

    def test_refuses_someone_who_is_not_a_party(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.ACCEPTED)
        with self.assertRaises(InvalidItemAction):
            execute_transition(
                item, tx, self.bystander, ItemAction.MARK_COLLECTED, now=NOW
            )
        self.assert_untouched(tx, TransactionStatus.ACCEPTED)

    def test_refuses_everything_on_a_finished_transaction(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.RETURNED)
        for action in ItemAction:
            with self.subTest(action=action.value):
                with self.assertRaises(InvalidItemAction):
                    execute_transition(item, tx, self.lender, action, now=NOW)
        self.assert_untouched(tx, TransactionStatus.RETURNED)

    def test_refuses_ordinary_actions_once_the_counterparty_is_gone(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.COLLECTED)
        self.borrower.is_active = False
        self.borrower.save(update_fields=("is_active",))
        with self.assertRaises(InvalidItemAction):
            execute_transition(
                item, tx, self.lender, ItemAction.CONFIRM_RETURNED, now=NOW
            )
        self.assert_untouched(tx, TransactionStatus.COLLECTED)

    def test_refuses_the_one_who_asserted_a_step_confirming_it(self) -> None:
        item, tx = self.open_transaction(
            TransactionStatus.COLLECTION_ASSERTED, updated_by=self.lender
        )
        with self.assertRaises(InvalidItemAction):
            execute_transition(
                item, tx, self.lender, ItemAction.CONFIRM_COLLECTED, now=NOW
            )
        self.assert_untouched(tx, TransactionStatus.COLLECTION_ASSERTED)

    def test_stamps_carry_the_time_it_was_given(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.COLLECTED)
        execute_transition(item, tx, self.lender, ItemAction.REQUEST_RETURN, now=NOW)
        tx.refresh_from_db()
        self.assertEqual(tx.return_requested_at, NOW)

        later = NOW + timedelta(hours=1)
        execute_transition(
            item, tx, self.borrower, ItemAction.FLAG_CANNOT_RETURN, now=later
        )
        tx.refresh_from_db()
        self.assertEqual(tx.disputed_at, later)
        self.assertEqual(tx.dispute_raised_by_id, self.borrower.pk)

    def test_a_failing_effect_leaves_nothing_behind(self) -> None:
        item, tx = self.open_transaction(TransactionStatus.GIVEAWAY_OFFERED)
        with mock.patch.object(
            Item, "_transfer_ownership", side_effect=RuntimeError("no")
        ):
            with self.assertRaises(RuntimeError):
                execute_transition(
                    item, tx, self.borrower, ItemAction.ACCEPT_GIVEAWAY, now=NOW
                )
        self.assert_untouched(tx, TransactionStatus.GIVEAWAY_OFFERED)
        stored_item = Item.objects.get(pk=item.pk)
        self.assertEqual(stored_item.owner_id, self.lender.pk)
        self.assertEqual(stored_item.status, ItemStatus.BORROWED)

    def test_a_lost_item_is_removed_only_after_its_transaction_is_resolved(
        self,
    ) -> None:
        item, tx = self.open_transaction(TransactionStatus.DISPUTED)
        seen: list[tuple[int, str | None]] = []
        remove = Item.soft_delete

        def spy(self_item: Item, deleted_by: BorrowdUser) -> None:
            stored = Transaction.objects.get(pk=tx.pk)
            seen.append((stored.status, stored.resolution_reason))
            remove(self_item, deleted_by)

        with mock.patch.object(Item, "soft_delete", spy):
            execute_transition(
                item,
                tx,
                self.lender,
                ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
                now=NOW,
            )
        self.assertEqual(
            seen,
            [(TransactionStatus.RESOLVED, ResolutionReason.DISPUTE_ITEM_NOT_RETURNED)],
        )
        self.assertIsNotNone(Item.all_objects.get(pk=item.pk).deleted_at)


class EveryRowDoesWhatItsTargetImpliesTests(ExecutionTestCase):
    """Check each transition's status, timestamps, resolution reason, and ownership."""

    def test_each_transition_leaves_a_consistent_record(self) -> None:
        for spec in TRANSITIONS:
            name = f"{spec.source.name} + {spec.action.value}"
            with self.subTest(name):
                actor = self.borrower if spec.actor is Actor.BORROWER else self.lender
                other = self.lender if actor is self.borrower else self.borrower
                other.is_active = not spec.preempts
                other.save(update_fields=("is_active",))
                item, tx = self.open_transaction(spec.source, updated_by=other)

                applied = execute_transition(item, tx, actor, spec.action, now=NOW)

                self.assertIs(applied, spec)
                tx.refresh_from_db()
                item = Item.all_objects.get(pk=item.pk)
                self.assertEqual(tx.status, spec.target)
                self.assertEqual(tx.updated_by_id, actor.pk)
                if item.deleted_at is None:
                    self.assertEqual(
                        item.status, ITEM_STATUS_FOR_TRANSACTION[spec.target]
                    )
                if spec.target == TransactionStatus.DISPUTED:
                    self.assertEqual(tx.disputed_at, NOW)
                    self.assertEqual(tx.dispute_raised_by_id, actor.pk)
                if spec.target == TransactionStatus.RETURN_REQUESTED:
                    self.assertEqual(tx.return_requested_at, NOW)
                self.assertEqual(
                    tx.resolution_reason is not None,
                    spec.target == TransactionStatus.RESOLVED,
                )
                self.assertEqual(
                    item.owner_id,
                    self.borrower.pk
                    if spec.target == TransactionStatus.OWNERSHIP_TRANSFERRED
                    else self.lender.pk,
                )

                other.is_active = True
                other.save(update_fields=("is_active",))
