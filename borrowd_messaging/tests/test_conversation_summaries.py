from datetime import timedelta
from io import BytesIO
from tempfile import mkdtemp

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from borrowd_items.models import Item, ItemPhoto, ListingType, TransactionStatus
from borrowd_messaging.conversation_summaries import (
    HubConversationSummary,
    build_conversation_summaries,
    build_hub_conversation_summaries,
    participant_conversation_threads,
    threads_for_item,
)
from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_messaging.models import ArchiveReason, ChatThread, Message
from borrowd_messaging.read_state import mark_thread_read
from borrowd_messaging.services import MessagingService
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
                threads_for_item(self.item, self.lender),
                self.lender,
            )

        first_summary = next(
            summary for summary in summaries if summary.thread_id == first.pk
        )
        with self.assertNumQueries(0):
            self.assertEqual(first_summary.other_participant, self.borrower)
            self.assertEqual(
                first_summary.other_participant.profile.full_name(),
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
            threads_for_item(self.item, self.borrower).values_list("pk", flat=True)
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
            threads_for_item(self.item, self.lender),
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
            threads_for_item(self.item, self.lender),
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
            threads_for_item(self.item, self.lender),
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


@override_settings(MESSAGING_ENABLED=True)
class ParticipantConversationSummaryTests(MessagingTestCase):
    def test_scope_includes_both_roles_but_never_other_peoples_threads(self) -> None:
        borrowing = self.make_thread()
        lending = self.make_thread(
            item=self.make_item(owner=self.borrower),
            lender=self.borrower,
            borrower=self.lender,
        )
        self.make_thread(borrower=self.make_user("outsider"))

        threads = participant_conversation_threads(self.borrower)

        self.assertEqual(
            set(threads.values_list("pk", flat=True)), {borrowing.pk, lending.pk}
        )
        summaries = build_conversation_summaries(threads, self.borrower)
        self.assertTrue(
            all(summary.other_participant == self.lender for summary in summaries)
        )

    def test_superuser_does_not_gain_other_peoples_conversations(self) -> None:
        self.make_thread()
        outsider = self.make_user("administrator")
        outsider.is_superuser = True
        outsider.save(update_fields=["is_superuser"])

        self.assertFalse(participant_conversation_threads(outsider).exists())

    def test_summary_builder_rejects_an_unrelated_viewer(self) -> None:
        thread = self.make_thread()
        outsider = self.make_user("outsider")

        with self.assertRaises(NotThreadParticipant):
            build_conversation_summaries([thread], outsider)

    def test_query_is_lazy_and_loads_summary_relations_with_item_photos(self) -> None:
        transaction = self.make_transaction(status=TransactionStatus.DISPUTED)
        thread = ChatThread.objects.get(transaction=transaction)
        Message.objects.create(
            thread=thread, sender=self.lender, body="Let's work this out."
        )
        self.make_thread(item=self.make_item(name="Ladder"))
        expected_name = self.lender.profile.full_name()

        with self.assertNumQueries(0):
            query = participant_conversation_threads(self.borrower)
        # One row query, plus one prefetch for the loaded Items' photos.
        with self.assertNumQueries(2):
            threads = list(query)
            summaries = build_conversation_summaries(threads, self.borrower)
            for loaded in threads:
                self.assertIsNotNone(loaded.item)
                self.assertEqual(loaded.lender.profile.full_name(), expected_name)
                self.assertEqual(loaded.borrower.profile.user_id, self.borrower.pk)

        summary = next(
            summary for summary in summaries if summary.thread_id == thread.pk
        )
        self.assertEqual(summary.last_message_preview, "Let's work this out.")
        self.assertEqual(
            (summary.status_label, summary.status_kind), ("Disputed", "disputed")
        )

    def test_empty_threads_use_creation_time_and_ties_use_thread_id(self) -> None:
        older = self.make_thread()
        message = Message.objects.create(
            thread=older, sender=self.lender, body="Old message"
        )
        now = timezone.now()
        Message.objects.filter(pk=message.pk).update(created_at=now - timedelta(days=1))
        first_empty = self.make_thread(item=self.make_item(name="Saw"))
        second_empty = self.make_thread(item=self.make_item(name="Ladder"))
        ChatThread.objects.filter(pk__in=[first_empty.pk, second_empty.pk]).update(
            created_at=now
        )

        summaries = build_conversation_summaries(
            participant_conversation_threads(self.borrower), self.borrower
        )

        self.assertEqual(
            [summary.thread_id for summary in summaries],
            [second_empty.pk, first_empty.pk, older.pk],
        )
        self.assertEqual(summaries[0].last_activity_at, now)
        self.assertIsNone(summaries[0].last_message_preview)

    def test_activity_uses_newest_timestamp_but_preview_uses_delivery_order(
        self,
    ) -> None:
        thread = self.make_thread()
        first = Message.objects.create(
            thread=thread, sender=self.lender, body="First delivered"
        )
        last = Message.objects.create(
            thread=thread, sender=self.borrower, body="Last delivered"
        )
        now = timezone.now()
        Message.objects.filter(pk=first.pk).update(created_at=now)
        Message.objects.filter(pk=last.pk).update(created_at=now - timedelta(hours=1))

        # The item history and Messages list must use the same definition.
        for threads in (
            participant_conversation_threads(self.borrower),
            threads_for_item(self.item, self.borrower),
        ):
            summary = build_conversation_summaries(threads, self.borrower)[0]
            self.assertEqual(summary.last_activity_at, now)
            self.assertEqual(summary.last_message_preview, "Last delivered")

    def test_equal_message_times_choose_the_last_delivered_preview(self) -> None:
        thread = self.make_thread()
        Message.objects.create(thread=thread, sender=self.lender, body="First")
        Message.objects.create(thread=thread, sender=self.borrower, body="Second")
        Message.objects.filter(thread=thread).update(created_at=timezone.now())

        summary = build_conversation_summaries(
            participant_conversation_threads(self.borrower), self.borrower
        )[0]

        self.assertEqual(summary.last_message_preview, "Second")

    def test_unread_state_includes_notices_and_is_independent_for_each_participant(
        self,
    ) -> None:
        thread = self.make_thread()
        notice = MessagingService.post_system_message(thread, "An update.")
        mark_thread_read(thread, self.borrower, through_message_id=notice.pk)
        Message.objects.create(thread=thread, sender=self.borrower, body="My reply")

        borrower_thread = participant_conversation_threads(self.borrower).get(
            pk=thread.pk
        )
        lender_thread = participant_conversation_threads(self.lender).get(pk=thread.pk)

        self.assertFalse(getattr(borrower_thread, "has_unread_messages"))
        self.assertTrue(getattr(lender_thread, "has_unread_messages"))
        summary = build_conversation_summaries([borrower_thread], self.borrower)[0]
        self.assertEqual(summary.last_message_preview, "My reply")

    def test_reading_summaries_does_not_acknowledge_or_update_a_thread(self) -> None:
        thread = self.make_thread()
        MessagingService.post_system_message(thread, "An update.")
        thread.refresh_from_db()
        before = (thread.updated_at, thread.updated_by_id)

        build_conversation_summaries(
            participant_conversation_threads(self.borrower), self.borrower
        )

        thread.refresh_from_db()
        self.assertIsNone(thread.borrower_last_read_message_id)
        self.assertIsNone(thread.lender_last_read_message_id)
        self.assertEqual((thread.updated_at, thread.updated_by_id), before)

    def test_archived_deleted_item_history_keeps_notice_and_unread_state(self) -> None:
        thread = self.make_thread()
        self.item.delete()

        loaded = participant_conversation_threads(self.borrower).get(pk=thread.pk)
        summary = build_conversation_summaries([loaded], self.borrower)[0]

        self.assertIsNone(loaded.item)
        self.assertTrue(getattr(loaded, "has_unread_messages"))
        self.assertEqual(
            (summary.status_label, summary.status_kind), ("Item deleted", "archived")
        )
        self.assertIsNotNone(summary.last_message_preview)

    def test_historical_context_survives_changes_to_live_item_and_group(self) -> None:
        group = self.make_group("Original group")
        thread = self.make_thread(
            conversation_group=group,
            conversation_group_source_id=group.pk,
            conversation_group_name=group.name,
            listing_type=ListingType.LEND,
        )
        group.name = "Renamed group"
        group.save(update_fields=["name"])
        self.item.listing_type = ListingType.GIVEAWAY
        self.item.save(update_fields=["listing_type"])

        loaded = participant_conversation_threads(self.borrower).get(pk=thread.pk)

        self.assertEqual(loaded.conversation_group_name, "Original group")
        self.assertEqual(loaded.conversation_group_source_id, group.pk)
        self.assertEqual(loaded.listing_type, ListingType.LEND)

    def test_query_can_be_split_and_sliced_before_loading_summaries(self) -> None:
        active = self.make_thread()
        ChatThread.objects.bulk_create(
            [
                ChatThread(
                    item=self.item,
                    lender=self.lender,
                    borrower=self.borrower,
                    created_by=self.borrower,
                    updated_by=self.borrower,
                    archived_at=timezone.now(),
                    archive_reason=ArchiveReason.CLOSED,
                )
                for _ in range(26)
            ]
        )
        query = participant_conversation_threads(self.borrower)

        self.assertEqual(list(query.filter(archived_at__isnull=True)), [active])
        archived = query.filter(archived_at__isnull=False)
        self.assertEqual(archived.count(), 26)
        # The photo prefetch follows the slice, so it stays one page wide.
        with self.assertNumQueries(2):
            summaries = build_conversation_summaries(archived[:25], self.borrower)
        self.assertEqual(len(summaries), 25)

    def test_both_entry_points_use_the_same_unread_definition(self) -> None:
        thread = self.make_thread()
        notice = MessagingService.post_system_message(thread, "An update.")

        for threads in (
            participant_conversation_threads(self.borrower),
            threads_for_item(self.item, self.borrower),
        ):
            self.assertTrue(
                build_conversation_summaries(threads, self.borrower)[
                    0
                ].has_unread_messages
            )

        mark_thread_read(thread, self.borrower, through_message_id=notice.pk)

        for threads in (
            participant_conversation_threads(self.borrower),
            threads_for_item(self.item, self.borrower),
        ):
            self.assertFalse(
                build_conversation_summaries(threads, self.borrower)[
                    0
                ].has_unread_messages
            )


@override_settings(MESSAGING_ENABLED=True, MEDIA_ROOT=mkdtemp())
class HubConversationSummaryTests(MessagingTestCase):
    """The extra Item context and unread state the Messages hub cards show."""

    def add_photo(self, item: Item) -> ItemPhoto:
        image = Image.new("RGB", (40, 40), color="red")
        content = BytesIO()
        image.save(content, format="JPEG")
        return ItemPhoto.objects.create(
            item=item,
            image=SimpleUploadedFile(
                name="photo.jpg", content=content.getvalue(), content_type="image/jpeg"
            ),
            created_by=self.lender,
            updated_by=self.lender,
        )

    def hub_cards(self, viewer: BorrowdUser) -> list[HubConversationSummary]:
        return build_hub_conversation_summaries(
            participant_conversation_threads(viewer), viewer
        )

    def test_card_carries_the_item_name_thumbnail_and_unread_state(self) -> None:
        thread = self.make_thread()
        photo = self.add_photo(self.item)
        Message.objects.create(thread=thread, sender=self.lender, body="Hello")

        card = self.hub_cards(self.borrower)[0]

        self.assertEqual(card.conversation.thread_id, thread.pk)
        self.assertEqual(card.item_name, self.item.name)
        self.assertEqual(card.item_thumbnail_url, photo.thumbnail.url)
        self.assertTrue(card.conversation.has_unread_messages)

    def test_acknowledged_conversation_is_not_marked_unread(self) -> None:
        thread = self.make_thread()
        message = Message.objects.create(
            thread=thread, sender=self.lender, body="Hello"
        )
        mark_thread_read(thread, self.borrower, through_message_id=message.pk)

        card = self.hub_cards(self.borrower)[0]

        self.assertFalse(card.conversation.has_unread_messages)

    def test_a_soft_deleted_item_keeps_its_name_and_photo(self) -> None:
        self.make_thread()
        photo = self.add_photo(self.item)
        self.item.soft_delete(deleted_by=self.lender)

        card = self.hub_cards(self.borrower)[0]

        self.assertEqual(card.item_name, self.item.name)
        self.assertEqual(card.item_thumbnail_url, photo.thumbnail.url)
        self.assertTrue(card.item_removed)

    def test_a_hard_deleted_item_leaves_the_name_and_thumbnail_empty(self) -> None:
        self.make_thread()
        self.add_photo(self.item)
        self.item.delete()

        card = self.hub_cards(self.borrower)[0]

        self.assertIsNone(card.item_name)
        self.assertIsNone(card.item_thumbnail_url)
        self.assertFalse(card.item_removed)

    def test_an_item_without_a_photo_still_names_the_item(self) -> None:
        self.make_thread()

        card = self.hub_cards(self.borrower)[0]

        self.assertEqual(card.item_name, self.item.name)
        self.assertIsNone(card.item_thumbnail_url)
        self.assertFalse(card.item_removed)

    def test_a_missing_photo_file_does_not_break_the_card(self) -> None:
        self.make_thread()
        photo = self.add_photo(self.item)
        photo.image.storage.delete(photo.image.name)

        card = self.hub_cards(self.borrower)[0]

        self.assertEqual(card.item_name, self.item.name)
        self.assertIsNone(card.item_thumbnail_url)

    def test_cards_load_their_photos_without_a_query_per_row(self) -> None:
        for name in ("Ladder", "Projector", "Saw"):
            item = self.make_item(name=name)
            self.add_photo(item)
            self.make_thread(item=item)
        query = participant_conversation_threads(self.borrower)

        # One row query and one photo prefetch, however many rows there are.
        with self.assertNumQueries(2):
            cards = build_hub_conversation_summaries(query, self.borrower)

        self.assertEqual(len(cards), 3)
        self.assertTrue(all(card.item_thumbnail_url for card in cards))

    def test_card_template_shows_the_item_context_and_the_unread_mark(self) -> None:
        thread = self.make_thread()
        Message.objects.create(thread=thread, sender=self.lender, body="Hello")
        card = self.hub_cards(self.borrower)[0]

        with self.assertNumQueries(0):
            html = render_to_string(
                "messaging/_thread_summary_card.html",
                {
                    "summary": card.conversation,
                    "show_item": True,
                    "item_name": card.item_name,
                    "item_thumbnail_url": card.item_thumbnail_url,
                },
            )

        self.assertIn(self.item.name, html)
        self.assertIn("Unread.", html)
        self.assertNotIn("Item unavailable", html)

    def test_card_template_names_an_item_whose_row_is_gone(self) -> None:
        self.make_thread()
        self.item.delete()
        card = self.hub_cards(self.borrower)[0]

        html = render_to_string(
            "messaging/_thread_summary_card.html",
            {
                "summary": card.conversation,
                "show_item": True,
                "item_name": card.item_name,
                "item_thumbnail_url": card.item_thumbnail_url,
                "item_removed": card.item_removed,
            },
        )

        self.assertIn("Item unavailable", html)
