from datetime import timedelta

from django.template.loader import render_to_string
from django.test import override_settings
from django.utils import timezone

from borrowd_items.models import TransactionStatus
from borrowd_messaging.models import ArchiveReason, ChatThread, Message
from borrowd_messaging.thread_summaries import (
    build_conversation_summaries,
    item_conversation_threads,
)
from borrowd_users.models import BorrowdUser

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=False)
class ItemConversationSummaryTests(MessagingTestCase):
    def test_summaries_load_card_data_in_one_query(self) -> None:
        other_borrower = self.make_user("other-borrower")
        first = self.make_thread()
        second = self.make_thread(borrower=other_borrower)
        latest_message = Message.objects.create(
            thread=first,
            sender=self.borrower,
            body="Saturday morning works for me.",
        )
        Message.objects.create(
            thread=second,
            sender=other_borrower,
            body="Is this still available?",
        )

        with self.assertNumQueries(1):
            summaries = build_conversation_summaries(
                item_conversation_threads(self.item, self.lender),
                self.lender,
            )

        first_summary = next(
            summary for summary in summaries if summary.thread_id == first.pk
        )
        with self.assertNumQueries(0):
            self.assertEqual(first_summary.other_party, self.borrower)
            self.assertEqual(
                first_summary.other_party.profile.full_name(),
                self.borrower.profile.full_name(),
            )
            self.assertEqual(
                first_summary.last_message_preview,
                "Saturday morning works for me.",
            )
            self.assertEqual(first_summary.last_activity_at, latest_message.created_at)

    def test_item_query_is_scoped_to_the_viewer_and_item(self) -> None:
        own_thread = self.make_thread()
        other_item_thread = self.make_thread(item=self.make_item(name="Saw"))
        stranger = self.make_user("stranger")
        strangers_thread = self.make_thread(borrower=stranger)

        thread_ids = set(
            item_conversation_threads(self.item, self.borrower).values_list(
                "pk", flat=True
            )
        )

        self.assertEqual(thread_ids, {own_thread.pk})
        self.assertNotIn(other_item_thread.pk, thread_ids)
        self.assertNotIn(strangers_thread.pk, thread_ids)

    def test_threads_are_sorted_by_latest_activity(self) -> None:
        older = self.make_thread()
        older_message = Message.objects.create(
            thread=older,
            sender=self.borrower,
            body="Older",
        )
        Message.objects.filter(pk=older_message.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        newer = self.make_thread(borrower=self.make_user("newer-borrower"))

        summaries = build_conversation_summaries(
            item_conversation_threads(self.item, self.lender),
            self.lender,
        )

        self.assertEqual(
            [summary.thread_id for summary in summaries],
            [newer.pk, older.pk],
        )
        self.assertIsNone(summaries[0].last_message_preview)

    def test_status_labels_cover_each_conversation_state(self) -> None:
        prerequest = self.make_thread()
        active = self._make_transaction_thread(
            borrower=self.make_user("active-borrower"),
            status=TransactionStatus.COLLECTED,
        )
        disputed = self._make_transaction_thread(
            borrower=self.make_user("disputed-borrower"),
            status=TransactionStatus.DISPUTED,
        )
        archived = self.make_thread(borrower=self.make_user("archived-borrower"))
        archived.archived_at = timezone.now()
        archived.archive_reason = ArchiveReason.RETURNED
        archived.save(update_fields=["archived_at", "archive_reason"])

        summaries = build_conversation_summaries(
            item_conversation_threads(self.item, self.lender),
            self.lender,
        )
        statuses = {
            summary.thread_id: (summary.status_label, summary.status_kind)
            for summary in summaries
        }

        self.assertEqual(statuses[prerequest.pk], ("Pre-request", "prerequest"))
        self.assertEqual(statuses[active.pk], ("Active", "active"))
        self.assertEqual(statuses[disputed.pk], ("Disputed", "disputed"))
        self.assertEqual(statuses[archived.pk], ("Returned", "archived"))

    def test_card_renders_summary_details_without_more_queries(self) -> None:
        thread = self.make_thread()
        thread.created_at = timezone.now() - timedelta(days=3)
        thread.archived_at = timezone.now()
        thread.archive_reason = ArchiveReason.CANCELLED
        thread.save(update_fields=["created_at", "archived_at", "archive_reason"])
        Message.objects.create(
            thread=thread,
            sender=self.borrower,
            body="Maybe another time.",
        )
        summary = build_conversation_summaries(
            item_conversation_threads(self.item, self.lender),
            self.lender,
        )[0]

        with self.assertNumQueries(0):
            html = render_to_string(
                "messaging/_thread_summary_card.html",
                {"summary": summary},
            )

        self.assertIn(self.borrower.profile.full_name(), html)
        self.assertIn("Cancelled", html)
        self.assertIn("Maybe another time.", html)
        self.assertIn(f"/messages/{thread.pk}/", html)
        self.assertNotIn("Present", html)

    def _make_transaction_thread(
        self,
        *,
        borrower: BorrowdUser,
        status: TransactionStatus,
    ) -> ChatThread:
        transaction = self.make_transaction(borrower=borrower, status=status)
        return self.make_thread(borrower=borrower, transaction=transaction)
