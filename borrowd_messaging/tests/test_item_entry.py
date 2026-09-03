from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import Client, override_settings
from django.urls import reverse
from guardian.shortcuts import assign_perm, remove_perm

from borrowd_groups.models import BorrowdGroup
from borrowd_items.exceptions import ItemAlreadyRequested
from borrowd_items.models import (
    ItemAction,
    ItemStatus,
    ListingType,
    Transaction,
    TransactionStatus,
)
from borrowd_messaging.models import ChatThread, Message
from borrowd_messaging.views import ChatThreadPreRequestOpenView
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

        thread = ChatThread.objects.get(
            item=self.item,
            borrower=self.borrower,
            transaction__isnull=True,
        )
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
        self.assertEqual(
            ChatThread.objects.filter(
                item=self.item,
                borrower=self.borrower,
            ).count(),
            1,
        )

    def test_reopens_an_existing_conversation_after_lender_disables_new_chats(
        self,
    ) -> None:
        existing = self.make_thread()
        profile = self.lender.profile
        profile.allow_pre_request_chat = False
        profile.save(update_fields=["allow_pre_request_chat"])
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("chat-thread-detail", args=[existing.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            ChatThread.objects.filter(
                item=self.item,
                borrower=self.borrower,
            ).count(),
            1,
        )

    def test_snapshots_an_explicit_eligible_group(self) -> None:
        self._make_eligible_group("Group A")
        selected = self._make_eligible_group("Group B")
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url,
            {"conversation_group": selected.pk},
        )

        thread = ChatThread.objects.get(
            item=self.item,
            borrower=self.borrower,
            transaction__isnull=True,
        )
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
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
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
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
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
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_rejects_a_numeric_group_that_does_not_exist(self) -> None:
        deleted_group = self.make_group(name="Deleted Group")
        deleted_group_id = deleted_group.pk
        deleted_group.delete()
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url,
            {"conversation_group": deleted_group_id},
        )

        self.assertRedirects(
            response,
            reverse("item-detail", args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["The selected group is not available for this conversation."],
        )

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
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

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
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_owner_cannot_open_a_pre_request_conversation(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_user_without_item_permission_gets_a_404(self) -> None:
        stranger = self.make_user("stranger")
        self.client.force_login(stranger)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_anonymous_user_is_sent_to_login(self) -> None:
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_returns_a_404(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())


class ItemObjectLookupTests(MessagingTestCase):
    def test_item_lookup_is_reused_for_permission_and_request_handling(self) -> None:
        view = ChatThreadPreRequestOpenView()
        view.kwargs = {"item_pk": self.item.pk}

        with self.assertNumQueries(1):
            first_lookup = view.get_object()
            second_lookup = view.get_object()

        self.assertIs(first_lookup, second_lookup)


@override_settings(MESSAGING_ENABLED=True)
class ItemDetailMessagingActionTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.url = reverse("item-detail", args=[self.item.pk])
        self.open_url = reverse(
            "chat-thread-pre-request-open",
            args=[self.item.pk],
        )
        self.client.force_login(self.borrower)

    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_available_item_shows_message_lender_and_request_item(self) -> None:
        response = self.client.get(self.url)

        self.assertContains(response, 'id="message-lender-button"')
        self.assertContains(response, "Message lender")
        self.assertContains(response, f'action="{self.open_url}"')
        self.assertContains(response, "Request item")

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_hides_the_messaging_action(self) -> None:
        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="message-lender-button"')
        self.assertNotContains(response, 'id="item-conversation-link"')
        self.assertContains(response, "Request item")

    def test_owner_does_not_see_a_messaging_action(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="message-lender-button"')
        self.assertNotContains(response, 'id="item-conversation-link"')

    def test_lender_preference_hides_only_message_lender(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")
        profile = self.lender.profile
        profile.allow_pre_request_chat = False
        profile.save(update_fields=["allow_pre_request_chat"])

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="message-lender-button"')
        self.assertNotContains(response, 'id="item-conversation-link"')
        self.assertContains(response, "Request item")
        self.assertContains(
            response,
            f'id="form-{response.context["request_modal_id"]}-conversation-group"',
        )

    def test_unavailable_item_hides_message_lender(self) -> None:
        self.item.status = ItemStatus.BORROWED
        self.item.save(update_fields=["status"])

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="message-lender-button"')
        self.assertNotContains(response, 'id="item-conversation-link"')

    def test_existing_pre_request_thread_is_linked_directly(self) -> None:
        existing = self.make_thread()
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")

        response = self.client.get(self.url)

        conversation_url = reverse("chat-thread-detail", args=[existing.pk])
        self.assertContains(response, 'id="item-conversation-link"')
        self.assertContains(response, f'href="{conversation_url}"')
        self.assertContains(response, "Message lender")
        self.assertNotContains(response, 'id="conversation-group-modal"')
        self.assertNotContains(response, "Choose the group for this request")

    def test_active_transaction_thread_is_linked_directly(self) -> None:
        transaction = self.make_transaction(status=TransactionStatus.REQUESTED)
        thread = ChatThread.objects.get(transaction=transaction)
        self.item.status = ItemStatus.REQUESTED
        self.item.save(update_fields=["status"])

        response = self.client.get(self.url)

        conversation_url = reverse("chat-thread-detail", args=[thread.pk])
        self.assertContains(response, 'id="item-conversation-link"')
        self.assertContains(response, f'href="{conversation_url}"')
        self.assertContains(response, "View conversation")
        self.assertNotContains(response, 'id="message-lender-button"')

    def test_one_eligible_group_does_not_require_a_picker(self) -> None:
        self._make_eligible_group("Tool Library")

        response = self.client.get(self.url)

        self.assertContains(response, 'id="message-lender-button"')
        self.assertNotContains(response, 'id="conversation-group-modal"')
        self.assertNotContains(response, "Choose the group for this request")

    def test_multiple_eligible_groups_are_offered_in_a_picker(self) -> None:
        group_b = self._make_eligible_group("Group B")
        group_a = self._make_eligible_group("Group A")

        response = self.client.get(self.url)

        self.assertContains(response, 'id="conversation-group-modal"')
        self.assertContains(response, "Choose a group")
        self.assertContains(response, f'action="{self.open_url}"')
        self.assertContains(response, 'name="conversation_group"')
        self.assertContains(response, 'form="open-conversation-form"')
        request_form_id = f"form-{response.context['request_modal_id']}"
        self.assertContains(
            response,
            f'id="{request_form_id}-conversation-group"',
        )
        self.assertContains(response, f'form="{request_form_id}"')
        self.assertContains(response, "Choose the group for this request")
        self.assertContains(
            response,
            '<option value="" selected disabled>Choose a group</option>',
            html=True,
        )
        self.assertContains(
            response,
            f'<option value="{group_a.pk}">Group A</option>',
            html=True,
        )
        self.assertContains(
            response,
            f'<option value="{group_b.pk}">Group B</option>',
            html=True,
        )

    def test_unshared_group_is_not_offered_in_the_picker(self) -> None:
        shared_a = self._make_eligible_group("Shared A")
        shared_b = self._make_eligible_group("Shared B")
        unshared = self._make_eligible_group("Not shared")
        self.item.share_with_all_groups = False
        self.item.save(update_fields=["share_with_all_groups"])
        self.item.shared_with_groups.add(shared_a, shared_b)

        response = self.client.get(self.url)

        choice_ids = [
            group.pk for group in response.context["conversation_group_choices"]
        ]
        self.assertEqual(choice_ids, [shared_a.pk, shared_b.pk])
        self.assertNotIn(unshared.pk, choice_ids)

    def test_giveaway_request_modal_uses_the_same_required_group_choice(self) -> None:
        self.item.listing_type = ListingType.GIVEAWAY
        self.item.save(update_fields=["listing_type"])
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")

        response = self.client.get(self.url)

        form_id = f"form-request-giveaway-modal{response.context['modal_suffix']}"
        self.assertContains(response, f'id="{form_id}-conversation-group"')
        self.assertContains(response, f'form="{form_id}"')
        self.assertContains(response, 'value="REQUEST_GIVEAWAY"')


@override_settings(MESSAGING_ENABLED=True)
class ItemListRequestGroupChoiceTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.url = reverse("item-list")
        self.client.force_login(self.borrower)

    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_ambiguous_request_modal_lists_the_batched_group_choices(self) -> None:
        group_b = self._make_eligible_group("Group B")
        group_a = self._make_eligible_group("Group A")

        response = self.client.get(self.url)

        card = next(
            card
            for card in response.context["item_cards"]
            if card["pk"] == self.item.pk
        )
        self.assertEqual(
            card["request_conversation_group_choices"],
            (group_a, group_b),
        )
        form_id = f"form-request-item-modal-search-{self.item.pk}"
        self.assertContains(response, f'id="{form_id}-conversation-group"')
        self.assertContains(response, f'form="{form_id}"')
        self.assertRegex(
            response.content.decode(),
            rf'<select id="{form_id}-conversation-group"[^>]*required>',
        )

    def test_existing_thread_removes_the_group_choice_from_the_modal(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")
        self.make_thread()

        response = self.client.get(self.url)

        card = next(
            card
            for card in response.context["item_cards"]
            if card["pk"] == self.item.pk
        )
        self.assertEqual(card["request_conversation_group_choices"], ())
        self.assertNotContains(response, "Choose the group for this request")


@override_settings(MESSAGING_ENABLED=True)
class PreRequestChatRequestActionTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def test_borrower_can_request_a_lending_listing(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Request item")
        self.assertContains(
            response,
            f'action="{reverse("item-borrow", args=[self.item.pk])}"',
        )
        self.assertContains(response, 'value="REQUEST_ITEM"')

    def test_borrower_can_request_a_giveaway_listing(self) -> None:
        self.item.listing_type = ListingType.GIVEAWAY
        self.item.save(update_fields=["listing_type"])
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Request gift")
        self.assertContains(response, 'value="REQUEST_GIVEAWAY"')

    def test_lender_cannot_request_from_the_chat(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Close conversation")

    def test_linked_thread_no_longer_shows_pre_request_actions(self) -> None:
        transaction = self.make_transaction()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(self.thread.transaction, transaction)
        self.assertNotContains(response, 'id="request-listing-button"')
        self.assertNotContains(response, "Close conversation")

    def test_unavailable_item_hides_the_request_action(self) -> None:
        self.item.status = ItemStatus.BORROWED
        self.item.save(update_fields=["status"])
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Close conversation")

    def test_lost_item_permission_hides_the_request_action(self) -> None:
        remove_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Close conversation")

    def test_changed_item_owner_hides_the_request_action(self) -> None:
        new_owner = self.make_user("new-owner")
        self.item.owner = new_owner
        self.item.updated_by = new_owner
        self.item.save(update_fields=["owner", "updated_by"])
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="request-listing-button"')
        self.assertContains(response, "Close conversation")


@override_settings(MESSAGING_ENABLED=True)
class ItemConversationConversionFlowTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.item_url = reverse("item-detail", args=[self.item.pk])
        self.open_url = reverse(
            "chat-thread-pre-request-open",
            args=[self.item.pk],
        )
        self.borrow_url = reverse("item-borrow", args=[self.item.pk])
        self.client.force_login(self.borrower)

    def _make_eligible_group(self, name: str) -> BorrowdGroup:
        group = self.make_group(name=name)
        group.add_user(self.borrower)
        return group

    def test_lending_request_keeps_the_thread_history_and_context(self) -> None:
        self._make_eligible_group("Group A")
        selected_group = self._make_eligible_group("Group B")
        self.client.post(
            self.open_url,
            {"conversation_group": selected_group.pk},
        )
        thread = ChatThread.objects.get(
            item=self.item,
            borrower=self.borrower,
            transaction__isnull=True,
        )
        message = Message.objects.create(
            thread=thread,
            sender=self.borrower,
            body="Could I collect this on Saturday?",
        )
        chat_url = reverse("chat-thread-detail", args=[thread.pk])

        response = self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=chat_url,
        )

        transaction = Transaction.objects.get(
            item=self.item,
            party2=self.borrower,
        )
        thread.refresh_from_db()
        self.item.refresh_from_db()
        self.assertRedirects(response, chat_url, fetch_redirect_response=False)
        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.conversation_group, selected_group)
        self.assertEqual(thread.conversation_group_source_id, selected_group.pk)
        self.assertEqual(thread.conversation_group_name, "Group B")
        self.assertEqual(thread.messages.get(pk=message.pk).body, message.body)
        self.assertEqual(
            ChatThread.objects.filter(
                item=self.item,
                borrower=self.borrower,
            ).count(),
            1,
        )
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)

        chat_response = self.client.get(chat_url)
        self.assertContains(chat_response, message.body)
        self.assertNotContains(chat_response, 'id="request-listing-button"')
        self.assertNotContains(chat_response, "Close conversation")

        item_response = self.client.get(self.item_url)
        self.assertContains(item_response, "View conversation")
        self.assertContains(item_response, f'href="{chat_url}"')

    def test_giveaway_request_keeps_the_existing_thread(self) -> None:
        self.item.listing_type = ListingType.GIVEAWAY
        self.item.save(update_fields=["listing_type"])
        self.client.post(self.open_url)
        thread = ChatThread.objects.get(
            item=self.item,
            borrower=self.borrower,
            transaction__isnull=True,
        )
        message = Message.objects.create(
            thread=thread,
            sender=self.borrower,
            body="Would this fit in a hatchback?",
        )
        chat_url = reverse("chat-thread-detail", args=[thread.pk])

        response = self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_GIVEAWAY},
            HTTP_REFERER=chat_url,
        )

        transaction = Transaction.objects.get(
            item=self.item,
            party2=self.borrower,
        )
        thread.refresh_from_db()
        self.assertRedirects(response, chat_url, fetch_redirect_response=False)
        self.assertEqual(transaction.status, TransactionStatus.GIVEAWAY_REQUESTED)
        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.listing_type, ListingType.GIVEAWAY)
        self.assertTrue(thread.messages.filter(pk=message.pk).exists())
        self.assertEqual(
            ChatThread.objects.filter(
                item=self.item,
                borrower=self.borrower,
            ).count(),
            1,
        )

    def test_direct_item_request_still_creates_one_transaction_thread(self) -> None:
        eligible_group = self._make_eligible_group("Tool Library")

        response = self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=self.item_url,
        )

        transaction = Transaction.objects.get(
            item=self.item,
            party2=self.borrower,
        )
        thread = ChatThread.objects.get(transaction=transaction)
        self.assertRedirects(response, self.item_url, fetch_redirect_response=False)
        self.assertEqual(thread.transaction, transaction)
        self.assertEqual(thread.conversation_group, eligible_group)
        self.assertEqual(thread.conversation_group_name, "Tool Library")

    def test_direct_item_request_without_groups_stays_unfiled(self) -> None:
        self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=self.item_url,
        )

        transaction = Transaction.objects.get(item=self.item, party2=self.borrower)
        thread = ChatThread.objects.get(transaction=transaction)
        self.assertIsNone(thread.conversation_group)
        self.assertIsNone(thread.conversation_group_source_id)
        self.assertIsNone(thread.conversation_group_name)

    def test_direct_item_request_requires_an_ambiguous_group_choice(self) -> None:
        self._make_eligible_group("Group A")
        self._make_eligible_group("Group B")

        response = self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=self.item_url,
        )

        self.item.refresh_from_db()
        self.assertRedirects(response, self.item_url, fetch_redirect_response=False)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["Choose a group for this conversation."],
        )

    def test_direct_item_request_snapshots_the_selected_group(self) -> None:
        self._make_eligible_group("Group A")
        selected = self._make_eligible_group("Group B")

        response = self.client.post(
            self.borrow_url,
            {
                "action": ItemAction.REQUEST_ITEM,
                "conversation_group": selected.pk,
            },
            HTTP_REFERER=self.item_url,
        )

        transaction = Transaction.objects.get(item=self.item, party2=self.borrower)
        thread = ChatThread.objects.get(transaction=transaction)
        self.assertRedirects(response, self.item_url, fetch_redirect_response=False)
        self.assertEqual(thread.conversation_group, selected)
        self.assertEqual(thread.conversation_group_source_id, selected.pk)
        self.assertEqual(thread.conversation_group_name, "Group B")

    def test_direct_giveaway_request_snapshots_the_selected_group(self) -> None:
        self.item.listing_type = ListingType.GIVEAWAY
        self.item.save(update_fields=["listing_type"])
        self._make_eligible_group("Group A")
        selected = self._make_eligible_group("Group B")

        self.client.post(
            self.borrow_url,
            {
                "action": ItemAction.REQUEST_GIVEAWAY,
                "conversation_group": selected.pk,
            },
            HTTP_REFERER=self.item_url,
        )

        transaction = Transaction.objects.get(item=self.item, party2=self.borrower)
        thread = ChatThread.objects.get(transaction=transaction)
        self.assertEqual(transaction.status, TransactionStatus.GIVEAWAY_REQUESTED)
        self.assertEqual(thread.conversation_group, selected)
        self.assertEqual(thread.listing_type, ListingType.GIVEAWAY)

    def test_direct_request_rejects_an_ineligible_group(self) -> None:
        ineligible = self.make_group(name="Lender only")

        response = self.client.post(
            self.borrow_url,
            {
                "action": ItemAction.REQUEST_ITEM,
                "conversation_group": ineligible.pk,
            },
            HTTP_REFERER=self.item_url,
        )

        self.assertRedirects(response, self.item_url, fetch_redirect_response=False)
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["The selected group is not available for this conversation."],
        )

    def test_direct_request_ignores_the_pre_request_chat_preference(self) -> None:
        profile = self.lender.profile
        profile.allow_pre_request_chat = False
        profile.save(update_fields=["allow_pre_request_chat"])

        self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=self.item_url,
        )

        transaction = Transaction.objects.get(item=self.item, party2=self.borrower)
        self.assertTrue(ChatThread.objects.filter(transaction=transaction).exists())

    def test_failed_direct_request_rolls_back_the_prepared_thread(self) -> None:
        with patch(
            "borrowd_items.models.Item.process_action",
            side_effect=ItemAlreadyRequested,
        ):
            response = self.client.post(
                self.borrow_url,
                {"action": ItemAction.REQUEST_ITEM},
                HTTP_REFERER=self.item_url,
            )

        self.assertRedirects(response, self.item_url, fetch_redirect_response=False)
        self.assertFalse(Transaction.objects.filter(item=self.item).exists())
        self.assertFalse(ChatThread.objects.filter(item=self.item).exists())

    def test_stale_chat_request_does_not_claim_the_pre_request_thread(self) -> None:
        self.client.post(self.open_url)
        losing_thread = ChatThread.objects.get(
            item=self.item,
            borrower=self.borrower,
            transaction__isnull=True,
        )
        winner = self.make_user("winner")
        assign_perm(ItemOLP.VIEW, winner, self.item)
        winner_client = Client()
        winner_client.force_login(winner)
        winner_client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=self.item_url,
        )
        winning_transaction = Transaction.objects.get(
            item=self.item,
            party2=winner,
        )

        response = self.client.post(
            self.borrow_url,
            {"action": ItemAction.REQUEST_ITEM},
            HTTP_REFERER=reverse("chat-thread-detail", args=[losing_thread.pk]),
        )

        losing_thread.refresh_from_db()
        self.assertEqual(Transaction.objects.filter(item=self.item).count(), 1)
        self.assertIsNone(losing_thread.transaction)
        self.assertEqual(winning_transaction.chat_thread.borrower, winner)
        self.assertEqual(
            [str(message) for message in get_messages(response.wsgi_request)],
            ["Sorry! Another user requested this item just before you."],
        )
