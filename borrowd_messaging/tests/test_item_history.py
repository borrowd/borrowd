from django.test import override_settings
from django.urls import reverse
from guardian.shortcuts import assign_perm

from borrowd_messaging.models import Message
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

        response = self.client.get(self.url)

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

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_hides_the_conversation_section(self) -> None:
        self.make_thread()
        self.client.force_login(self.lender)

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="item-conversations"')
