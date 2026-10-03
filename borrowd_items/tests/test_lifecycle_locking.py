"""Lifecycle writes decide on current state, not on what the caller loaded."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from notifications.models import Notification

from borrowd_items.admin import ItemAdmin
from borrowd_items.exceptions import InvalidItemAction, TransactionLenderMismatch
from borrowd_items.management.commands.repair_item_statuses import Command
from borrowd_items.models import (
    Item,
    ItemAction,
    ItemCategory,
    ItemStatus,
    ListingType,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser
from borrowd_users.services import soft_delete_account


class LockingTestCase(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser
    other: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower, cls.other = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("lk_owner", "lk_borrower", "lk_other")
        )

    def make_item(self, status: ItemStatus = ItemStatus.AVAILABLE) -> Item:
        return Item.objects.create(
            name="Drill",
            description="A useful thing",
            owner=self.owner,
            status=status,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def make_transaction(self, item: Item, status: TransactionStatus) -> Transaction:
        return Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=self.borrower,
        )


class ProcessActionUsesCurrentStateTests(LockingTestCase):
    def test_an_account_closed_since_the_page_loaded_cannot_act(self) -> None:
        item = self.make_item(ItemStatus.REQUESTED)
        self.make_transaction(item, TransactionStatus.REQUESTED)
        BorrowdUser.objects.filter(pk=self.owner.pk).update(is_active=False)

        self.assertTrue(self.owner.is_active)  # the caller's copy is stale
        with self.assertRaises(InvalidItemAction):
            item.process_action(self.owner, ItemAction.ACCEPT_REQUEST)

    def test_an_item_deleted_since_the_page_loaded_cannot_be_requested(self) -> None:
        item = self.make_item()
        Item.all_objects.filter(pk=item.pk).update(deleted_at=timezone.now())

        self.assertIsNone(item.deleted_at)
        with self.assertRaises(InvalidItemAction):
            item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.assertFalse(Transaction.objects.filter(item=item).exists())

    def test_a_request_made_since_the_page_loaded_is_seen(self) -> None:
        item = self.make_item()
        stale = Item.objects.get(pk=item.pk)
        item.process_action(self.borrower, ItemAction.REQUEST_ITEM)

        self.assertEqual(stale.status, ItemStatus.AVAILABLE)
        with self.assertRaises(InvalidItemAction):
            stale.process_action(self.other, ItemAction.REQUEST_ITEM)
        self.assertEqual(Transaction.objects.filter(item=item).count(), 1)

    def test_the_callers_copy_is_brought_up_to_date(self) -> None:
        item = self.make_item()
        item.process_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.assertEqual(item.status, ItemStatus.REQUESTED)

    def test_an_open_transaction_whose_lender_is_not_the_owner_is_refused(
        self,
    ) -> None:
        item = self.make_item(ItemStatus.RESERVED)
        tx = self.make_transaction(item, TransactionStatus.ACCEPTED)
        Item.objects.filter(pk=item.pk).update(owner=self.other)

        with self.assertLogs("borrowd.items", level="ERROR"):
            with self.assertRaises(TransactionLenderMismatch):
                item.process_action(self.borrower, ItemAction.MARK_COLLECTED)
        tx.refresh_from_db()
        self.assertEqual(tx.status, TransactionStatus.ACCEPTED)


class ItemViewsRecheckUnderTheLockTests(LockingTestCase):
    def setUp(self) -> None:
        self.client.force_login(self.owner)
        self.item = self.make_item()
        tools = ItemCategory.objects.create(name="Tools")
        self.item.categories.add(tools)
        self.form_data = {
            "name": "Hammer drill",
            "description": "Renamed",
            "categories": [tools.pk],
            "listing_type": ListingType.LEND,
            "share_with_all_groups": "on",
        }

    @contextmanager
    def arrives_while_locking(self, change: Callable[[], None]) -> Iterator[None]:
        """Run `change` at the moment the view takes the item lock."""
        lock = Item.lock_for_update

        def lock_after_change(pk: int, **kwargs: Any) -> Item:
            change()
            return lock(pk, **kwargs)

        with mock.patch.object(Item, "lock_for_update", side_effect=lock_after_change):
            yield

    def request_arrives(self) -> None:
        self.make_transaction(self.item, TransactionStatus.REQUESTED)
        Item.objects.filter(pk=self.item.pk).update(status=ItemStatus.REQUESTED)

    def test_an_edit_does_not_write_back_a_status_it_loaded_earlier(self) -> None:
        with self.arrives_while_locking(self.request_arrives):
            response = self.client.post(
                reverse("item-edit", args=[self.item.pk]), self.form_data
            )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Hammer drill")
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)
        self.assertEqual(self.item.updated_by_id, self.owner.pk)

    def test_a_request_that_arrives_first_blocks_the_delete(self) -> None:
        with self.arrives_while_locking(self.request_arrives):
            self.client.post(reverse("item-delete", args=[self.item.pk]))
        self.assertIsNone(Item.all_objects.get(pk=self.item.pk).deleted_at)

    def test_an_item_with_an_open_transaction_is_not_deleted(self) -> None:
        # The stored status has drifted; the transaction still counts.
        self.make_transaction(self.item, TransactionStatus.ACCEPTED)
        self.client.post(reverse("item-delete", args=[self.item.pk]))
        self.assertIsNone(Item.all_objects.get(pk=self.item.pk).deleted_at)

    def test_a_closed_account_cannot_create_an_item(self) -> None:
        closed = BorrowdUser(pk=self.owner.pk, is_active=False)
        with mock.patch.object(BorrowdUser, "lock_account", return_value=closed):
            response = self.client.post(reverse("item-create"), self.form_data)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(name="Hammer drill").exists())


class AccountClosureTests(LockingTestCase):
    def test_closing_an_already_closed_account_does_nothing(self) -> None:
        item = Item.objects.create(
            name="Ladder",
            description="A ladder",
            owner=self.other,
            created_by=self.other,
            updated_by=self.other,
        )
        Transaction.objects.create(
            item=item,
            party1=self.other,
            party2=self.borrower,
            status=TransactionStatus.REQUESTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        soft_delete_account(self.borrower, deleted_by=self.borrower)
        notified = Notification.objects.filter(recipient=self.other).count()

        soft_delete_account(self.borrower, deleted_by=self.borrower)

        self.assertEqual(
            Notification.objects.filter(recipient=self.other).count(), notified
        )


class ItemAdminOwnerTests(LockingTestCase):
    def setUp(self) -> None:
        self.admin = ItemAdmin(Item, AdminSite())
        self.request = RequestFactory().get("/")

    def test_owner_is_read_only_while_a_transaction_is_open(self) -> None:
        idle = self.make_item()
        busy = self.make_item(ItemStatus.REQUESTED)
        self.make_transaction(busy, TransactionStatus.REQUESTED)

        self.assertNotIn("owner", self.admin.get_readonly_fields(self.request, idle))
        self.assertIn("owner", self.admin.get_readonly_fields(self.request, busy))

    def test_an_owner_change_is_refused_if_a_request_arrived_first(self) -> None:
        item = self.make_item()
        form = mock.Mock(changed_data=["owner"])
        self.make_transaction(item, TransactionStatus.REQUESTED)
        item.owner = self.other

        with self.assertRaises(PermissionDenied):
            self.admin.save_model(self.request, item, form, change=True)
        self.assertEqual(Item.objects.get(pk=item.pk).owner_id, self.owner.pk)

    def test_an_item_is_not_handed_to_a_closed_account(self) -> None:
        item = self.make_item()
        form = mock.Mock(changed_data=["owner"])
        BorrowdUser.objects.filter(pk=self.other.pk).update(is_active=False)
        item.owner = self.other

        with self.assertRaises(PermissionDenied):
            self.admin.save_model(self.request, item, form, change=True)
        self.assertEqual(Item.objects.get(pk=item.pk).owner_id, self.owner.pk)

    def test_an_owner_change_on_an_idle_item_is_saved(self) -> None:
        item = self.make_item()
        form = mock.Mock(changed_data=["owner"])
        item.owner = self.other

        self.admin.save_model(self.request, item, form, change=True)
        self.assertEqual(Item.objects.get(pk=item.pk).owner_id, self.other.pk)


class RepairRereadsUnderTheLockTests(LockingTestCase):
    def test_an_item_fixed_since_the_scan_is_left_alone(self) -> None:
        item = self.make_item(ItemStatus.REQUESTED)
        self.make_transaction(item, TransactionStatus.REQUESTED)
        self.assertFalse(Command()._repair(item.pk))

    def test_the_repair_follows_the_transaction_it_finds_now(self) -> None:
        item = self.make_item(ItemStatus.AVAILABLE)
        self.make_transaction(item, TransactionStatus.COLLECTED)
        out = StringIO()
        call_command("repair_item_statuses", stdout=out)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BORROWED)
