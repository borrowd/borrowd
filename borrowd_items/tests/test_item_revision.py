"""Item.revision advances on every change to the item or its transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from borrowd_items.models import Item, ItemAction, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser


def make_item(owner: BorrowdUser) -> Item:
    return Item.objects.create(
        name="Drill",
        description="A drill",
        owner=owner,
        created_by=owner,
        updated_by=owner,
    )


class ItemRevisionTests(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("rev_owner", "rev_borrower")
        )

    def setUp(self) -> None:
        self.item = make_item(self.owner)

    def stored_revision(self) -> int:
        return Item.all_objects.values_list("revision", flat=True).get(pk=self.item.pk)

    def test_a_new_item_starts_at_zero(self) -> None:
        self.assertEqual(self.item.revision, 0)

    def test_pre_revision_code_can_still_create_items(self) -> None:
        old_apps = (
            MigrationExecutor(connection)
            .loader.project_state([("borrowd_items", "0026_unique_open_transaction")])
            .apps
        )
        old_item = old_apps.get_model("borrowd_items", "Item").objects.create(
            name="Old runtime drill",
            description="A drill",
            owner_id=self.owner.pk,
            created_by_id=self.owner.pk,
            updated_by_id=self.owner.pk,
        )
        self.assertEqual(Item.all_objects.get(pk=old_item.pk).revision, 0)

    def test_saving_the_item_advances_it(self) -> None:
        self.item.name = "Hammer drill"
        self.item.save()
        self.item.save(update_fields=["name"])
        self.assertEqual(self.item.revision, 2)
        self.assertEqual(self.stored_revision(), 2)

    def test_saving_a_transaction_advances_its_item(self) -> None:
        tx = Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        tx.status = TransactionStatus.ACCEPTED
        tx.save()
        self.assertEqual(self.stored_revision(), 2)

    def test_coming_back_to_a_status_still_reads_as_a_change(self) -> None:
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.COLLECTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        before = self.stored_revision()
        self.item.process_action(self.owner, ItemAction.OFFER_GIVEAWAY)
        self.item.process_action(self.borrower, ItemAction.DECLINE_GIVEAWAY)

        tx = Transaction.objects.get(item=self.item)
        self.assertEqual(tx.status, TransactionStatus.COLLECTED)
        self.assertGreater(self.stored_revision(), before)

    def test_every_step_of_a_loan_advances_it(self) -> None:
        steps = (
            (self.borrower, ItemAction.REQUEST_ITEM),
            (self.owner, ItemAction.ACCEPT_REQUEST),
            (self.borrower, ItemAction.MARK_COLLECTED),
            (self.owner, ItemAction.CONFIRM_COLLECTED),
            (self.borrower, ItemAction.MARK_RETURNED),
            (self.owner, ItemAction.CONFIRM_RETURNED),
        )
        for user, action in steps:
            with self.subTest(action=action.name):
                before = self.stored_revision()
                self.item.process_action(user, action)
                self.assertGreater(self.stored_revision(), before)
                self.assertEqual(self.item.revision, self.stored_revision())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL concurrency.")
class ConcurrentRevisionTests(TransactionTestCase):
    def test_two_saves_at_once_both_count(self) -> None:
        owner = BorrowdUser.objects.create_user(username="rev_race_owner")
        item = make_item(owner)
        both_loaded = Barrier(2, timeout=10)

        def save_a_stale_copy() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    stale = Item.objects.get(pk=item.pk)
                    both_loaded.wait()
                    stale.save()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            for future in [executor.submit(save_a_stale_copy) for _ in range(2)]:
                future.result(timeout=20)

        item.refresh_from_db()
        self.assertEqual(item.revision, 2)
