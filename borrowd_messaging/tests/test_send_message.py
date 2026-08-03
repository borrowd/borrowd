from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from borrowd_items.models import Item
from borrowd_messaging.exceptions import (
    MessagingDisabled,
    NotThreadParticipant,
    ThreadNotWritable,
)
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import MessagingService
from borrowd_users.models import BorrowdUser


@override_settings(MESSAGING_ENABLED=True)
class SendMessageTests(TestCase):
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

    def test_stores_a_message_from_either_party(self) -> None:
        from_borrower = MessagingService.send_message(
            self.thread, self.borrower, "Is this available?"
        )
        from_lender = MessagingService.send_message(self.thread, self.lender, "It is.")

        self.assertEqual(from_borrower.sender, self.borrower)
        self.assertEqual(from_lender.sender, self.lender)
        self.assertFalse(from_borrower.is_system)
        self.assertEqual(
            list(self.thread.messages.order_by("id")),
            [
                from_borrower,
                from_lender,
            ],
        )

    def test_strips_surrounding_whitespace(self) -> None:
        message = MessagingService.send_message(self.thread, self.borrower, "  hello  ")

        self.assertEqual(message.body, "hello")

    def test_rejects_a_blank_body(self) -> None:
        with self.assertRaises(ValueError):
            MessagingService.send_message(self.thread, self.borrower, "   ")

    def test_rejects_a_non_participant(self) -> None:
        outsider = BorrowdUser.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="password",
        )

        with self.assertRaises(NotThreadParticipant):
            MessagingService.send_message(self.thread, outsider, "hello")

    def test_rejects_an_archived_thread(self) -> None:
        self.thread.archived_at = timezone.now()
        self.thread.archive_reason = ArchiveReason.RETURNED
        self.thread.save(update_fields=["archived_at", "archive_reason"])

        with self.assertRaises(ThreadNotWritable):
            MessagingService.send_message(self.thread, self.borrower, "hello")

    @override_settings(MESSAGING_ENABLED=False)
    def test_refused_while_the_feature_flag_is_off(self) -> None:
        with self.assertRaises(MessagingDisabled):
            MessagingService.send_message(self.thread, self.borrower, "hello")

    def test_hands_every_stored_message_to_dispatch(self) -> None:
        with patch.object(MessagingService, "_dispatch") as dispatch:
            message = MessagingService.send_message(self.thread, self.borrower, "hello")

        dispatch.assert_called_once_with(message)
