from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse
from guardian.shortcuts import assign_perm

from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import ItemStatus
from borrowd_messaging.models import ChatThread
from borrowd_permissions.models import ItemOLP

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadPreRequestOpenViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.url = reverse("chat-thread-pre-request-open", args=[self.item.pk])

    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_opens_a_new_pre_request_conversation(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        thread = ChatThread.objects.get()
        self.assertRedirects(
            response,
            reverse("chat-thread-detail", args=[thread.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(thread.item, self.item)
        self.assertEqual(thread.lender, self.lender)
        self.assertEqual(thread.borrower, self.borrower)
        self.assertIsNone(thread.transaction)

    def test_reopens_the_existing_pre_request_conversation(self) -> None:
        existing = self.make_thread()
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("chat-thread-detail", args=[existing.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(ChatThread.objects.count(), 1)

    def test_snapshots_an_explicit_eligible_group(self) -> None:
        self._make_eligible_group("Group A")
        selected = self._make_eligible_group("Group B")
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url,
            {"conversation_group": selected.pk},
        )

        thread = ChatThread.objects.get()
        self.assertRedirects(
            response,
            reverse("chat-thread-detail", args=[thread.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(thread.conversation_group, selected)
        self.assertEqual(thread.conversation_group_source_id, selected.pk)
        self.assertEqual(thread.conversation_group_name, "Group B")

    def test_requires_a_group_when_multiple_are_eligible(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.exists())
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["Choose a group for this conversation."],
        )

    def test_rejects_an_ineligible_group(self) -> None:
        ineligible = self.make_group(name="Lender only")
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url,
            {"conversation_group": ineligible.pk},
        )

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.exists())
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["The selected group is not available for this conversation."],
        )

    def test_rejects_a_malformed_group(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url,
            {"conversation_group": "not-an-id"},
        )

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.exists())

    def test_unavailable_item_does_not_open_a_conversation(self) -> None:
        self.item.status = ItemStatus.BORROWED
        self.item.save(update_fields=["status"])
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.exists())

    def test_disabled_lender_preference_does_not_open_a_conversation(self) -> None:
        profile = self.lender.profile
        profile.allow_pre_request_chat = False
        profile.save(update_fields=["allow_pre_request_chat"])
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.exists())

    def test_owner_cannot_open_a_pre_request_conversation(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ChatThread.objects.exists())

    def test_user_without_item_permission_gets_a_404(self) -> None:
        stranger = self.make_user("stranger")
        self.client.force_login(stranger)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChatThread.objects.exists())

    def test_anonymous_user_is_sent_to_login(self) -> None:
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_returns_a_404(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChatThread.objects.exists())

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(ChatThread.objects.exists())
