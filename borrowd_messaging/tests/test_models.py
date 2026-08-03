from typing import Any

from django.db import IntegrityError
from django.db.transaction import atomic
from django.test import TestCase
from django.utils import timezone

from borrowd_items.models import Item, Transaction
from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_messaging.models import ArchiveReason, ChatThread, Message
from borrowd_users.models import BorrowdUser


class ChatThreadModelTests(TestCase):
    def setUp(self) -> None:
        self.lender = BorrowdUser.objects.create_user(
            username="lender",
            email="lender@example.com",
            password="password",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
        )
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )

    def create_thread(self, **overrides: Any) -> ChatThread:
        defaults: dict[str, Any] = {
            "item": self.item,
            "lender": self.lender,
            "borrower": self.borrower,
            "created_by": self.borrower,
            "updated_by": self.borrower,
        }
        defaults.update(overrides)
        return ChatThread.objects.create(**defaults)

    def create_transaction(self) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def test_second_active_prerequest_thread_is_rejected(self) -> None:
        self.create_thread()

        with self.assertRaises(IntegrityError):
            with atomic():
                self.create_thread()

    def test_new_prerequest_thread_allowed_once_previous_has_transaction(self) -> None:
        first = self.create_thread()
        first.transaction = self.create_transaction()
        first.save(update_fields=["transaction"])

        second = self.create_thread()

        self.assertNotEqual(first.pk, second.pk)

    def test_new_prerequest_thread_allowed_once_previous_is_archived(self) -> None:
        first = self.create_thread()
        first.archived_at = timezone.now()
        first.archive_reason = ArchiveReason.CLOSED
        first.save(update_fields=["archived_at", "archive_reason"])

        second = self.create_thread()

        self.assertNotEqual(first.pk, second.pk)

    def test_other_borrowers_can_open_threads_on_same_item(self) -> None:
        other_borrower = BorrowdUser.objects.create_user(
            username="other",
            email="other@example.com",
            password="password",
        )
        self.create_thread()

        thread = self.create_thread(
            borrower=other_borrower,
            created_by=other_borrower,
            updated_by=other_borrower,
        )

        self.assertEqual(thread.borrower, other_borrower)

    def test_transaction_can_only_have_one_thread(self) -> None:
        txn = self.create_transaction()
        self.create_thread(transaction=txn)

        with self.assertRaises(IntegrityError):
            with atomic():
                self.create_thread(transaction=txn)

    def test_is_archived_reflects_archived_at(self) -> None:
        thread = self.create_thread()
        self.assertFalse(thread.is_archived)

        thread.archived_at = timezone.now()

        self.assertTrue(thread.is_archived)

    def test_mark_read_writes_the_callers_own_column(self) -> None:
        thread = self.create_thread()

        thread.mark_read(self.borrower)
        thread.refresh_from_db()

        self.assertIsNotNone(thread.borrower_last_read_at)
        self.assertIsNone(thread.lender_last_read_at)
        self.assertEqual(
            thread.last_read_at_for(self.borrower), thread.borrower_last_read_at
        )

    def test_mark_read_by_lender_writes_lender_column(self) -> None:
        thread = self.create_thread()

        thread.mark_read(self.lender)
        thread.refresh_from_db()

        self.assertIsNotNone(thread.lender_last_read_at)
        self.assertIsNone(thread.borrower_last_read_at)

    def test_read_helpers_reject_non_participants(self) -> None:
        outsider = BorrowdUser.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="password",
        )
        thread = self.create_thread()

        with self.assertRaises(NotThreadParticipant):
            thread.mark_read(outsider)
        with self.assertRaises(NotThreadParticipant):
            thread.last_read_at_for(outsider)


class MessageModelTests(TestCase):
    def setUp(self) -> None:
        self.lender = BorrowdUser.objects.create_user(
            username="lender",
            email="lender@example.com",
            password="password",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
        )
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )
        self.thread = ChatThread.objects.create(
            item=self.item,
            lender=self.lender,
            borrower=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def test_empty_body_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError):
            with atomic():
                Message.objects.create(
                    thread=self.thread,
                    sender=self.borrower,
                    body="",
                )

    def test_messages_read_back_in_send_order_by_pk(self) -> None:
        first = Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Is this available?"
        )
        second = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Yes it is."
        )

        messages = list(self.thread.messages.order_by("id"))

        self.assertEqual(messages, [first, second])
        self.assertLess(first.pk, second.pk)
