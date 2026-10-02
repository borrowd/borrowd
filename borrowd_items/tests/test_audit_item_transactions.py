"""The read-only audit of open transactions."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from borrowd_items.models import Item, ItemStatus, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser


class AuditItemTransactionsTests(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser
    other: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower, cls.other = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("ait_owner", "ait_borrower", "ait_other")
        )

    def _item(self, *, deleted: bool = False) -> Item:
        return Item.objects.create(
            name="Drill",
            description="A useful thing",
            owner=self.owner,
            status=ItemStatus.AVAILABLE,
            created_by=self.owner,
            updated_by=self.owner,
            deleted_at=timezone.now() if deleted else None,
        )

    def _txn(
        self,
        item: Item,
        status: TransactionStatus,
        *,
        lender: BorrowdUser | None = None,
    ) -> Transaction:
        return Transaction.objects.create(
            item=item,
            party1=lender or self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def _run(self) -> str:
        out = StringIO()
        call_command("audit_item_transactions", stdout=out)
        return out.getvalue()

    def _findings(self) -> str:
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_item_transactions", stdout=out)
        return out.getvalue()

    def test_consistent_data_has_no_findings(self) -> None:
        self._txn(self._item(), TransactionStatus.COLLECTED)
        # Finished, so the lender no longer has to be the owner.
        self._txn(self._item(), TransactionStatus.RETURNED, lender=self.other)
        # The owner left mid-loan; the borrower can still resolve this one.
        self._txn(self._item(deleted=True), TransactionStatus.COLLECTED)

        self.assertIn("No findings.", self._run())

    def test_reports_an_open_transaction_whose_lender_is_not_the_owner(self) -> None:
        item = self._item()
        tx = self._txn(item, TransactionStatus.REQUESTED, lender=self.other)

        out = self._findings()

        self.assertIn(
            f"Lender is not owner: transaction={tx.pk} status=REQUESTED "
            f"item={item.pk} lender={self.other.pk} owner={self.owner.pk} "
            f"borrower={self.borrower.pk} item_deleted=False",
            out,
        )

    def test_reports_an_item_with_more_than_one_open_transaction(self) -> None:
        item = self._item()
        first = self._txn(item, TransactionStatus.ACCEPTED)
        second = self._txn(item, TransactionStatus.COLLECTED)

        out = self._findings()

        self.assertIn(
            f"More than one open transaction: item={item.pk} "
            f"transactions={first.pk} (ACCEPTED), {second.pk} (COLLECTED)",
            out,
        )

    def test_reports_a_request_stuck_on_a_deleted_item(self) -> None:
        item = self._item(deleted=True)
        tx = self._txn(item, TransactionStatus.REQUESTED)

        out = self._findings()

        self.assertIn(f"Stuck on a deleted item: transaction={tx.pk}", out)

    def test_counts_every_finding(self) -> None:
        self._txn(self._item(), TransactionStatus.REQUESTED, lender=self.other)
        self._txn(self._item(deleted=True), TransactionStatus.ACCEPTED)

        with self.assertRaisesMessage(CommandError, "2 finding(s)."):
            call_command("audit_item_transactions", stdout=StringIO())

    def test_only_reads(self) -> None:
        self._txn(self._item(), TransactionStatus.REQUESTED, lender=self.other)

        with CaptureQueriesContext(connection) as queries:
            self._findings()

        self.assertTrue(queries.captured_queries)
        for query in queries.captured_queries:
            self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT"))
