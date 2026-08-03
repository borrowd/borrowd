from django.test import override_settings

from borrowd_items.models import TransactionStatus
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import _ARCHIVE_MESSAGES, MessagingService
from borrowd_messaging.tests.base import MessagingTestCase
from borrowd_permissions.models import ChatThreadOLP


class ChatThreadPermissionSignalTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

    def test_both_parties_can_view_the_thread(self) -> None:
        self.assertTrue(self.lender.has_perm(ChatThreadOLP.VIEW, self.thread))
        self.assertTrue(self.borrower.has_perm(ChatThreadOLP.VIEW, self.thread))

    def test_outsiders_cannot_view_the_thread(self) -> None:
        outsider = self.make_user("outsider")

        self.assertFalse(outsider.has_perm(ChatThreadOLP.VIEW, self.thread))


class TransactionLifecycleTests(MessagingTestCase):
    """
    Deliberately runs with MESSAGING_ENABLED off, since threads must stay in
    step with transactions whether or not the feature is switched on.
    """

    def test_a_new_transaction_gets_a_thread(self) -> None:
        transaction = self.make_transaction()

        thread = ChatThread.objects.filter(transaction=transaction).first()

        self.assertIsNotNone(thread)

    def test_a_new_transaction_closes_everyone_elses_conversation(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))

        self.make_transaction()

        onlooker_thread.refresh_from_db()
        self.assertEqual(onlooker_thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_the_requesters_own_conversation_carries_forward(self) -> None:
        thread = self.make_thread()

        transaction = self.make_transaction()

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
                transaction = self.make_transaction()
                transaction.status = status
                transaction.save()

                thread = ChatThread.objects.get(transaction=transaction)
                self.assertEqual(thread.archive_reason, reason)
                last_message = thread.messages.order_by("id").last()
                assert last_message is not None
                self.assertEqual(last_message.body, _ARCHIVE_MESSAGES[reason])

    def test_progress_short_of_a_terminal_status_leaves_the_thread_alone(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.ACCEPTED
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertFalse(thread.is_archived)
        self.assertEqual(thread.messages.count(), 0)

    @override_settings(MESSAGING_ENABLED=True)
    def test_a_dispute_warns_both_parties_but_keeps_the_thread_open(self) -> None:
        transaction = self.make_transaction()
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
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.RETURNED
        transaction.save()
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(thread.messages.count(), 1)
