from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings

from borrowd_messaging.exceptions import (
    InvalidReadCursor,
    MessagingDisabled,
    NotThreadParticipant,
)
from borrowd_messaging.models import ArchiveReason, ChatThread, Message
from borrowd_messaging.read_state import (
    mark_thread_read,
    threads_with_unread_state,
    unread_threads_for,
)
from borrowd_messaging.services import MessagingService
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ReadCursorTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Saturday works for me."
        )

    def test_each_participant_advances_only_their_own_cursor(self) -> None:
        self.assertTrue(
            mark_thread_read(
                self.thread, self.borrower, through_message_id=self.message.pk
            )
        )
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)
        self.assertIsNone(self.thread.lender_last_read_message_id)

        self.assertTrue(
            mark_thread_read(
                self.thread, self.lender, through_message_id=self.message.pk
            )
        )
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.lender_last_read_message_id, self.message.pk)
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)

    def test_delayed_acknowledgment_cannot_overwrite_a_newer_cursor(self) -> None:
        older_tab = ChatThread.objects.get(pk=self.thread.pk)
        newer_message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Come after noon."
        )
        mark_thread_read(
            self.thread, self.borrower, through_message_id=newer_message.pk
        )

        self.assertFalse(
            mark_thread_read(
                older_tab, self.borrower, through_message_id=self.message.pk
            )
        )

        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, newer_message.pk)

    def test_repeated_acknowledgments_are_idempotent(self) -> None:
        with patch(
            "borrowd_messaging.read_state.clear_message_notification_through"
        ) as clear_notification:
            mark_thread_read(
                self.thread,
                self.borrower,
                through_message_id=self.message.pk,
            )

            self.assertFalse(
                mark_thread_read(
                    self.thread,
                    self.borrower,
                    through_message_id=self.message.pk,
                )
            )

        clear_notification.assert_called_once()
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)

    def test_notification_state_failure_rolls_back_the_cursor(self) -> None:
        with patch(
            "borrowd_messaging.read_state.clear_message_notification_through",
            side_effect=RuntimeError("notification state unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                mark_thread_read(
                    self.thread,
                    self.borrower,
                    through_message_id=self.message.pk,
                )

        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_zero_leaves_empty_and_existing_cursors_unchanged(self) -> None:
        empty_thread = self.make_thread(item=self.make_item(name="Ladder"))
        self.assertFalse(
            mark_thread_read(empty_thread, self.borrower, through_message_id=0)
        )
        empty_thread.refresh_from_db()
        self.assertIsNone(empty_thread.borrower_last_read_message_id)

        mark_thread_read(self.thread, self.borrower, through_message_id=self.message.pk)
        self.assertFalse(
            mark_thread_read(self.thread, self.borrower, through_message_id=0)
        )
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)

    def test_invalid_cursors_leave_read_state_unchanged(self) -> None:
        other_thread = self.make_thread(item=self.make_item(name="Ladder"))
        foreign_message = Message.objects.create(
            thread=other_thread, sender=self.lender, body="Another conversation."
        )
        for cursor in (-1, foreign_message.pk, foreign_message.pk + 1000, 2**100):
            with self.subTest(cursor=cursor):
                with self.assertRaises(InvalidReadCursor):
                    mark_thread_read(
                        self.thread, self.borrower, through_message_id=cursor
                    )
                self.thread.refresh_from_db()
                self.assertIsNone(self.thread.borrower_last_read_message_id)
                self.assertIsNone(self.thread.lender_last_read_message_id)

    def test_non_participant_cannot_acknowledge_any_cursor(self) -> None:
        outsider = self.make_user("outsider")
        for cursor in (0, self.message.pk):
            with self.subTest(cursor=cursor):
                with self.assertRaises(NotThreadParticipant):
                    mark_thread_read(self.thread, outsider, through_message_id=cursor)

        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)
        self.assertIsNone(self.thread.lender_last_read_message_id)

    @override_settings(MESSAGING_ENABLED=False)
    def test_disabled_messaging_blocks_acknowledgments(self) -> None:
        with self.assertRaises(MessagingDisabled):
            mark_thread_read(
                self.thread, self.borrower, through_message_id=self.message.pk
            )

        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_reading_does_not_change_activity_or_archive_context(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        before = (
            self.thread.created_at,
            self.thread.updated_at,
            self.thread.updated_by_id,
            self.thread.archived_at,
            self.thread.archive_reason,
        )
        message_count = self.thread.messages.count()

        self.assertTrue(
            mark_thread_read(
                self.thread, self.borrower, through_message_id=self.message.pk
            )
        )

        self.thread.refresh_from_db()
        self.assertEqual(
            (
                self.thread.created_at,
                self.thread.updated_at,
                self.thread.updated_by_id,
                self.thread.archived_at,
                self.thread.archive_reason,
            ),
            before,
        )
        self.assertEqual(self.thread.messages.count(), message_count)

    def test_own_and_system_messages_can_be_rendered_cursors(self) -> None:
        for sender, is_system in ((self.borrower, False), (get_system_user(), True)):
            with self.subTest(is_system=is_system):
                message = Message.objects.create(
                    thread=self.thread,
                    sender=sender,
                    is_system=is_system,
                    body="Latest rendered message.",
                )
                self.assertTrue(
                    mark_thread_read(
                        self.thread, self.borrower, through_message_id=message.pk
                    )
                )
                self.thread.refresh_from_db()
                self.assertEqual(self.thread.borrower_last_read_message_id, message.pk)
                self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_acknowledgment_leaves_later_messages_unread_even_with_equal_times(
        self,
    ) -> None:
        newer_message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="One more thing."
        )
        Message.objects.filter(pk=newer_message.pk).update(
            created_at=self.message.created_at
        )

        mark_thread_read(self.thread, self.borrower, through_message_id=self.message.pk)

        self.assertTrue(unread_threads_for(self.borrower).exists())
        mark_thread_read(
            self.thread, self.borrower, through_message_id=newer_message.pk
        )
        self.assertFalse(unread_threads_for(self.borrower).exists())


@override_settings(MESSAGING_ENABLED=True)
class UnreadThreadQueryTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

    def test_empty_thread_has_no_unread_messages(self) -> None:
        self.assertEqual(
            list(
                threads_with_unread_state(self.borrower).values_list(
                    "pk", "has_unread_messages"
                )
            ),
            [(self.thread.pk, False)],
        )
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_own_and_unrelated_human_messages_do_not_count(self) -> None:
        outsider = self.make_user("outsider")
        for sender in (self.borrower, get_system_user(), outsider):
            Message.objects.create(
                thread=self.thread,
                sender=sender,
                is_system=False,
                body="Does not count as incoming human chat.",
            )

        self.assertFalse(unread_threads_for(self.borrower).exists())
        Message.objects.create(
            thread=self.thread, sender=self.lender, body="An incoming message."
        )
        self.assertEqual(unread_threads_for(self.borrower).count(), 1)

    def test_system_notices_need_each_participants_acknowledgment(self) -> None:
        for sender in (get_system_user(), self.lender, self.borrower):
            with self.subTest(sender=sender.pk):
                notice = MessagingService.post_system_message(
                    self.thread, "A conversation update.", sender=sender
                )
                for viewer in (self.lender, self.borrower):
                    self.assertEqual(list(unread_threads_for(viewer)), [self.thread])

                mark_thread_read(
                    self.thread, self.borrower, through_message_id=notice.pk
                )

                self.assertFalse(unread_threads_for(self.borrower).exists())
                self.assertTrue(unread_threads_for(self.lender).exists())
                mark_thread_read(self.thread, self.lender, through_message_id=notice.pk)
                self.assertFalse(unread_threads_for(self.lender).exists())

    def test_read_notice_does_not_hide_a_later_notice_or_human_message(self) -> None:
        notice = MessagingService.post_system_message(self.thread, "First notice.")
        later_notice = MessagingService.post_system_message(
            self.thread, "Second notice."
        )
        mark_thread_read(self.thread, self.borrower, through_message_id=notice.pk)
        self.assertTrue(unread_threads_for(self.borrower).exists())
        mark_thread_read(self.thread, self.borrower, through_message_id=later_notice.pk)
        self.assertFalse(unread_threads_for(self.borrower).exists())

        message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="One more thing."
        )
        self.assertTrue(unread_threads_for(self.borrower).exists())
        mark_thread_read(self.thread, self.borrower, through_message_id=message.pk)
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_later_own_messages_do_not_hide_unread_incoming_messages(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.lender, body="Can you come Saturday?"
        )
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="My response."
        )
        self.assertTrue(unread_threads_for(self.borrower).exists())

    def test_each_threads_viewer_role_selects_the_right_cursor(self) -> None:
        lending_thread = self.make_thread(
            item=self.make_item(owner=self.borrower),
            lender=self.borrower,
            borrower=self.lender,
        )
        borrowed_message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="I can lend this."
        )
        lent_message = Message.objects.create(
            thread=lending_thread, sender=self.lender, body="Can I borrow this?"
        )

        self.assertEqual(unread_threads_for(self.borrower).count(), 2)
        mark_thread_read(
            self.thread, self.borrower, through_message_id=borrowed_message.pk
        )
        self.assertEqual(
            dict(
                threads_with_unread_state(self.borrower).values_list(
                    "pk", "has_unread_messages"
                )
            ),
            {self.thread.pk: False, lending_thread.pk: True},
        )
        mark_thread_read(
            lending_thread, self.borrower, through_message_id=lent_message.pk
        )
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_queries_exclude_unrelated_conversations(self) -> None:
        other_thread = self.make_thread(borrower=self.make_user("outsider"))
        Message.objects.create(
            thread=other_thread, sender=self.lender, body="Private conversation."
        )
        MessagingService.post_system_message(other_thread, "A private notice.")

        self.assertEqual(list(threads_with_unread_state(self.borrower)), [self.thread])
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_archiving_keeps_unread_incoming_messages(self) -> None:
        message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Final arrangements."
        )
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)

        self.assertEqual(list(unread_threads_for(self.borrower)), [self.thread])
        mark_thread_read(self.thread, self.borrower, through_message_id=message.pk)
        self.assertTrue(unread_threads_for(self.borrower).exists())
        closing_notice = self.thread.messages.latest("pk")
        self.assertTrue(closing_notice.is_system)
        mark_thread_read(
            self.thread, self.borrower, through_message_id=closing_notice.pk
        )
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_item_removal_preserves_unread_history_and_read_access(self) -> None:
        message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Keep this conversation."
        )
        self.item.delete()
        self.thread.refresh_from_db()

        self.assertIsNone(self.thread.item_id)
        self.assertEqual(list(unread_threads_for(self.borrower)), [self.thread])
        mark_thread_read(self.thread, self.borrower, through_message_id=message.pk)
        self.assertTrue(unread_threads_for(self.borrower).exists())
        deletion_notice = self.thread.messages.latest("pk")
        self.assertTrue(deletion_notice.is_system)
        mark_thread_read(
            self.thread, self.borrower, through_message_id=deletion_notice.pk
        )
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_multiple_messages_count_once_per_thread_in_one_query(self) -> None:
        second_thread = self.make_thread(item=self.make_item(name="Ladder"))
        for thread in (self.thread, second_thread):
            for _ in range(3):
                Message.objects.create(
                    thread=thread, sender=self.lender, body="An unread message."
                )
            MessagingService.post_system_message(thread, "An unread notice.")

        with self.assertNumQueries(1):
            self.assertEqual(unread_threads_for(self.borrower).count(), 2)
        with self.assertNumQueries(1):
            states = dict(
                threads_with_unread_state(self.borrower).values_list(
                    "pk", "has_unread_messages"
                )
            )
        self.assertEqual(states, {self.thread.pk: True, second_thread.pk: True})


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL concurrency.")
@override_settings(MESSAGING_ENABLED=True)
class ConcurrentReadCursorTests(TransactionTestCase):
    def test_concurrent_acknowledgments_keep_the_greatest_cursor(self) -> None:
        lender = BorrowdUser.objects.create_user(username="lender")
        borrower = BorrowdUser.objects.create_user(username="borrower")
        thread = ChatThread.objects.create(
            lender=lender, borrower=borrower, created_by=borrower, updated_by=borrower
        )
        messages = [
            Message.objects.create(thread=thread, sender=lender, body=body)
            for body in ("First message.", "Second message.")
        ]
        ready = Barrier(2, timeout=10)

        def acknowledge(through_message_id: int) -> bool:
            close_old_connections()
            try:
                tab_thread = ChatThread.objects.get(pk=thread.pk)
                ready.wait()
                return mark_thread_read(
                    tab_thread, borrower, through_message_id=through_message_id
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(acknowledge, [message.pk for message in messages])
            )

        self.assertTrue(any(results))
        thread.refresh_from_db()
        self.assertEqual(thread.borrower_last_read_message_id, messages[-1].pk)
        self.assertIsNone(thread.lender_last_read_message_id)

    def test_message_send_waits_for_read_acknowledgment_to_commit(self) -> None:
        lender = BorrowdUser.objects.create_user(username="lock-lender")
        borrower = BorrowdUser.objects.create_user(username="lock-borrower")
        thread = ChatThread.objects.create(
            lender=lender,
            borrower=borrower,
            created_by=borrower,
            updated_by=borrower,
        )
        message = Message.objects.create(
            thread=thread,
            sender=lender,
            body="Free Saturday?",
        )
        read_follow_up_started = Event()
        allow_read_to_commit = Event()
        send_started = Event()
        send_finished = Event()

        def pause_read_follow_up(
            thread: ChatThread,
            reader: BorrowdUser,
            *,
            through_message_id: int,
        ) -> bool:
            read_follow_up_started.set()
            if not allow_read_to_commit.wait(timeout=10):
                raise TimeoutError("Timed out waiting to finish the read transaction.")
            return False

        def acknowledge_message() -> bool:
            close_old_connections()
            try:
                return mark_thread_read(
                    ChatThread.objects.get(pk=thread.pk),
                    BorrowdUser.objects.get(pk=borrower.pk),
                    through_message_id=message.pk,
                )
            finally:
                connections.close_all()

        def send_another_message() -> int:
            close_old_connections()
            try:
                send_started.set()
                sent = MessagingService.send_message(
                    ChatThread.objects.get(pk=thread.pk),
                    BorrowdUser.objects.get(pk=lender.pk),
                    "Or Sunday?",
                )
                send_finished.set()
                return sent.pk
            finally:
                connections.close_all()

        with patch(
            "borrowd_messaging.read_state.clear_message_notification_through",
            side_effect=pause_read_follow_up,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                try:
                    read_result = executor.submit(acknowledge_message)
                    self.assertTrue(read_follow_up_started.wait(timeout=10))
                    send_result = executor.submit(send_another_message)
                    self.assertTrue(send_started.wait(timeout=10))
                    self.assertFalse(send_finished.wait(timeout=0.5))
                finally:
                    allow_read_to_commit.set()

                self.assertTrue(read_result.result(timeout=10))
                sent_message_id = send_result.result(timeout=10)

        thread.refresh_from_db()
        self.assertEqual(thread.borrower_last_read_message_id, message.pk)
        self.assertTrue(Message.objects.filter(pk=sent_message_id).exists())
