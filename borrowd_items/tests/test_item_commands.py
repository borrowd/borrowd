"""Lifecycle commands: stale pages are refused and retries are answered once."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import mock, skipUnless
from uuid import UUID, uuid4

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from notifications.models import Notification

from borrowd_items.commands import CommandResult, ItemCommand, run_item_command
from borrowd_items.exceptions import CommandKeyReused, StaleItemCommand
from borrowd_items.models import (
    Item,
    ItemAction,
    ItemCommandRecord,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser
from borrowd_users.system import SYSTEM_USER_USERNAME


def make_user(username: str) -> BorrowdUser:
    return BorrowdUser.objects.create_user(
        username=username, email=f"{username}@example.com", password="password"
    )


def make_item(owner: BorrowdUser) -> Item:
    return Item.objects.create(
        name="Drill",
        description="A drill",
        owner=owner,
        created_by=owner,
        updated_by=owner,
    )


class CommandTestCase(TestCase):
    owner: BorrowdUser
    alice: BorrowdUser
    bob: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner = make_user("cmd_owner")
        cls.alice = make_user("cmd_alice")
        cls.bob = make_user("cmd_bob")

    def setUp(self) -> None:
        self.item = make_item(self.owner)

    def revision(self) -> int:
        return Item.all_objects.values_list("revision", flat=True).get(pk=self.item.pk)

    def command(
        self,
        actor: BorrowdUser,
        action: ItemAction,
        *,
        key: UUID | None = None,
        revision: int | None = None,
        transaction_id: int | None = None,
    ) -> ItemCommand:
        return ItemCommand(
            actor=actor,
            action=action,
            item_id=self.item.pk,
            expected_revision=revision,
            transaction_id=transaction_id,
            key=key,
        )

    def run_as(
        self,
        actor: BorrowdUser,
        action: ItemAction,
        *,
        key: UUID | None = None,
        revision: int | None = None,
        transaction_id: int | None = None,
    ) -> CommandResult:
        return run_item_command(
            self.command(
                actor,
                action,
                key=key,
                revision=revision,
                transaction_id=transaction_id,
            )
        )


class ItemCommandTests(CommandTestCase):
    def test_a_key_requires_a_revision(self) -> None:
        with self.assertRaisesMessage(ValueError, "requires an expected revision"):
            self.run_as(self.alice, ItemAction.REQUEST_ITEM, key=uuid4())
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())
        self.assertFalse(ItemCommandRecord.objects.exists())

    def test_a_command_reports_what_it_did(self) -> None:
        result = run_item_command(
            self.command(self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=0)
        )

        tx = Transaction.objects.get(item=self.item)
        self.assertEqual(result.transaction_id, tx.pk)
        self.assertEqual(result.transaction_status, TransactionStatus.REQUESTED)
        self.assertEqual(result.revision, self.revision())
        self.assertFalse(result.replayed)

    def test_a_retry_gets_the_same_answer_and_runs_once(self) -> None:
        command = self.command(
            self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=0
        )
        first = run_item_command(command)
        notified = Notification.objects.count()

        again = run_item_command(command)

        self.assertTrue(again.replayed)
        self.assertEqual(again.transaction_id, first.transaction_id)
        self.assertEqual(again.revision, first.revision)
        self.assertEqual(Transaction.objects.filter(item=self.item).count(), 1)
        self.assertEqual(Notification.objects.count(), notified)

    def test_a_retry_is_answered_even_after_the_item_moved_on(self) -> None:
        command = self.command(
            self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=0
        )
        first = run_item_command(command)
        self.item.process_action(self.owner, ItemAction.ACCEPT_REQUEST)

        again = run_item_command(command)

        self.assertTrue(again.replayed)
        self.assertEqual(again.transaction_status, TransactionStatus.REQUESTED)
        self.assertEqual(again.transaction_id, first.transaction_id)

    def test_a_key_sent_with_a_different_command_is_refused(self) -> None:
        key = uuid4()
        run_item_command(
            self.command(self.alice, ItemAction.REQUEST_ITEM, key=key, revision=0)
        )

        with self.assertRaises(CommandKeyReused):
            run_item_command(
                self.command(self.alice, ItemAction.CANCEL_REQUEST, key=key, revision=0)
            )
        self.assertEqual(
            Transaction.objects.get(item=self.item).status,
            TransactionStatus.REQUESTED,
        )

    def test_an_old_accept_does_not_land_on_a_newer_request(self) -> None:
        self.item.process_action(self.alice, ItemAction.REQUEST_ITEM)
        seen_by_owner = self.revision()
        self.item.process_action(self.alice, ItemAction.CANCEL_REQUEST)
        self.item.process_action(self.bob, ItemAction.REQUEST_ITEM)

        with self.assertRaises(StaleItemCommand):
            self.run_as(self.owner, ItemAction.ACCEPT_REQUEST, revision=seen_by_owner)

        self.assertEqual(
            Transaction.objects.get(item=self.item, party2=self.bob).status,
            TransactionStatus.REQUESTED,
        )

    def test_a_status_that_came_back_is_still_stale(self) -> None:
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.alice,
            status=TransactionStatus.COLLECTED,
            created_by=self.alice,
            updated_by=self.alice,
        )
        seen = self.revision()
        self.item.process_action(self.owner, ItemAction.OFFER_GIVEAWAY)
        self.item.process_action(self.alice, ItemAction.DECLINE_GIVEAWAY)

        with self.assertRaises(StaleItemCommand):
            self.run_as(self.alice, ItemAction.MARK_RETURNED, revision=seen)

    def test_a_transaction_the_client_did_not_mean_is_refused(self) -> None:
        self.item.process_action(self.alice, ItemAction.REQUEST_ITEM)
        alices = Transaction.objects.get(item=self.item, party2=self.alice)
        self.item.process_action(self.alice, ItemAction.CANCEL_REQUEST)
        self.item.process_action(self.bob, ItemAction.REQUEST_ITEM)

        with self.assertRaises(StaleItemCommand):
            self.run_as(self.owner, ItemAction.ACCEPT_REQUEST, transaction_id=alices.pk)

    def test_a_refused_command_records_nothing(self) -> None:
        with self.assertRaises(StaleItemCommand):
            self.run_as(self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=9)
        self.assertFalse(ItemCommandRecord.objects.exists())

    def test_a_command_that_fails_midway_leaves_nothing_and_can_run_again(
        self,
    ) -> None:
        command = self.command(
            self.alice, ItemAction.REQUEST_ITEM, key=uuid4(), revision=0
        )
        with mock.patch(
            "borrowd_items.models.sync_item_status", side_effect=RuntimeError
        ):
            with self.assertRaises(RuntimeError):
                run_item_command(command)
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())
        self.assertFalse(ItemCommandRecord.objects.exists())

        result = run_item_command(command)

        self.assertFalse(result.replayed)
        self.assertTrue(Transaction.objects.filter(item=self.item).exists())

    def test_every_successful_command_advances_the_revision(self) -> None:
        steps = (
            (self.alice, ItemAction.REQUEST_ITEM),
            (self.owner, ItemAction.ACCEPT_REQUEST),
            (self.bob, ItemAction.NOTIFY_WHEN_AVAILABLE),
            (self.bob, ItemAction.CANCEL_NOTIFICATION_REQUEST),
            (self.alice, ItemAction.MARK_COLLECTED),
            (self.owner, ItemAction.CONFIRM_COLLECTED),
            (self.alice, ItemAction.MARK_RETURNED),
            (self.owner, ItemAction.CONFIRM_RETURNED),
        )
        for actor, action in steps:
            with self.subTest(action=action.name):
                before = self.revision()
                result = self.run_as(actor, action, key=uuid4(), revision=before)
                self.assertGreater(result.revision, before)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks.")
class ConcurrentCommandTests(TransactionTestCase):
    def test_two_identical_commands_at_once_run_once(self) -> None:
        # TransactionTestCase truncates migration data, so make the system user here.
        BorrowdUser.objects.get_or_create(username=SYSTEM_USER_USERNAME)
        owner = make_user("cmd_race_owner")
        alice = make_user("cmd_race_alice")
        item = make_item(owner)
        command = ItemCommand(
            actor=alice,
            action=ItemAction.REQUEST_ITEM,
            item_id=item.pk,
            key=uuid4(),
            expected_revision=0,
        )
        both_ready = Barrier(2, timeout=10)

        def send() -> CommandResult:
            close_old_connections()
            try:
                both_ready.wait()
                return run_item_command(command)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=20)
                for future in [executor.submit(send) for _ in range(2)]
            ]

        self.assertEqual(sorted(result.replayed for result in results), [False, True])
        self.assertEqual(Transaction.objects.filter(item=item).count(), 1)
