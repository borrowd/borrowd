"""Lifecycle writers on separate connections take turns instead of colliding."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as StillWaiting
from threading import Barrier, Event
from typing import Any
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from guardian.shortcuts import assign_perm

from borrowd_groups.models import BorrowdGroup
from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.models import (
    OPEN_TRANSACTION_STATUSES,
    Item,
    ItemAction,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_messaging.models import ChatThread
from borrowd_permissions.models import ItemOLP
from borrowd_users import services
from borrowd_users.models import BorrowdUser
from borrowd_users.services import soft_delete_account
from borrowd_users.system import SYSTEM_USER_USERNAME


class Hold:
    """Stops a writer inside its database transaction until released."""

    def __init__(self) -> None:
        self.reached = Event()
        self.release = Event()

    def __call__(self) -> None:
        self.reached.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("Timed out holding the database transaction.")


def on_its_own_connection[T](work: Callable[[], T]) -> Callable[[], T]:
    def run() -> T:
        close_old_connections()
        try:
            return work()
        finally:
            connections.close_all()

    return run


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks.")
class LifecycleConcurrencyTests(TransactionTestCase):
    def setUp(self) -> None:
        # TransactionTestCase truncates migration data, so make the system user here.
        BorrowdUser.objects.get_or_create(username=SYSTEM_USER_USERNAME)
        self.owner = self.make_user("race-owner")
        self.borrower = self.make_user("race-borrower")
        self.item = self.make_item(self.owner)

    @staticmethod
    def make_user(username: str) -> BorrowdUser:
        return BorrowdUser.objects.create_user(
            username=username, email=f"{username}@example.com", password="password"
        )

    @staticmethod
    def make_item(owner: BorrowdUser) -> Item:
        return Item.objects.create(
            name="Drill",
            description="A drill",
            owner=owner,
            created_by=owner,
            updated_by=owner,
        )

    @staticmethod
    def make_transaction(
        item: Item, borrower: BorrowdUser, status: TransactionStatus
    ) -> Transaction:
        return Transaction.objects.create(
            item=item,
            party1=item.owner,
            party2=borrower,
            status=status,
            created_by=borrower,
            updated_by=borrower,
        )

    def act(
        self, user: BorrowdUser, action: ItemAction, item: Item
    ) -> Callable[[], str]:
        def run() -> str:
            try:
                Item.objects.get(pk=item.pk).process_action(user, action)
            except InvalidItemAction:
                return "refused"
            return "done"

        return run

    def close_account(self, user: BorrowdUser) -> Callable[[], None]:
        def run() -> None:
            leaving = BorrowdUser.objects.get(pk=user.pk)
            soft_delete_account(leaving, deleted_by=leaving)

        return run

    def delete_item(self) -> int:
        client = Client()
        client.force_login(self.owner)
        return client.post(reverse("item-delete", args=[self.item.pk])).status_code

    def run_behind[T, U](
        self, hold: Hold, first: Callable[[], T], second: Callable[[], U]
    ) -> tuple[T, U]:
        """Start `second` while `first` is held, and check that it waits."""
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                holding = executor.submit(on_its_own_connection(first))
                self.assertTrue(hold.reached.wait(timeout=10))
                waiting = executor.submit(on_its_own_connection(second))
                with self.assertRaises(StillWaiting):
                    waiting.result(timeout=0.5)
            finally:
                hold.release.set()
            return holding.result(timeout=10), waiting.result(timeout=10)

    def run_together[T](self, *work: Callable[[], T]) -> list[T]:
        with ThreadPoolExecutor(max_workers=len(work)) as executor:
            running = [executor.submit(on_its_own_connection(each)) for each in work]
            return [future.result(timeout=20) for future in running]

    def held_inside(self, target: Any, name: str, hold: Hold) -> Any:
        """Patch `target.name` to stop at `hold` before doing its work."""
        original = getattr(target, name)

        def held(*args: Any, **kwargs: Any) -> Any:
            hold()
            return original(*args, **kwargs)

        return patch.object(target, name, autospec=True, side_effect=held)

    def open_transactions(self, **filters: Any) -> int:
        return Transaction.objects.filter(
            status__in=OPEN_TRANSACTION_STATUSES, **filters
        ).count()

    def test_lender_and_borrower_acting_at_once_both_finish(self) -> None:
        tx = self.make_transaction(self.item, self.borrower, TransactionStatus.ACCEPTED)
        both_hold_their_gate = Barrier(2, timeout=10)
        lock = Item.lock_for_update

        def lock_once_both_are_gated(pk: int, **kwargs: Any) -> Item:
            both_hold_their_gate.wait()
            return lock(pk, **kwargs)

        with patch.object(
            Item, "lock_for_update", side_effect=lock_once_both_are_gated
        ):
            outcomes = self.run_together(
                self.act(self.owner, ItemAction.MARK_COLLECTED, self.item),
                self.act(self.borrower, ItemAction.MARK_COLLECTED, self.item),
            )

        # The winner notifies the other party while that party holds its own
        # gate. Neither is aborted; the loser finds collection already marked.
        self.assertCountEqual(outcomes, ["done", "refused"])
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.COLLECTION_ASSERTED)

    def test_a_request_made_during_an_item_delete_is_refused(self) -> None:
        hold = Hold()
        with self.held_inside(Item, "soft_delete", hold):
            _, request = self.run_behind(
                hold,
                self.delete_item,
                self.act(self.borrower, ItemAction.REQUEST_ITEM, self.item),
            )

        self.assertEqual(request, "refused")
        self.assertIsNotNone(Item.all_objects.get(pk=self.item.pk).deleted_at)
        self.assertEqual(self.open_transactions(item=self.item), 0)

    def test_a_delete_made_during_a_request_leaves_the_item(self) -> None:
        hold = Hold()
        with self.held_inside(Transaction.objects, "create", hold):
            request, _ = self.run_behind(
                hold,
                self.act(self.borrower, ItemAction.REQUEST_ITEM, self.item),
                self.delete_item,
            )

        self.assertEqual(request, "done")
        self.item.refresh_from_db()
        self.assertIsNone(self.item.deleted_at)
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)

    def test_a_closing_borrower_cannot_make_a_new_request(self) -> None:
        cancelled = self.make_transaction(
            self.item, self.borrower, TransactionStatus.REQUESTED
        )
        another_item = self.make_item(self.owner)
        hold = Hold()
        with self.held_inside(services, "_cancel_open_transactions", hold):
            _, request = self.run_behind(
                hold,
                self.close_account(self.borrower),
                self.act(self.borrower, ItemAction.REQUEST_ITEM, another_item),
            )

        self.assertEqual(request, "refused")
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, TransactionStatus.CANCELLED)
        self.assertEqual(self.open_transactions(party2=self.borrower), 0)

    def test_a_closing_owners_item_cannot_be_requested(self) -> None:
        hold = Hold()
        with self.held_inside(services, "_cancel_open_transactions", hold):
            _, request = self.run_behind(
                hold,
                self.close_account(self.owner),
                self.act(self.borrower, ItemAction.REQUEST_ITEM, self.item),
            )

        self.assertEqual(request, "refused")
        self.assertEqual(self.open_transactions(party1=self.owner), 0)

    def test_two_accounts_closing_at_once_both_finish(self) -> None:
        # Each has a request open on the other's item, so both lock both items.
        borrowers_item = self.make_item(self.borrower)
        self.make_transaction(self.item, self.borrower, TransactionStatus.REQUESTED)
        self.make_transaction(borrowers_item, self.owner, TransactionStatus.REQUESTED)
        both_hold_their_gate = Barrier(2, timeout=10)
        lock_items = services._lock_items_involving

        def lock_once_both_are_gated(user: BorrowdUser) -> None:
            both_hold_their_gate.wait()
            lock_items(user)

        with patch.object(
            services, "_lock_items_involving", side_effect=lock_once_both_are_gated
        ):
            self.run_together(
                self.close_account(self.owner), self.close_account(self.borrower)
            )

        self.assertEqual(self.open_transactions(), 0)
        self.assertFalse(Item.objects.exists())
        self.assertFalse(
            BorrowdUser.objects.filter(username__startswith="race-").exists()
        )

    @override_settings(MESSAGING_ENABLED=True)
    def test_a_conversation_prepared_during_an_item_delete_is_not_kept(self) -> None:
        group = BorrowdGroup.objects.create_group(
            name="Group",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )
        group.add_user(self.borrower)
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)

        def request_through_the_view() -> int:
            client = Client()
            client.force_login(self.borrower)
            return client.post(
                reverse("item-borrow", args=[self.item.pk]),
                {"action": ItemAction.REQUEST_ITEM},
            ).status_code

        hold = Hold()
        with self.held_inside(Item, "soft_delete", hold):
            self.run_behind(hold, self.delete_item, request_through_the_view)

        self.assertIsNotNone(Item.all_objects.get(pk=self.item.pk).deleted_at)
        self.assertEqual(self.open_transactions(item=self.item), 0)
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
