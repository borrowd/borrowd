from django.test import override_settings

from borrowd_items.models import Transaction, TransactionStatus
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import ARCHIVE_MESSAGES, MessagingService
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


@override_settings(MESSAGING_ENABLED=True)
class TransactionLifecycleTests(MessagingTestCase):
    def test_a_new_transaction_gets_a_thread(self) -> None:
        transaction = self.make_transaction()

        thread = ChatThread.objects.filter(transaction=transaction).first()

        self.assertIsNotNone(thread)

    def advance(self, transaction: Transaction, status: TransactionStatus) -> None:
        transaction.status = status
        transaction.save()

    def test_a_pending_request_leaves_other_conversations_open(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))

        self.make_transaction()

        onlooker_thread.refresh_from_db()
        self.assertFalse(onlooker_thread.is_archived)

    def test_a_rejected_request_leaves_other_conversations_open(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.REJECTED)

        onlooker_thread.refresh_from_db()
        self.assertFalse(onlooker_thread.is_archived)

    def test_a_cancelled_request_leaves_other_conversations_open(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.CANCELLED)

        onlooker_thread.refresh_from_db()
        self.assertFalse(onlooker_thread.is_archived)

    def test_accepting_closes_everyone_elses_conversation(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.ACCEPTED)

        onlooker_thread.refresh_from_db()
        self.assertEqual(onlooker_thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_giving_the_item_away_closes_everyone_elses_conversation(self) -> None:
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.OWNERSHIP_TRANSFERRED)

        onlooker_thread.refresh_from_db()
        self.assertEqual(onlooker_thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_accepting_leaves_the_requesters_own_conversation_open(self) -> None:
        thread = self.make_thread()
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.ACCEPTED)

        thread.refresh_from_db()
        self.assertFalse(thread.is_archived)

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
                self.assertEqual(last_message.body, ARCHIVE_MESSAGES[reason])

    def test_progress_short_of_a_terminal_status_leaves_the_thread_alone(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.ACCEPTED
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertFalse(thread.is_archived)
        self.assertEqual(thread.messages.count(), 0)

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

    def test_re_saving_a_disputed_transaction_posts_one_notice(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.DISPUTED
        transaction.save()
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(thread.messages.count(), 1)

    def test_re_saving_a_terminal_transaction_posts_one_notice(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.RETURNED
        transaction.save()
        transaction.save()

        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(thread.messages.count(), 1)


@override_settings(MESSAGING_ENABLED=False)
class TransactionLifecycleWhileFeatureFlagIsOffTests(MessagingTestCase):
    def advance(self, transaction: Transaction, status: TransactionStatus) -> None:
        transaction.status = status
        transaction.save()

    def test_a_new_transaction_does_not_create_a_thread(self) -> None:
        transaction = self.make_transaction()

        self.assertFalse(ChatThread.objects.filter(transaction=transaction).exists())

    def test_a_new_transaction_carries_an_existing_conversation_forward(self) -> None:
        thread = self.make_thread()

        transaction = self.make_transaction()

        thread.refresh_from_db()
        self.assertEqual(thread.transaction, transaction)
        self.assertFalse(thread.is_archived)

    def test_accepting_archives_other_prerequest_conversations(self) -> None:
        requester_thread = self.make_thread()
        onlooker_thread = self.make_thread(borrower=self.make_user("onlooker"))
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.ACCEPTED)

        requester_thread.refresh_from_db()
        onlooker_thread.refresh_from_db()
        self.assertFalse(requester_thread.is_archived)
        self.assertEqual(onlooker_thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_a_dispute_annotates_an_existing_thread(self) -> None:
        thread = self.make_thread()
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.DISPUTED)

        thread.refresh_from_db()
        self.assertFalse(thread.is_archived)
        message = thread.messages.get()
        self.assertTrue(message.is_system)
        self.assertIn("dispute has been raised", message.body)

    def test_a_terminal_status_archives_an_existing_thread(self) -> None:
        thread = self.make_thread()
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.RETURNED)

        thread.refresh_from_db()
        self.assertEqual(thread.archive_reason, ArchiveReason.RETURNED)
        self.assertEqual(
            thread.messages.get().body,
            ARCHIVE_MESSAGES[ArchiveReason.RETURNED],
        )

    def test_a_terminal_status_does_not_create_a_thread(self) -> None:
        transaction = self.make_transaction()

        self.advance(transaction, TransactionStatus.RETURNED)

        self.assertFalse(ChatThread.objects.filter(transaction=transaction).exists())

    def test_a_transaction_without_a_thread_can_still_be_destroyed(self) -> None:
        transaction = self.make_transaction()

        transaction.delete()

        self.assertFalse(Transaction.objects.filter(pk=transaction.pk).exists())
