from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from guardian.shortcuts import assign_perm

from borrowd_messaging.models import ArchiveReason, ChatThread, Message
from borrowd_permissions.models import ItemOLP

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ItemConversationPreviewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("item-detail", args=[self.item.pk])

    def test_lender_sees_the_ten_most_recent_conversations(self) -> None:
        threads = [
            self.make_thread(borrower=self.make_user(f"borrower-{index}"))
            for index in range(11)
        ]
        Message.objects.create(
            thread=threads[0],
            sender=threads[0].borrower,
            body="This makes the first thread the most recent.",
        )
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="item-conversations"')
        self.assertContains(response, "This makes the first thread the most recent.")
        self.assertContains(
            response,
            reverse("chat-thread-detail", args=[threads[0].pk]),
        )
        self.assertNotContains(
            response,
            reverse("chat-thread-detail", args=[threads[1].pk]),
        )
        for thread in threads[2:]:
            self.assertContains(
                response,
                reverse("chat-thread-detail", args=[thread.pk]),
            )

    def test_borrower_sees_only_their_own_conversation(self) -> None:
        own_thread = self.make_thread()
        someone_elses_thread = self.make_thread(borrower=self.make_user("someone-else"))
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="item-conversations"')
        self.assertContains(
            response,
            reverse("chat-thread-detail", args=[own_thread.pk]),
        )
        self.assertNotContains(
            response,
            reverse("chat-thread-detail", args=[someone_elses_thread.pk]),
        )

    def test_unrelated_item_viewer_does_not_see_conversation_history(self) -> None:
        thread = self.make_thread()
        viewer = self.make_user("viewer")
        assign_perm(ItemOLP.VIEW, viewer, self.item)
        self.client.force_login(viewer)

        with patch(
            "borrowd_items.views.build_conversation_summaries"
        ) as build_summaries:
            response = self.client.get(self.url)

        build_summaries.assert_not_called()
        self.assertNotContains(response, 'id="item-conversations"')
        self.assertNotContains(
            response,
            reverse("chat-thread-detail", args=[thread.pk]),
        )

    def test_new_item_owner_does_not_inherit_old_conversations(self) -> None:
        old_thread = self.make_thread()
        new_owner = self.make_user("new-owner")
        self.item.owner = new_owner
        self.item.save(update_fields=["owner"])
        assign_perm(ItemOLP.VIEW, new_owner, self.item)
        self.client.force_login(new_owner)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="item-conversations"')
        self.assertContains(response, "No conversations yet.")
        self.assertNotContains(
            response,
            reverse("chat-thread-detail", args=[old_thread.pk]),
        )

    def test_lender_sees_an_empty_conversation_section(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="item-conversations"')
        self.assertContains(response, "No conversations yet.")

    def test_conversation_section_links_to_the_full_history(self) -> None:
        self.make_thread()
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertContains(
            response,
            reverse("item-conversation-history", args=[self.item.pk]),
        )

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_hides_the_conversation_section(self) -> None:
        self.make_thread()
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="item-conversations"')


@override_settings(MESSAGING_ENABLED=True)
class ItemConversationHistoryViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("item-conversation-history", args=[self.item.pk])

    def test_paginates_conversations_at_twenty_five_per_page(self) -> None:
        threads = self._make_archived_threads(26)
        self.client.force_login(self.lender)

        first_page = self.client.get(self.url)
        second_page = self.client.get(self.url, {"page": 2})

        first_page_summaries = first_page.context["item_conversation_summaries"]
        second_page_summaries = second_page.context["item_conversation_summaries"]
        self.assertEqual(len(first_page_summaries), 25)
        self.assertEqual(len(second_page_summaries), 1)
        self.assertEqual(first_page.context["page_obj"].paginator.per_page, 25)
        self.assertNotIn(
            threads[0].pk,
            {summary.thread_id for summary in first_page_summaries},
        )
        self.assertEqual(second_page_summaries[0].thread_id, threads[0].pk)

    def test_borrower_history_contains_only_their_conversations(self) -> None:
        own_thread = self.make_thread()
        someone_elses_thread = self.make_thread(
            borrower=self.make_user("someone-else-history")
        )
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        summaries = response.context["item_conversation_summaries"]
        self.assertEqual(
            [summary.thread_id for summary in summaries],
            [own_thread.pk],
        )
        self.assertNotContains(
            response,
            reverse("chat-thread-detail", args=[someone_elses_thread.pk]),
        )

    def test_empty_history_has_an_empty_state(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertContains(response, self.item.name)
        self.assertContains(response, "No conversations yet.")

    def test_anonymous_user_is_sent_to_login(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_item_viewer_without_permission_gets_a_404(self) -> None:
        viewer = self.make_user("history-viewer")
        self.client.force_login(viewer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_hides_the_history_page(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def _make_archived_threads(self, count: int) -> list[ChatThread]:
        threads: list[ChatThread] = []
        for _ in range(count):
            thread = self.make_thread()
            archived_at = timezone.now()
            ChatThread.objects.filter(pk=thread.pk).update(
                archived_at=archived_at,
                archive_reason=ArchiveReason.CLOSED,
            )
            thread.archived_at = archived_at
            thread.archive_reason = ArchiveReason.CLOSED
            threads.append(thread)
        return threads
