from django.db import IntegrityError
from django.db.transaction import atomic
from django.utils import timezone

from borrowd_items.models import ListingType
from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_messaging.models import ArchiveReason, Message
from borrowd_messaging.tests.base import MessagingTestCase


class ChatThreadModelTests(MessagingTestCase):
    def test_conversation_context_defaults_to_unknown(self) -> None:
        thread = self.make_thread()

        self.assertIsNone(thread.conversation_group)
        self.assertIsNone(thread.conversation_group_source_id)
        self.assertIsNone(thread.conversation_group_name)
        self.assertIsNone(thread.listing_type)

    def test_conversation_context_accepts_group_snapshots(self) -> None:
        group = self.make_group(name="Tool Library")

        thread = self.make_thread(
            conversation_group=group,
            conversation_group_source_id=group.pk,
            conversation_group_name=group.name,
            listing_type=ListingType.GIVEAWAY,
        )
        thread.refresh_from_db()

        self.assertEqual(thread.conversation_group, group)
        self.assertEqual(thread.conversation_group_source_id, group.pk)
        self.assertEqual(thread.conversation_group_name, "Tool Library")
        self.assertEqual(thread.listing_type, ListingType.GIVEAWAY)

    def test_live_conversation_group_requires_both_snapshots(self) -> None:
        group = self.make_group()

        with self.assertRaises(IntegrityError), atomic():
            self.make_thread(conversation_group=group)

    def test_group_context_rejects_partial_snapshots(self) -> None:
        invalid_contexts = (
            {"conversation_group_source_id": 42},
            {"conversation_group_name": "Tool Library"},
        )

        for context in invalid_contexts:
            with self.subTest(context=context):
                with self.assertRaises(IntegrityError), atomic():
                    self.make_thread(**context)

    def test_historical_group_snapshots_do_not_require_live_group(self) -> None:
        thread = self.make_thread(
            conversation_group_source_id=42,
            conversation_group_name="Former Tool Library",
        )

        self.assertIsNone(thread.conversation_group)
        self.assertEqual(thread.conversation_group_source_id, 42)
        self.assertEqual(thread.conversation_group_name, "Former Tool Library")

    def test_group_deletion_preserves_conversation_snapshots(self) -> None:
        group = self.make_group(name="Tool Library")
        group_id = group.pk
        thread = self.make_thread(
            conversation_group=group,
            conversation_group_source_id=group_id,
            conversation_group_name=group.name,
        )

        group.delete()
        thread.refresh_from_db()

        self.assertIsNone(thread.conversation_group)
        self.assertEqual(thread.conversation_group_source_id, group_id)
        self.assertEqual(thread.conversation_group_name, "Tool Library")

    def test_second_active_prerequest_thread_is_rejected(self) -> None:
        self.make_thread()

        with self.assertRaises(IntegrityError), atomic():
            self.make_thread()

    def test_new_prerequest_thread_allowed_once_previous_has_transaction(self) -> None:
        first = self.make_thread()
        first.transaction = self.make_transaction()
        first.save(update_fields=["transaction"])

        second = self.make_thread()

        self.assertNotEqual(first.pk, second.pk)

    def test_new_prerequest_thread_allowed_once_previous_is_archived(self) -> None:
        first = self.make_thread()
        first.archived_at = timezone.now()
        first.archive_reason = ArchiveReason.CLOSED
        first.save(update_fields=["archived_at", "archive_reason"])

        second = self.make_thread()

        self.assertNotEqual(first.pk, second.pk)

    def test_other_borrowers_can_open_threads_on_same_item(self) -> None:
        other_borrower = self.make_user("other")
        self.make_thread()

        thread = self.make_thread(borrower=other_borrower)

        self.assertEqual(thread.borrower, other_borrower)

    def test_transaction_can_only_have_one_thread(self) -> None:
        txn = self.make_transaction()
        self.make_thread(transaction=txn)

        # A different borrower, so only the OneToOne can be what trips.
        with self.assertRaises(IntegrityError), atomic():
            self.make_thread(transaction=txn, borrower=self.make_user("other"))

    def test_a_user_cannot_chat_with_themselves(self) -> None:
        with self.assertRaises(IntegrityError), atomic():
            self.make_thread(borrower=self.lender)

    def test_is_archived_reflects_archived_at(self) -> None:
        thread = self.make_thread()
        self.assertFalse(thread.is_archived)

        thread.archived_at = timezone.now()

        self.assertTrue(thread.is_archived)

    def test_mark_read_writes_the_callers_own_column(self) -> None:
        thread = self.make_thread()

        thread.mark_read(self.borrower)
        thread.refresh_from_db()

        self.assertIsNotNone(thread.borrower_last_read_at)
        self.assertIsNone(thread.lender_last_read_at)
        self.assertEqual(
            thread.last_read_at_for(self.borrower), thread.borrower_last_read_at
        )

    def test_mark_read_by_lender_writes_lender_column(self) -> None:
        thread = self.make_thread()

        thread.mark_read(self.lender)
        thread.refresh_from_db()

        self.assertIsNotNone(thread.lender_last_read_at)
        self.assertIsNone(thread.borrower_last_read_at)

    def test_mark_read_leaves_the_audit_fields_alone(self) -> None:
        thread = self.make_thread()
        updated_at = thread.updated_at

        thread.mark_read(self.borrower)
        thread.refresh_from_db()

        self.assertEqual(thread.updated_at, updated_at)
        self.assertEqual(thread.updated_by, self.borrower)

    def test_read_helpers_reject_non_participants(self) -> None:
        outsider = self.make_user("outsider")
        thread = self.make_thread()

        with self.assertRaises(NotThreadParticipant):
            thread.mark_read(outsider)
        with self.assertRaises(NotThreadParticipant):
            thread.last_read_at_for(outsider)


class MessageModelTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

    def test_empty_body_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError), atomic():
            Message.objects.create(
                thread=self.thread,
                sender=self.borrower,
                body="",
            )

    def test_messages_read_back_in_send_order_by_pk(self) -> None:
        first = Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Is this available?"
        )
        second = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Yes it is."
        )

        messages = list(self.thread.messages.order_by("id"))

        self.assertEqual(messages, [first, second])
        self.assertLess(first.pk, second.pk)
