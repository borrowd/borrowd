from django.test import TestCase, override_settings
from guardian.shortcuts import assign_perm

from borrowd_items.models import Item, Transaction
from borrowd_messaging.models import ChatThread
from borrowd_messaging.services import MessagingService
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser


@override_settings(MESSAGING_ENABLED=True)
class AttachThreadToTransactionTests(TestCase):
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

    def create_transaction(self, borrower: BorrowdUser | None = None) -> Transaction:
        borrower = borrower or self.borrower
        return Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=borrower,
            created_by=borrower,
            updated_by=borrower,
        )

    def create_prerequest_thread(
        self, borrower: BorrowdUser | None = None
    ) -> ChatThread:
        borrower = borrower or self.borrower
        return ChatThread.objects.create(
            item=self.item,
            lender=self.lender,
            borrower=borrower,
            created_by=borrower,
            updated_by=borrower,
        )

    def test_carries_an_existing_conversation_forward(self) -> None:
        thread = self.create_prerequest_thread()
        message = MessagingService.send_message(
            thread, self.borrower, "Is this available?"
        )

        attached = MessagingService.attach_thread_to(self.create_transaction())

        self.assertEqual(attached.pk, thread.pk)
        self.assertEqual(ChatThread.objects.count(), 1)
        self.assertEqual(list(attached.messages.order_by("id")), [message])

    def test_creates_a_thread_when_there_was_no_conversation(self) -> None:
        transaction = self.create_transaction()

        thread = MessagingService.attach_thread_to(transaction)

        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.lender, self.lender)
        self.assertEqual(thread.borrower, self.borrower)
        self.assertEqual(thread.item, self.item)

    def test_is_idempotent(self) -> None:
        transaction = self.create_transaction()

        first = MessagingService.attach_thread_to(transaction)
        second = MessagingService.attach_thread_to(transaction)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_ignores_another_borrowers_conversation(self) -> None:
        other_borrower = BorrowdUser.objects.create_user(
            username="other",
            email="other@example.com",
            password="password",
        )
        other_thread = self.create_prerequest_thread(borrower=other_borrower)

        attached = MessagingService.attach_thread_to(self.create_transaction())

        self.assertNotEqual(attached.pk, other_thread.pk)
        other_thread.refresh_from_db()
        self.assertIsNone(other_thread.transaction)

    def test_ignores_an_archived_conversation(self) -> None:
        thread = self.create_prerequest_thread()
        MessagingService.close_prerequest_thread(thread, self.borrower)

        attached = MessagingService.attach_thread_to(self.create_transaction())

        self.assertNotEqual(attached.pk, thread.pk)

    def test_frees_the_borrower_to_open_a_new_conversation(self) -> None:
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        thread = self.create_prerequest_thread()
        MessagingService.attach_thread_to(self.create_transaction())

        fresh = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )

        self.assertNotEqual(fresh.pk, thread.pk)

    @override_settings(MESSAGING_ENABLED=False)
    def test_attaches_while_the_feature_flag_is_off(self) -> None:
        transaction = self.create_transaction()

        thread = MessagingService.attach_thread_to(transaction)

        self.assertEqual(thread.transaction, transaction)
