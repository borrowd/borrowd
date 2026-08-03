from django.test import TestCase, override_settings

from borrowd_items.models import Item, Transaction, TransactionStatus
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import _ARCHIVE_MESSAGES, MessagingService
from borrowd_users.models import BorrowdUser


class TransactionLifecycleTests(TestCase):
    """
    The messaging side effects of a transaction moving through its states.
    Deliberately runs with MESSAGING_ENABLED off, since threads must stay in
    step with transactions whether or not the feature is switched on.
    """

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

    def create_transaction(self) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def create_onlooker_thread(self) -> ChatThread:
        onlooker = BorrowdUser.objects.create_user(
            username="onlooker",
            email="onlooker@example.com",
            password="password",
        )
        return ChatThread.objects.create(
            item=self.item,
            lender=self.lender,
            borrower=onlooker,
            created_by=onlooker,
            updated_by=onlooker,
        )

    def test_a_new_transaction_gets_a_thread(self) -> None:
        transaction = self.create_transaction()

        thread = ChatThread.objects.filter(transaction=transaction).first()

        self.assertIsNotNone(thread)

    def test_a_new_transaction_closes_everyone_elses_conversation(self) -> None:
        onlooker_thread = self.create_onlooker_thread()

        self.create_transaction()

        onlooker_thread.refresh_from_db()
        self.assertEqual(onlooker_thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_the_requesters_own_conversation_carries_forward(self) -> None:
        thread = ChatThread.objects.create(
            item=self.item,
            lender=self.lender,
            borrower=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

        transaction = self.create_transaction()

        thread.refresh_from_db()
        self.assertEqual(thread.transaction, transaction)
        self.assertFalse(thread.is_archived)

    def test_terminal_statuses_archive_the_thread(self) -> None:
        cases = [
            (TransactionStatus.RETURNED, ArchiveReason.RETURNED),
            (TransactionStatus.REJECTED, ArchiveReason.REJECTED),
            (TransactionStatus.CANCELLED, ArchiveReason.CANCELLED),
            (TransactionStatus.RESOLVED, ArchiveReason.RESOLVED),
            (
                TransactionStatus.OWNERSHIP_TRANSFERRED,
                ArchiveReason.OWNERSHIP_TRANSFERRED,
            ),
        ]
        for status, reason in cases:
            with self.subTest(status=status.name):
                transaction = self.create_transaction()
                transaction.status = status
                transaction.save()

                thread = ChatThread.objects.get(transaction=transaction)
                self.assertEqual(thread.archive_reason, reason)
                last_message = thread.messages.order_by("id").last()
                assert last_message is not None
                self.assertEqual(last_message.body, _ARCHIVE_MESSAGES[reason])

    def test_progress_short_of_a_terminal_status_leaves_the_thread_alone(self) -> None:
        transaction = self.create_transaction()
        transaction.status = TransactionStatus.ACCEPTED
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertFalse(thread.is_archived)
        self.assertEqual(thread.messages.count(), 0)

    @override_settings(MESSAGING_ENABLED=True)
    def test_a_dispute_warns_both_parties_but_keeps_the_thread_open(self) -> None:
        transaction = self.create_transaction()
        transaction.status = TransactionStatus.DISPUTED
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertFalse(thread.is_archived)
        last_message = thread.messages.order_by("id").last()
        assert last_message is not None
        self.assertTrue(last_message.is_system)
        self.assertIn("dispute has been raised", last_message.body)
        MessagingService.send_message(thread, self.borrower, "Let's sort this out.")

    def test_re_saving_a_terminal_transaction_posts_one_notice(self) -> None:
        transaction = self.create_transaction()
        transaction.status = TransactionStatus.RETURNED
        transaction.save()
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(thread.messages.count(), 1)
