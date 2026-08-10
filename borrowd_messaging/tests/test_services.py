from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from guardian.shortcuts import assign_perm

from borrowd_items.models import ItemStatus
from borrowd_messaging.exceptions import (
    InvalidMessageBody,
    MessagingDisabled,
    NotThreadParticipant,
    PreRequestChatUnavailable,
    ThreadNotWritable,
)
from borrowd_messaging.models import (
    MESSAGE_BODY_MAX_LENGTH,
    ArchiveReason,
    ChatThread,
)
from borrowd_messaging.services import ARCHIVE_MESSAGES, MessagingService
from borrowd_messaging.tests.base import MessagingTestCase
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user


class ArchiveMessageCopyTests(TestCase):
    def test_every_archive_reason_has_copy(self) -> None:
        for reason in ArchiveReason:
            self.assertIn(reason, ARCHIVE_MESSAGES)


@override_settings(MESSAGING_ENABLED=True)
class GetOrCreatePreRequestThreadTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
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
        stranger = self.make_user("stranger")

        with self.assertRaises(PermissionDenied):
            MessagingService.get_or_create_prerequest_thread(stranger, self.item)

    def test_unavailable_item_is_refused(self) -> None:
        self.item.status = ItemStatus.BORROWED
        self.item.save(update_fields=["status"])

        with self.assertRaises(PreRequestChatUnavailable):
            MessagingService.get_or_create_prerequest_thread(self.borrower, self.item)

    def test_soft_deleted_item_is_refused(self) -> None:
        # soft_delete leaves status alone, so the AVAILABLE check misses this.
        self.item.soft_delete(deleted_by=self.lender)

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

    def test_losing_a_race_returns_the_thread_the_winner_made(self) -> None:
        # First lookup sees nothing and we try to create; the unique constraint
        # rejects it; the second lookup finds what the winner just made.
        winner = self.make_thread()

        with patch.object(
            MessagingService, "_active_prerequest_thread", side_effect=[None, winner]
        ):
            thread = MessagingService.get_or_create_prerequest_thread(
                self.borrower, self.item
            )

        self.assertEqual(thread.pk, winner.pk)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_an_integrity_error_with_no_racing_thread_is_reraised(self) -> None:
        self.make_thread()

        with patch.object(
            MessagingService, "_active_prerequest_thread", return_value=None
        ):
            with self.assertRaises(IntegrityError):
                MessagingService.get_or_create_prerequest_thread(
                    self.borrower, self.item
                )


@override_settings(MESSAGING_ENABLED=True)
class SendMessageTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

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
            [from_borrower, from_lender],
        )

    def test_strips_surrounding_whitespace(self) -> None:
        message = MessagingService.send_message(self.thread, self.borrower, "  hello  ")

        self.assertEqual(message.body, "hello")

    def test_rejects_a_blank_body(self) -> None:
        with self.assertRaises(InvalidMessageBody):
            MessagingService.send_message(self.thread, self.borrower, "   ")

    def test_accepts_a_body_at_the_length_limit(self) -> None:
        message = MessagingService.send_message(
            self.thread, self.borrower, "a" * MESSAGE_BODY_MAX_LENGTH
        )

        self.assertEqual(len(message.body), MESSAGE_BODY_MAX_LENGTH)

    def test_rejects_a_body_over_the_length_limit(self) -> None:
        with self.assertRaises(InvalidMessageBody):
            MessagingService.send_message(
                self.thread, self.borrower, "a" * (MESSAGE_BODY_MAX_LENGTH + 1)
            )

    def test_measures_length_after_stripping(self) -> None:
        body = "a" * MESSAGE_BODY_MAX_LENGTH

        message = MessagingService.send_message(
            self.thread, self.borrower, f"  {body}  "
        )

        self.assertEqual(message.body, body)

    def test_rejects_a_non_participant(self) -> None:
        outsider = self.make_user("outsider")

        with self.assertRaises(NotThreadParticipant):
            MessagingService.send_message(self.thread, outsider, "hello")

    def test_rejects_an_archived_thread(self) -> None:
        self.thread.archived_at = timezone.now()
        self.thread.archive_reason = ArchiveReason.RETURNED
        self.thread.save(update_fields=["archived_at", "archive_reason"])

        with self.assertRaises(ThreadNotWritable):
            MessagingService.send_message(self.thread, self.borrower, "hello")

    def test_rejects_a_thread_archived_since_the_caller_loaded_it(self) -> None:
        # What a request that opened the thread page would still be holding.
        stale = ChatThread.objects.get(pk=self.thread.pk)
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)

        with self.assertRaises(ThreadNotWritable):
            MessagingService.send_message(stale, self.borrower, "snuck in")

        self.assertEqual(self.thread.messages.count(), 1)

    @override_settings(MESSAGING_ENABLED=False)
    def test_refused_while_the_feature_flag_is_off(self) -> None:
        with self.assertRaises(MessagingDisabled):
            MessagingService.send_message(self.thread, self.borrower, "hello")

    def test_hands_every_stored_message_to_dispatch(self) -> None:
        with patch.object(MessagingService, "_dispatch") as dispatch:
            message = MessagingService.send_message(self.thread, self.borrower, "hello")

        dispatch.assert_called_once_with(message)


@override_settings(MESSAGING_ENABLED=True)
class AttachThreadToTransactionTests(MessagingTestCase):
    def test_carries_an_existing_conversation_forward(self) -> None:
        thread = self.make_thread()
        message = MessagingService.send_message(
            thread, self.borrower, "Is this available?"
        )

        attached = MessagingService.attach_thread_to(self.make_transaction())

        self.assertEqual(attached.pk, thread.pk)
        self.assertEqual(ChatThread.objects.count(), 1)
        self.assertEqual(list(attached.messages.order_by("id")), [message])

    def test_creates_a_thread_when_there_was_no_conversation(self) -> None:
        transaction = self.make_transaction()

        thread = MessagingService.attach_thread_to(transaction)

        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.lender, self.lender)
        self.assertEqual(thread.borrower, self.borrower)
        self.assertEqual(thread.item, self.item)

    def test_is_idempotent(self) -> None:
        transaction = self.make_transaction()

        first = MessagingService.attach_thread_to(transaction)
        second = MessagingService.attach_thread_to(transaction)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_ignores_another_borrowers_conversation(self) -> None:
        other_borrower = self.make_user("other")
        other_thread = self.make_thread(borrower=other_borrower)

        attached = MessagingService.attach_thread_to(self.make_transaction())

        self.assertNotEqual(attached.pk, other_thread.pk)
        other_thread.refresh_from_db()
        self.assertIsNone(other_thread.transaction)

    def test_does_not_steal_a_conversation_claimed_mid_flight(self) -> None:
        thread = self.make_thread()
        winner = self.make_transaction()
        stale = ChatThread.objects.get(pk=thread.pk)
        # What a racing caller would have read just before the winner claimed it.
        stale.transaction = None
        with override_settings(MESSAGING_ENABLED=False):
            loser = self.make_transaction()

        with patch.object(
            MessagingService, "_active_prerequest_thread", return_value=stale
        ):
            attached = MessagingService.attach_thread_to(loser)

        self.assertNotEqual(attached.pk, thread.pk)
        self.assertEqual(attached.transaction, loser)
        thread.refresh_from_db()
        self.assertEqual(thread.transaction, winner)

    def test_ignores_an_archived_conversation(self) -> None:
        thread = self.make_thread()
        MessagingService.close_prerequest_thread(thread, self.borrower)

        attached = MessagingService.attach_thread_to(self.make_transaction())

        self.assertNotEqual(attached.pk, thread.pk)

    def test_frees_the_borrower_to_open_a_new_conversation(self) -> None:
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        thread = self.make_thread()
        MessagingService.attach_thread_to(self.make_transaction())

        fresh = MessagingService.get_or_create_prerequest_thread(
            self.borrower, self.item
        )

        self.assertNotEqual(fresh.pk, thread.pk)

    @override_settings(MESSAGING_ENABLED=False)
    def test_ignores_the_feature_flag(self) -> None:
        """
        The flag gates the lifecycle hook, not this call, so a backfill can
        attach threads to existing transactions before the flag is flipped.
        """
        transaction = self.make_transaction()

        thread = MessagingService.attach_thread_to(transaction)

        self.assertEqual(thread.transaction, transaction)


@override_settings(MESSAGING_ENABLED=True)
class ThreadArchivalTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

    def last_message_body(self, thread: ChatThread) -> str:
        message = thread.messages.order_by("id").last()
        assert message is not None
        return message.body

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
        self.assertEqual(
            self.last_message_body(self.thread),
            ARCHIVE_MESSAGES[ArchiveReason.RETURNED],
        )

    def test_the_dispute_notice_is_posted_once(self) -> None:
        first = MessagingService.post_dispute_notice(self.thread)
        second = MessagingService.post_dispute_notice(self.thread)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_archiving_twice_posts_one_notice(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        MessagingService.archive_thread(self.thread, ArchiveReason.CANCELLED)
        self.thread.refresh_from_db()

        self.assertEqual(self.thread.archive_reason, ArchiveReason.RETURNED)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_archiving_twice_from_separate_instances_posts_one_notice(self) -> None:
        stale = ChatThread.objects.get(pk=self.thread.pk)

        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        MessagingService.archive_thread(stale, ArchiveReason.CANCELLED)

        self.thread.refresh_from_db()
        self.assertEqual(self.thread.archive_reason, ArchiveReason.RETURNED)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_archiving_accepts_alternate_copy(self) -> None:
        MessagingService.archive_thread(
            self.thread,
            ArchiveReason.OWNERSHIP_TRANSFERRED,
            message="This item is no longer available. Chat is now archived.",
        )

        self.assertEqual(
            self.last_message_body(self.thread),
            "This item is no longer available. Chat is now archived.",
        )

    def test_either_party_can_close_a_prerequest_thread(self) -> None:
        MessagingService.close_prerequest_thread(self.thread, self.lender)
        self.thread.refresh_from_db()

        self.assertEqual(self.thread.archive_reason, ArchiveReason.CLOSED)
        self.assertEqual(self.thread.updated_by, self.lender)
        self.assertEqual(
            self.last_message_body(self.thread),
            ARCHIVE_MESSAGES[ArchiveReason.CLOSED],
        )

    def test_closing_an_already_archived_thread_is_refused(self) -> None:
        MessagingService.close_prerequest_thread(self.thread, self.borrower)

        with self.assertRaises(ThreadNotWritable):
            MessagingService.close_prerequest_thread(self.thread, self.lender)

    def test_outsiders_cannot_close_a_thread(self) -> None:
        outsider = self.make_user("outsider")

        with self.assertRaises(NotThreadParticipant):
            MessagingService.close_prerequest_thread(self.thread, outsider)

    def test_threads_with_a_transaction_cannot_be_closed(self) -> None:
        self.thread.transaction = self.make_transaction()
        self.thread.save(update_fields=["transaction"])

        with self.assertRaises(PermissionDenied):
            MessagingService.close_prerequest_thread(self.thread, self.borrower)

    def test_closing_a_thread_that_gained_a_transaction_is_refused(self) -> None:
        # The lender's close request read the thread just before the borrower tapped Request Item;
        # closing at that point would lock the live chat. Hence, test it doesn't happen
        stale = ChatThread.objects.get(pk=self.thread.pk)
        self.make_transaction()

        with self.assertRaises(PermissionDenied):
            MessagingService.close_prerequest_thread(stale, self.lender)

        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)
        self.assertIsNotNone(self.thread.transaction_id)

    def test_archives_every_open_conversation_about_an_item(self) -> None:
        other_borrower: BorrowdUser = self.make_user("other")
        other_thread = self.make_thread(borrower=other_borrower)

        MessagingService.archive_prerequest_threads_for_item(
            self.item, ArchiveReason.ITEM_UNAVAILABLE
        )

        for thread in (self.thread, other_thread):
            thread.refresh_from_db()
            self.assertEqual(thread.archive_reason, ArchiveReason.ITEM_UNAVAILABLE)

    def test_archiving_looks_the_system_user_up_once(self) -> None:
        # system user lookup, then savepoint, thread update, message insert, release
        with self.assertNumQueries(5):
            MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)

    def test_leaves_conversations_that_have_a_transaction(self) -> None:
        self.thread.transaction = self.make_transaction()
        self.thread.save(update_fields=["transaction"])

        MessagingService.archive_prerequest_threads_for_item(
            self.item, ArchiveReason.ITEM_UNAVAILABLE
        )

        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

    @override_settings(MESSAGING_ENABLED=False)
    def test_archival_works_while_the_feature_flag_is_off(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.RETURNED)
        self.thread.refresh_from_db()

        self.assertTrue(self.thread.is_archived)
        self.assertEqual(self.thread.messages.count(), 1)
