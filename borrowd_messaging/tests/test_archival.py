from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from borrowd_items.models import Item, Transaction
from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import _ARCHIVE_MESSAGES, MessagingService
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user


class ArchiveMessageCopyTests(TestCase):
    def test_every_archive_reason_has_copy(self) -> None:
        for reason in ArchiveReason:
            self.assertIn(reason, _ARCHIVE_MESSAGES)


@override_settings(MESSAGING_ENABLED=True)
class ThreadArchivalTests(TestCase):
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

    def test_system_messages_come_from_the_system_user(self) -> None:
        message = MessagingService.post_system_message(
            self.thread, "Something happened."
        )

        self.assertEqual(message.sender, get_system_user())
        self.assertTrue(message.is_system)
        self.assertEqual(message.body, "Something happened.")

    def test_archiving_locks_the_thread_and_explains_why(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        self.thread.refresh_from_db()

        self.assertTrue(self.thread.is_archived)
        self.assertEqual(self.thread.archive_reason, ArchiveReason.RETURNED)
        self.assertEqual(self.thread.updated_by, get_system_user())
        last_message = self.thread.messages.order_by("id").last()
        assert last_message is not None
        self.assertEqual(last_message.body, _ARCHIVE_MESSAGES[ArchiveReason.RETURNED])

    def test_archiving_twice_posts_one_notice(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        MessagingService.archive_thread(self.thread, ArchiveReason.CANCELLED)
        self.thread.refresh_from_db()

        self.assertEqual(self.thread.archive_reason, ArchiveReason.RETURNED)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_archiving_accepts_alternate_copy(self) -> None:
        MessagingService.archive_thread(
            self.thread,
            ArchiveReason.OWNERSHIP_TRANSFERRED,
            message="This item is no longer available. Chat is now archived.",
        )
        last_message = self.thread.messages.order_by("id").last()

        assert last_message is not None
        self.assertEqual(
            last_message.body, "This item is no longer available. Chat is now archived."
        )

    def test_either_party_can_close_a_prerequest_thread(self) -> None:
        MessagingService.close_prerequest_thread(self.thread, self.lender)
        self.thread.refresh_from_db()

        self.assertEqual(self.thread.archive_reason, ArchiveReason.CLOSED)
        self.assertEqual(self.thread.updated_by, self.lender)
        last_message = self.thread.messages.order_by("id").last()
        assert last_message is not None
        self.assertEqual(last_message.body, _ARCHIVE_MESSAGES[ArchiveReason.CLOSED])

    def test_outsiders_cannot_close_a_thread(self) -> None:
        outsider = BorrowdUser.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="password",
        )

        with self.assertRaises(NotThreadParticipant):
            MessagingService.close_prerequest_thread(self.thread, outsider)

    def test_threads_with_a_transaction_cannot_be_closed(self) -> None:
        self.thread.transaction = Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        self.thread.save(update_fields=["transaction"])

        with self.assertRaises(PermissionDenied):
            MessagingService.close_prerequest_thread(self.thread, self.borrower)

    @override_settings(MESSAGING_ENABLED=False)
    def test_archival_works_while_the_feature_flag_is_off(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        self.thread.refresh_from_db()

        self.assertTrue(self.thread.is_archived)
        self.assertEqual(self.thread.messages.count(), 1)
