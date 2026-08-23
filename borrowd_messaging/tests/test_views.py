from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from borrowd_items.models import Transaction, TransactionStatus
from borrowd_messaging.models import (
    MESSAGE_BODY_MAX_LENGTH,
    ArchiveReason,
    Message,
)
from borrowd_messaging.services import MessagingService
from borrowd_messaging.views import (
    ChatThreadCloseView,
    ChatThreadDetailView,
    ChatThreadPollView,
    ChatThreadSendView,
)
from borrowd_users.models import BorrowdUser

from .base import MessagingTestCase


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadDetailViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def test_borrower_sees_their_message_on_the_right(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Free Saturday?"
        )
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "Free Saturday?")
        self.assertContains(response, "chat-end")

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

    def test_bubble_preserves_line_breaks(self) -> None:
        Message.objects.create(
            thread=self.thread,
            sender=self.lender,
            body="First line\nSecond line",
        )
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "First line<br>Second line")

    def test_thread_participants_and_profiles_are_loaded_together(self) -> None:
        view = ChatThreadDetailView()
        view.kwargs = {"pk": self.thread.pk}

        with self.assertNumQueries(1):
            chat_thread = view.get_object()
            lender_name = chat_thread.lender.profile.full_name()
            borrower_name = chat_thread.borrower.profile.full_name()

        self.assertEqual(lender_name, self.lender.profile.full_name())
        self.assertEqual(borrower_name, self.borrower.profile.full_name())

    def test_system_notice_renders_without_a_bubble_or_avatar(self) -> None:
        MessagingService.post_system_message(self.thread, "This item was returned.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "This item was returned.")
        self.assertNotContains(response, "chat-bubble")
        self.assertNotContains(response, "ui-avatars.com")

    def test_header_names_the_item(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, self.item.name)
        self.assertNotContains(response, "no longer available")

    def test_header_handles_an_item_that_is_no_longer_available(self) -> None:
        self.thread.item = None
        self.thread.save(update_fields=["item"])
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "This item is no longer available.")

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


class ChatThreadObjectLookupTests(MessagingTestCase):
    def test_thread_lookup_is_cached_for_permission_and_request_handling(self) -> None:
        thread = self.make_thread()
        view_classes = (
            ChatThreadDetailView,
            ChatThreadSendView,
            ChatThreadPollView,
            ChatThreadCloseView,
        )

        for view_class in view_classes:
            with self.subTest(view=view_class.__name__):
                view = view_class()
                view.kwargs = {"pk": thread.pk}

                with self.assertNumQueries(1):
                    first_lookup = view.get_object()
                    second_lookup = view.get_object()

                self.assertIs(first_lookup, second_lookup)


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadSendViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-send", args=[self.thread.pk])

    def test_sending_stores_the_message_and_returns_its_bubble(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Free Saturday?", "after": 0})

        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(thread=self.thread)
        self.assertEqual(message.body, "Free Saturday?")
        self.assertEqual(message.sender, self.borrower)
        self.assertContains(response, f'id="message-{message.pk}"')
        # The sender is looking at their own message, so it sits on the right.
        self.assertContains(response, "chat-end")

    def test_sending_returns_messages_received_after_the_browser_cursor(self) -> None:
        seen = Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Is Saturday free?"
        )
        unseen = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Saturday works."
        )
        self.client.force_login(self.borrower)

        response = self.client.post(
            self.url, {"body": "Great, thank you.", "after": seen.pk}
        )

        sent = Message.objects.get(
            thread=self.thread, sender=self.borrower, body="Great, thank you."
        )
        self.assertNotContains(response, f'id="message-{seen.pk}"')
        self.assertContains(response, f'id="message-{unseen.pk}"')
        self.assertContains(response, f'id="message-{sent.pk}"')
        self.assertLess(
            response.content.index(f'id="message-{unseen.pk}"'.encode()),
            response.content.index(f'id="message-{sent.pk}"'.encode()),
        )

    def test_sending_rejects_invalid_cursors(self) -> None:
        other_thread = self.make_thread(
            item=self.make_item(owner=self.lender, name="Ladder")
        )
        foreign_message = Message.objects.create(
            thread=other_thread, sender=self.borrower, body="Wrong conversation"
        )
        self.client.force_login(self.borrower)

        cases = {
            "missing": {"body": "Do not store this."},
            "nonnumeric": {"body": "Do not store this.", "after": "abc"},
            "negative": {"body": "Do not store this.", "after": -1},
            "another conversation": {
                "body": "Do not store this.",
                "after": foreign_message.pk,
            },
        }
        for label, data in cases.items():
            with self.subTest(cursor=label):
                response = self.client.post(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_lender_can_reply(self) -> None:
        self.client.force_login(self.lender)

        self.assertEqual(
            self.client.post(self.url, {"body": "Yep", "after": 0}).status_code,
            200,
        )
        self.assertEqual(Message.objects.get(thread=self.thread).sender, self.lender)

    def test_invalid_body_is_rejected(self) -> None:
        self.client.force_login(self.borrower)

        cases = {
            "blank": ("   ", "Message body cannot be empty."),
            "overlong": (
                "x" * (MESSAGE_BODY_MAX_LENGTH + 1),
                f"Message body cannot exceed {MESSAGE_BODY_MAX_LENGTH} characters.",
            ),
        }
        for label, (body, error) in cases.items():
            with self.subTest(body=label):
                response = self.client.post(self.url, {"body": body, "after": 0})

                self.assertEqual(response.status_code, 400)
                self.assertContains(response, error, status_code=400)
                self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_archived_thread_refuses_the_message(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Still there?", "after": 0})

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            "This conversation is archived.",
            status_code=409,
        )
        self.assertFalse(
            Message.objects.filter(thread=self.thread, is_system=False).exists()
        )

    def test_non_participant_gets_a_404(self) -> None:
        self.client.force_login(self.make_user("stranger"))

        response = self.client.post(self.url, {"body": "Hello", "after": 0})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    @override_settings(MESSAGING_ENABLED=False)
    def test_sending_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, {"body": "Hello", "after": 0})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(thread=self.thread).exists())

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 405)


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadPollViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-poll", args=[self.thread.pk])

    def send(self, sender: BorrowdUser, body: str) -> Message:
        return Message.objects.create(thread=self.thread, sender=sender, body=body)

    def dispute(self) -> Transaction:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.DISPUTED
        transaction.save()
        self.thread.refresh_from_db()
        return transaction

    def test_nothing_new_returns_204(self) -> None:
        latest = self.send(self.borrower, "Free Saturday?")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": latest.pk})

        self.assertEqual(response.status_code, 204)
        self.assertFalse(response.content)

    def test_returns_only_messages_after_the_cursor(self) -> None:
        seen = self.send(self.borrower, "Free Saturday?")
        fresh = self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": seen.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saturday works.")
        self.assertNotContains(response, "Free Saturday?")
        self.assertContains(response, f'id="message-{fresh.pk}"')

    def test_zero_cursor_returns_the_whole_thread(self) -> None:
        self.send(self.borrower, "Free Saturday?")
        self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": 0})

        self.assertContains(response, "Free Saturday?")
        self.assertContains(response, "Saturday works.")

    def test_messages_come_back_in_order(self) -> None:
        self.send(self.borrower, "First")
        self.send(self.lender, "Second")
        self.client.force_login(self.borrower)

        body = self.client.get(self.url, {"after": 0}).content.decode()

        self.assertLess(body.index("First"), body.index("Second"))

    def test_bubbles_are_sided_for_the_reader(self) -> None:
        self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        # The borrower is reading the lender's message, so it sits on the left.
        self.assertContains(self.client.get(self.url, {"after": 0}), "chat-start")

    def test_poll_adds_the_dispute_badge(self) -> None:
        seen = self.send(self.borrower, "Free Saturday?")
        self.dispute()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": seen.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Disputed")
        self.assertContains(response, 'id="chat-dispute-indicator"')
        self.assertContains(response, 'hx-swap-oob="true"')

    def test_final_poll_removes_the_dispute_badge(self) -> None:
        transaction = self.dispute()
        dispute_notice = Message.objects.filter(thread=self.thread).latest("pk")
        transaction.status = TransactionStatus.RETURNED
        transaction.save()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": dispute_notice.pk})

        self.assertEqual(response.status_code, 286)
        self.assertContains(
            response,
            '<div id="chat-dispute-indicator" hx-swap-oob="true"></div>',
            html=True,
            status_code=286,
        )
        self.assertNotContains(response, "Disputed", status_code=286)

    def test_archiving_delivers_notice_replaces_composer_and_stops_poller(
        self,
    ) -> None:
        seen = self.send(self.borrower, "Free Saturday?")
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": seen.pk})

        # 286 swaps the closing notice in, then cancels the poll.
        self.assertEqual(response.status_code, 286)
        self.assertContains(response, "This conversation was closed.", status_code=286)
        self.assertContains(response, 'id="chat-composer"', status_code=286)
        self.assertContains(response, 'hx-swap-oob="true"', status_code=286)

    def test_settled_archived_thread_stops_the_poller_with_nothing_to_add(self) -> None:
        self.send(self.borrower, "Free Saturday?")
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        latest = Message.objects.filter(thread=self.thread).order_by("id").last()
        assert latest is not None
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": latest.pk})

        self.assertEqual(response.status_code, 286)
        self.assertNotContains(response, "chat-bubble", status_code=286)

    def test_invalid_cursors_are_rejected(self) -> None:
        other_thread = self.make_thread(
            item=self.make_item(owner=self.lender, name="Ladder")
        )
        foreign_message = Message.objects.create(
            thread=other_thread,
            sender=self.borrower,
            body="Wrong conversation",
        )
        self.client.force_login(self.borrower)

        cases: dict[str, dict[str, str | int]] = {
            "missing": {},
            "nonnumeric": {"after": "abc"},
            "negative": {"after": -1},
            "another conversation": {"after": foreign_message.pk},
        }
        for label, data in cases.items():
            with self.subTest(cursor=label):
                response = self.client.get(self.url, data)

                self.assertEqual(response.status_code, 400)
                self.assertContains(
                    response,
                    "`after` must be a message id from this conversation.",
                    status_code=400,
                )

    def test_non_participant_gets_a_404(self) -> None:
        self.send(self.borrower, "Free Saturday?")
        self.client.force_login(self.make_user("stranger"))

        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(MESSAGING_ENABLED=False)
    def test_polling_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 404)


@override_settings(MESSAGING_ENABLED=True)
class ArchivedThreadReadOnlyTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()

    def test_archived_page_is_read_only_and_does_not_poll(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        response = self.client.get(reverse("chat-thread-detail", args=[self.thread.pk]))

        self.assertContains(response, "This conversation is archived.")
        self.assertNotContains(response, 'name="body"')
        # Nothing to replace on a fresh page, so no out-of-band marker.
        self.assertNotContains(response, "hx-swap-oob")
        self.assertNotContains(
            response, reverse("chat-thread-poll", args=[self.thread.pk])
        )
        self.assertNotContains(
            response, reverse("chat-thread-close", args=[self.thread.pk])
        )

    def test_active_poll_leaves_the_composer_alone(self) -> None:
        seen = Message.objects.create(
            thread=self.thread, sender=self.borrower, body="Free Saturday?"
        )
        Message.objects.create(
            thread=self.thread, sender=self.lender, body="Saturday works."
        )
        self.client.force_login(self.borrower)

        response = self.client.get(
            reverse("chat-thread-poll", args=[self.thread.pk]), {"after": seen.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="chat-composer"')


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadCloseViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-close", args=[self.thread.pk])

    def test_borrower_closes_the_conversation(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.post(self.url)

        self.assertRedirects(
            response, reverse("chat-thread-detail", args=[self.thread.pk])
        )
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_archived)
        self.assertEqual(self.thread.archive_reason, ArchiveReason.CLOSED)
        self.assertEqual(self.thread.updated_by, self.borrower)

    def test_lender_can_close_it_too(self) -> None:
        self.client.force_login(self.lender)

        self.client.post(self.url)

        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_archived)

    def test_authentication_failure_is_not_treated_as_a_transaction_race(
        self,
    ) -> None:
        self.client.force_login(self.borrower)

        with patch(
            "borrowd_messaging.views.get_authenticated_user",
            side_effect=PermissionDenied,
        ):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

    def test_closing_posts_the_notice(self) -> None:
        self.client.force_login(self.borrower)

        self.client.post(self.url)

        notice = Message.objects.get(thread=self.thread, is_system=True)
        self.assertEqual(notice.body, "This conversation was closed.")

    def test_closing_twice_posts_one_notice(self) -> None:
        self.client.force_login(self.borrower)

        self.client.post(self.url)
        self.client.post(self.url)

        self.assertEqual(
            Message.objects.filter(thread=self.thread, is_system=True).count(), 1
        )

    def test_a_thread_with_a_transaction_stays_open(self) -> None:
        self.thread.transaction = self.make_transaction()
        self.thread.save()
        self.client.force_login(self.borrower)

        self.client.post(self.url)

        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

    def test_non_participant_gets_a_404(self) -> None:
        self.client.force_login(self.make_user("stranger"))

        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

    @override_settings(MESSAGING_ENABLED=False)
    def test_closing_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 405)


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadCloseButtonTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def test_thread_with_a_transaction_has_no_close_button(self) -> None:
        self.thread.transaction = self.make_transaction()
        self.thread.save()
        self.client.force_login(self.borrower)

        self.assertNotContains(
            self.client.get(self.url),
            reverse("chat-thread-close", args=[self.thread.pk]),
        )


@override_settings(MESSAGING_ENABLED=True)
class DisputeBadgeTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def dispute(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.DISPUTED
        transaction.save()
        self.thread.refresh_from_db()

    def test_disputed_thread_shows_the_badge(self) -> None:
        self.dispute()
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "Disputed")

    def test_disputed_thread_stays_writable(self) -> None:
        self.dispute()
        self.client.force_login(self.borrower)

        response = self.client.post(
            reverse("chat-thread-send", args=[self.thread.pk]),
            {"body": "Let us sort this out.", "after": 0},
        )

        self.assertEqual(response.status_code, 200)

    def test_prerequest_thread_has_no_badge(self) -> None:
        self.client.force_login(self.borrower)

        self.assertNotContains(self.client.get(self.url), "Disputed")

    def test_ordinary_transaction_has_no_badge(self) -> None:
        self.make_transaction()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        self.assertNotContains(self.client.get(self.url), "Disputed")


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadListViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")

    def test_lists_the_threads_you_are_in(self) -> None:
        thread = self.make_thread()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("chat-thread-detail", args=[thread.pk]))

    def test_leaves_out_other_peoples_threads(self) -> None:
        stranger = self.make_user("stranger")
        theirs = self.make_thread(borrower=stranger)
        self.client.force_login(self.borrower)

        self.assertNotContains(
            self.client.get(self.url),
            reverse("chat-thread-detail", args=[theirs.pk]),
        )

    def test_lender_sees_their_side_too(self) -> None:
        thread = self.make_thread()
        self.client.force_login(self.lender)

        self.assertContains(
            self.client.get(self.url),
            reverse("chat-thread-detail", args=[thread.pk]),
        )

    def test_lists_a_thread_whose_item_is_no_longer_available(self) -> None:
        thread = self.make_thread()
        thread.item = None
        thread.save(update_fields=["item"])
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "Item no longer available")
        self.assertContains(response, reverse("chat-thread-detail", args=[thread.pk]))

    def test_labels_an_archived_thread(self) -> None:
        thread = self.make_thread()
        MessagingService.archive_thread(thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "Archived")

    def test_thread_with_newest_message_comes_first(self) -> None:
        quiet = self.make_thread(item=self.make_item(name="Ladder"))
        chatty = self.make_thread(item=self.make_item(name="Projector"))
        Message.objects.create(thread=quiet, sender=self.borrower, body="One")
        Message.objects.create(thread=chatty, sender=self.borrower, body="Two")
        self.client.force_login(self.borrower)

        body = self.client.get(self.url).content.decode()

        self.assertLess(
            body.index(reverse("chat-thread-detail", args=[chatty.pk])),
            body.index(reverse("chat-thread-detail", args=[quiet.pk])),
        )

    def test_new_empty_thread_comes_before_an_older_message_thread(self) -> None:
        older = self.make_thread(item=self.make_item(name="Ladder"))
        old_message = Message.objects.create(
            thread=older, sender=self.borrower, body="One"
        )
        Message.objects.filter(pk=old_message.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        newer = self.make_thread(item=self.make_item(name="Projector"))
        self.client.force_login(self.borrower)

        body = self.client.get(self.url).content.decode()

        self.assertLess(
            body.index(reverse("chat-thread-detail", args=[newer.pk])),
            body.index(reverse("chat-thread-detail", args=[older.pk])),
        )

    def test_empty_state(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "no conversations yet")

    def test_anonymous_user_is_sent_to_login(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 302)

    @override_settings(MESSAGING_ENABLED=False)
    def test_list_is_hidden_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_sidebar_links_to_messages(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), reverse("chat-thread-list"))

    @override_settings(MESSAGING_ENABLED=False)
    def test_sidebar_hides_messages_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertNotContains(
            self.client.get(reverse("item-list")), reverse("chat-thread-list")
        )
