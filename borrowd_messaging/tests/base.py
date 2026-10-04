from typing import Any

from django.test import TestCase

from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, LifecycleEvent, Transaction, TransactionStatus
from borrowd_messaging.models import ChatThread
from borrowd_users.models import BorrowdUser


class MessagingTestCase(TestCase):
    """
    A lender, a borrower, and one item the lender owns. Every factory here
    defaults to those three and takes keyword overrides for the rest.
    """

    def setUp(self) -> None:
        self.lender = self.make_user("lender")
        self.borrower = self.make_user("borrower")
        self.item = self.make_item()

    @staticmethod
    def make_user(username: str) -> BorrowdUser:
        return BorrowdUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
        )

    def make_item(self, **overrides: Any) -> Item:
        defaults: dict[str, Any] = {
            "name": "Drill",
            "description": "A drill",
            "owner": self.lender,
            "created_by": self.lender,
            "updated_by": self.lender,
        }
        defaults.update(overrides)
        return Item.objects.create(**defaults)

    def make_group(self, name: str = "Group", **overrides: Any) -> BorrowdGroup:
        defaults: dict[str, Any] = {
            "name": name,
            "created_by": self.lender,
            "updated_by": self.lender,
            "membership_requires_approval": False,
        }
        defaults.update(overrides)
        return BorrowdGroup.objects.create_group(**defaults)

    def make_thread(self, **overrides: Any) -> ChatThread:
        borrower = overrides.pop("borrower", self.borrower)
        defaults: dict[str, Any] = {
            "item": self.item,
            "lender": self.lender,
            "borrower": borrower,
            "created_by": borrower,
            "updated_by": borrower,
        }
        defaults.update(overrides)
        return ChatThread.objects.create(**defaults)

    def make_transaction(self, **overrides: Any) -> Transaction:
        borrower = overrides.pop("borrower", self.borrower)
        defaults: dict[str, Any] = {
            "item": self.item,
            "party1": self.lender,
            "party2": borrower,
            "created_by": borrower,
            "updated_by": borrower,
        }
        defaults.update(overrides)
        transaction = Transaction.objects.create(**defaults)
        # The event opening a request records, which gives it its thread.
        LifecycleEvent.record(
            transaction,
            source=None,
            target=TransactionStatus(transaction.status),
            actor=transaction.created_by,
        )
        return transaction

    @staticmethod
    def move_transaction(transaction: Transaction, status: TransactionStatus) -> None:
        """Save `transaction` at `status`, with the event an action records."""
        source = TransactionStatus(transaction.status)
        transaction.status = status
        transaction.save()
        LifecycleEvent.record(
            transaction, source=source, target=status, actor=transaction.updated_by
        )
