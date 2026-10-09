"""Verify status repairs, dry runs, and skipped items."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from borrowd_items.models import (
    Item,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser


class RepairItemStatusesTests(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner = BorrowdUser.objects.create_user(
            username="ris_owner", email="ris_owner@example.com", password="password"
        )
        cls.borrower = BorrowdUser.objects.create_user(
            username="ris_borrower",
            email="ris_borrower@example.com",
            password="password",
        )

    def _item(self, name: str, status: ItemStatus) -> Item:
        return Item.objects.create(
            name=name,
            description="A useful thing",
            owner=self.owner,
            status=status,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _txn(self, item: Item, status: TransactionStatus) -> Transaction:
        return Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _run(self, *args: str) -> tuple[str, str]:
        out, err = StringIO(), StringIO()
        call_command("repair_item_statuses", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_repairs_an_item_that_disagrees_with_its_transaction(self) -> None:
        item = self._item("Drill", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.COLLECTED)

        out, _ = self._run()

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BORROWED)
        self.assertIn("1 repaired", out)

    def test_frees_an_item_with_no_open_transaction(self) -> None:
        item = self._item("Ladder", ItemStatus.BORROWED)
        self._txn(item, TransactionStatus.RETURNED)

        self._run()

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)

    def test_leaves_a_correct_item_alone(self) -> None:
        item = self._item("Saw", ItemStatus.RESERVED)
        self._txn(item, TransactionStatus.ACCEPTED)

        out, _ = self._run()

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.RESERVED)
        self.assertIn("0 of 1", out)

    def test_dry_run_reports_without_changing_anything(self) -> None:
        item = self._item("Mower", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.COLLECTED)

        out, _ = self._run("--dry-run")

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)
        self.assertIn("dry run", out)
        self.assertIn("should be BORROWED", out)

    def test_skips_a_soft_deleted_item(self) -> None:
        item = self._item("Gone", ItemStatus.BORROWED)
        item.deleted_at = timezone.now()
        item.deleted_by = self.owner
        item.save(update_fields=("deleted_at", "deleted_by"))

        self._run()

        item = Item.all_objects.get(pk=item.pk)
        self.assertEqual(item.status, ItemStatus.BORROWED)

    def test_reports_an_item_with_two_open_transactions_instead_of_guessing(
        self,
    ) -> None:
        item = self._item("Contested", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.ACCEPTED)
        self._txn(item, TransactionStatus.COLLECTED)

        out, err = StringIO(), StringIO()
        with self.assertRaisesMessage(CommandError, "1 item(s) skipped as ambiguous"):
            call_command("repair_item_statuses", stdout=out, stderr=err)

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)
        self.assertIn("Ambiguous", err.getvalue())
        self.assertIn("0 repaired", out.getvalue())
        self.assertNotIn("Drifted", out.getvalue())

    def test_repairs_an_unknown_status_from_the_open_transaction(self) -> None:
        item = self._item("Drill", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.COLLECTED)
        Item.all_objects.filter(pk=item.pk).update(status=999)

        out, _ = self._run()

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BORROWED)
        self.assertIn("is 999, should be BORROWED", out)
        self.assertIn("1 repaired", out)

    def test_repairs_an_unknown_status_without_an_open_transaction(self) -> None:
        item = self._item("Drill", ItemStatus.AVAILABLE)
        Item.all_objects.filter(pk=item.pk).update(status=999)

        out, _ = self._run()

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)
        self.assertIn("is 999, should be AVAILABLE", out)

    def test_dry_run_reports_an_unknown_status_without_changing_it(self) -> None:
        item = self._item("Drill", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.COLLECTED)
        Item.all_objects.filter(pk=item.pk).update(status=999)

        out, _ = self._run("--dry-run")

        item.refresh_from_db()
        self.assertEqual(item.status, 999)
        self.assertIn("is 999, should be BORROWED", out)

    def test_dry_run_fails_when_an_item_is_ambiguous(self) -> None:
        item = self._item("Contested", ItemStatus.AVAILABLE)
        self._txn(item, TransactionStatus.ACCEPTED)
        self._txn(item, TransactionStatus.COLLECTED)
        out = StringIO()

        with self.assertRaisesMessage(CommandError, "1 item(s) skipped as ambiguous"):
            call_command(
                "repair_item_statuses", "--dry-run", stdout=out, stderr=StringIO()
            )

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.AVAILABLE)
        self.assertIn("dry run", out.getvalue())

    def test_repairs_other_items_before_reporting_ambiguity(self) -> None:
        ambiguous = self._item("Contested", ItemStatus.AVAILABLE)
        self._txn(ambiguous, TransactionStatus.ACCEPTED)
        self._txn(ambiguous, TransactionStatus.COLLECTED)
        repairable = self._item("Drill", ItemStatus.BORROWED)
        out = StringIO()

        with self.assertRaisesMessage(CommandError, "1 item(s) skipped as ambiguous"):
            call_command("repair_item_statuses", stdout=out, stderr=StringIO())

        ambiguous.refresh_from_db()
        repairable.refresh_from_db()
        self.assertEqual(ambiguous.status, ItemStatus.AVAILABLE)
        self.assertEqual(repairable.status, ItemStatus.AVAILABLE)
        self.assertIn("1 of 2 item(s) had a drifted status; 1 repaired", out.getvalue())
