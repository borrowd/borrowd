"""An item has at most one open transaction."""

from importlib import import_module
from types import SimpleNamespace
from unittest import skipUnless

from django.apps import apps
from django.db import IntegrityError, connection
from django.db.transaction import atomic
from django.test import TestCase

from borrowd_items.models import (
    TERMINAL_TRANSACTION_STATUSES,
    Item,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser

migration = import_module("borrowd_items.migrations.0026_unique_open_transaction")


class OneOpenTransactionTestCase(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower = (
            BorrowdUser.objects.create_user(
                username=name, email=f"{name}@example.com", password="password"
            )
            for name in ("one_open_owner", "one_open_borrower")
        )

    def setUp(self) -> None:
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def make_transaction(self, status: TransactionStatus) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=self.borrower,
        )


class OneOpenTransactionPerItemTests(OneOpenTransactionTestCase):
    def test_a_second_open_transaction_is_rejected(self) -> None:
        self.make_transaction(TransactionStatus.COLLECTED)
        with self.assertRaises(IntegrityError), atomic():
            self.make_transaction(TransactionStatus.REQUESTED)

    def test_finished_transactions_do_not_count(self) -> None:
        for status in TERMINAL_TRANSACTION_STATUSES:
            self.make_transaction(status)
        self.make_transaction(TransactionStatus.REQUESTED)

        self.assertEqual(
            Transaction.objects.filter(item=self.item).count(),
            len(TERMINAL_TRANSACTION_STATUSES) + 1,
        )


@skipUnless(
    connection.vendor == "postgresql",
    "Drops the constraint inside the test transaction, which needs Postgres DDL.",
)
class MigrationPreCheckTests(OneOpenTransactionTestCase):
    def run_check(self) -> None:
        migration.check_for_multiple_open_transactions(
            apps, SimpleNamespace(connection=connection)
        )

    def test_names_the_items_to_fix(self) -> None:
        (constraint,) = Transaction._meta.constraints
        with connection.schema_editor() as editor:
            editor.remove_constraint(Transaction, constraint)
        self.make_transaction(TransactionStatus.ACCEPTED)
        self.make_transaction(TransactionStatus.REQUESTED)

        with self.assertRaisesMessage(RuntimeError, f"items {self.item.pk} have"):
            self.run_check()

    def test_passes_on_clean_data(self) -> None:
        self.make_transaction(TransactionStatus.RETURNED)
        self.make_transaction(TransactionStatus.REQUESTED)
        self.run_check()
