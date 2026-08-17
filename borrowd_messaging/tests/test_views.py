from django.test import override_settings
from django.urls import reverse

from borrowd_messaging.models import (
    MESSAGE_BODY_MAX_LENGTH,
    ArchiveReason,
    Message,
)
from borrowd_messaging.services import MessagingService

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadDetailViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def test_borrower_sees_the_thread(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Free Saturday?"
        )
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Free Saturday?")

    def test_bubble_carries_sender_avatar_name_and_timestamp(self) -> None:
        self.lender.first_name = "Lena"
        self.lender.last_name = "Derr"
        self.lender.save()
        message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Yes, come by at ten."
        )
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, f'id="message-{message.pk}"')
        self.assertContains(response, "Lena Derr")
        self.assertContains(response, message.created_at.strftime("%b %-d"))
        self.assertContains(response, "ui-avatars.com")
        # The borrower is reading the lender's message, so it sits on the left.
        self.assertContains(response, "chat-start")

    def test_own_messages_are_aligned_to_the_viewer(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Free Saturday?"
        )
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "chat-end")

    def test_system_notice_renders_without_a_bubble_or_avatar(self) -> None:
        MessagingService.post_system_message(self.thread, "This item was returned.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "This item was returned.")
        self.assertNotContains(response, "chat-bubble")
        self.assertNotContains(response, "ui-avatars.com")

    def test_lender_sees_the_thread(self) -> None:
        self.client.force_login(self.lender)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_non_participant_gets_a_404(self) -> None:
        self.client.force_login(self.make_user("stranger"))

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_user_is_sent_to_login(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    @override_settings(MESSAGING_ENABLED=False)
    def test_thread_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 404)


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadSendViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-send", args=[self.thread.pk])

    def test_sending_stores_the_message_and_returns_its_bubble(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Free Saturday?"})

        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(thread=self.thread)
        self.assertEqual(message.body, "Free Saturday?")
        self.assertEqual(message.sender, self.borrower)
        self.assertContains(response, f'id="message-{message.pk}"')
        # The sender is looking at their own message, so it sits on the right.
        self.assertContains(response, "chat-end")

    def test_lender_can_reply(self) -> None:
        self.client.force_login(self.lender)

        self.assertEqual(self.client.post(self.url, {"body": "Yep"}).status_code, 200)
        self.assertEqual(Message.objects.get(thread=self.thread).sender, self.lender)

    def test_empty_body_is_rejected(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_overlong_body_is_rejected(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url, {"body": "x" * (MESSAGE_BODY_MAX_LENGTH + 1)}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_archived_thread_refuses_the_message(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Still there?"})

        self.assertEqual(response.status_code, 409)
        self.assertFalse(
            Message.objects.filter(thread=self.thread, is_system=False).exists()
        )

    def test_non_participant_gets_a_404(self) -> None:
        self.client.force_login(self.make_user("stranger"))

        response = self.client.post(self.url, {"body": "Hello"})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    @override_settings(MESSAGING_ENABLED=False)
    def test_sending_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Hello"})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 405)
