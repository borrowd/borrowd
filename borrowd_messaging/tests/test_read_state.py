from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

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
        mark_thread_read(self.thread, self.borrower, through_message_id=self.message.pk)

        self.assertFalse(
            mark_thread_read(
                self.thread, self.borrower, through_message_id=self.message.pk
            )
        )
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)

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

    def test_only_the_other_participants_human_messages_count(self) -> None:
        outsider = self.make_user("outsider")
        for sender, is_system in (
            (self.borrower, False),
            (get_system_user(), True),
            (self.lender, True),
            (outsider, False),
        ):
            Message.objects.create(
                thread=self.thread,
                sender=sender,
                is_system=is_system,
                body="Does not count as incoming human chat.",
            )

        self.assertFalse(unread_threads_for(self.borrower).exists())
        Message.objects.create(
            thread=self.thread, sender=self.lender, body="An incoming message."
        )
        self.assertEqual(unread_threads_for(self.borrower).count(), 1)

    def test_later_own_and_system_messages_do_not_hide_unread_messages(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.lender, body="Can you come Saturday?"
        )
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="My response."
        )
        MessagingService.post_system_message(self.thread, "A system notice.")

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

        self.assertEqual(list(threads_with_unread_state(self.borrower)), [self.thread])
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_archiving_keeps_unread_incoming_messages(self) -> None:
        message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Final arrangements."
        )
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)

        self.assertEqual(list(unread_threads_for(self.borrower)), [self.thread])
        mark_thread_read(self.thread, self.borrower, through_message_id=message.pk)
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
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_multiple_messages_count_once_per_thread_in_one_query(self) -> None:
        second_thread = self.make_thread(item=self.make_item(name="Ladder"))
        for thread in (self.thread, second_thread):
            for _ in range(3):
                Message.objects.create(
                    thread=thread, sender=self.lender, body="An unread message."
                )

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
