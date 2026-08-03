from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.utils import timezone
from guardian.shortcuts import assign_perm

from borrowd_items.models import Item, ItemStatus
from borrowd_messaging.exceptions import MessagingDisabled, PreRequestChatUnavailable
from borrowd_messaging.models import ArchiveReason, ChatThread
from borrowd_messaging.services import MessagingService
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser


@override_settings(MESSAGING_ENABLED=True)
class GetOrCreatePreRequestThreadTests(TestCase):
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
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)

    def test_creates_a_thread_for_an_eligible_borrower(self) -> None:
        thread = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )

        self.assertEqual(thread.lender, self.lender)
        self.assertEqual(thread.borrower, self.borrower)
        self.assertEqual(thread.item, self.item)
        self.assertIsNone(thread.transaction)
        self.assertFalse(thread.is_archived)

    def test_is_idempotent(self) -> None:
        first = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )
        second = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_archived_thread_does_not_block_a_new_one(self) -> None:
        first = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )
        first.archived_at = timezone.now()
        first.archive_reason = ArchiveReason.CLOSED
        first.save(update_fields=["archived_at", "archive_reason"])

        second = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_owner_cannot_chat_about_their_own_item(self) -> None:
        with self.assertRaises(PermissionDenied):
            MessagingService.get_or_create_prerequest_thread(self.lender, self.item)

    def test_user_without_item_view_permission_is_refused(self) -> None:
        stranger = BorrowdUser.objects.create_user(
            username="stranger",
            email="stranger@example.com",
            password="password",
        )

        with self.assertRaises(PermissionDenied):
            MessagingService.get_or_create_prerequest_thread(stranger, self.item)

    def test_unavailable_item_is_refused(self) -> None:
        self.item.status = ItemStatus.BORROWED
        self.item.save(update_fields=["status"])

        with self.assertRaises(PreRequestChatUnavailable):
            MessagingService.get_or_create_prerequest_thread(self.borrower, self.item)

    def test_lender_can_turn_off_pre_request_chat(self) -> None:
        profile = self.lender.profile
        profile.allow_pre_request_chat = False
        profile.save(update_fields=["allow_pre_request_chat"])

        with self.assertRaises(PreRequestChatUnavailable):
            MessagingService.get_or_create_prerequest_thread(self.borrower, self.item)

    @override_settings(MESSAGING_ENABLED=False)
    def test_refused_while_the_feature_flag_is_off(self) -> None:
        with self.assertRaises(MessagingDisabled):
            MessagingService.get_or_create_prerequest_thread(self.borrower, self.item)
