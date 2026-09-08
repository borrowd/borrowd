from datetime import timedelta
from html.parser import HTMLParser
from io import BytesIO
from tempfile import mkdtemp
from typing import Any, Protocol
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from guardian.shortcuts import assign_perm, remove_perm
from PIL import Image

from borrowd_items.models import ItemPhoto, Transaction, TransactionStatus
from borrowd_messaging.models import (
    MESSAGE_BODY_MAX_LENGTH,
    ArchiveReason,
    ChatThread,
    Message,
)
from borrowd_messaging.read_state import mark_thread_read
from borrowd_messaging.services import MessagingService
from borrowd_messaging.views import (
    ChatThreadDetailView,
    ChatThreadPollView,
    ChatThreadPreRequestCloseView,
    ChatThreadSendView,
)
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .base import MessagingTestCase


class _ElementByIdParser(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__()
        self.element_id = element_id
        self.attributes: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id") == self.element_id:
            self.attributes = attributes


class _ResponseWithContent(Protocol):
    content: bytes


def _element_attributes(
    response: _ResponseWithContent, element_id: str
) -> dict[str, str | None]:
    parser = _ElementByIdParser(element_id)
    parser.feed(response.content.decode())
    if parser.attributes is None:
        raise AssertionError(f"Response does not contain #{element_id}.")
    return parser.attributes


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

    def test_bubble_carries_message_id_sender_name_and_timestamp(self) -> None:
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

    def test_system_notice_is_rendered(self) -> None:
        notice = MessagingService.post_system_message(
            self.thread, "This item was returned."
        )
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, f'id="message-{notice.pk}"')
        self.assertContains(response, "This item was returned.")

    def test_header_names_the_item(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, self.item.name)

    def test_header_handles_a_hard_deleted_item(self) -> None:
        item_name = self.item.name
        self.item.delete()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertIsNone(self.thread.item_id)
        self.assertContains(response, "Item unavailable")
        self.assertNotContains(response, item_name)

    def test_header_keeps_a_soft_deleted_item_name(self) -> None:
        self.item.soft_delete(deleted_by=self.lender)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.context["item_name"], self.item.name)
        self.assertTrue(response.context["item_removed"])

    def test_header_says_so_when_the_item_row_is_gone(self) -> None:
        self.item.delete()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertIsNone(response.context["item_name"])
        self.assertFalse(response.context["item_removed"])

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


class ChatThreadObjectLookupTests(MessagingTestCase):
    def test_thread_lookup_is_cached_for_permission_and_request_handling(self) -> None:
        thread = self.make_thread()
        view_classes = (
            ChatThreadDetailView,
            ChatThreadSendView,
            ChatThreadPollView,
            ChatThreadPreRequestCloseView,
        )

        for view_class in view_classes:
            with self.subTest(view=view_class.__name__):
                view = view_class()
                view.kwargs = {"pk": thread.pk}

                with self.assertNumQueries(1):
                    first_lookup = view.get_object()
                    second_lookup = view.get_object()

                self.assertIs(first_lookup, second_lookup)


@override_settings(MESSAGING_ENABLED=False)
class MessagingViewFeatureFlagTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.client.force_login(self.borrower)

    def test_all_messaging_views_are_hidden(self) -> None:
        responses = {
            "list": self.client.get(reverse("chat-thread-list")),
            "detail": self.client.get(
                reverse("chat-thread-detail", args=[self.thread.pk])
            ),
            "send": self.client.post(
                reverse("chat-thread-send", args=[self.thread.pk]),
                {"body": "Do not store this.", "after": 0},
            ),
            "poll": self.client.get(
                reverse("chat-thread-poll", args=[self.thread.pk]), {"after": 0}
            ),
            "close": self.client.post(
                reverse("chat-thread-pre-request-close", args=[self.thread.pk])
            ),
        }

        for view_name, response in responses.items():
            with self.subTest(view=view_name):
                self.assertEqual(response.status_code, 404)

        self.assertFalse(Message.objects.filter(thread=self.thread).exists())
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)


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

    def test_get_is_not_allowed(self) -> None:
        self.client.force_login(self.borrower)

        self.assertEqual(self.client.get(self.url).status_code, 405)


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadActivePageTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def test_active_prerequest_page_has_composer_poller_and_close_action(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, 'name="body"')
        self.assertContains(
            response, reverse("chat-thread-poll", args=[self.thread.pk])
        )
        self.assertContains(response, 'hx-trigger="every 4s"')
        self.assertContains(
            response,
            reverse("chat-thread-pre-request-close", args=[self.thread.pk]),
        )
        self.assertContains(
            response, "onclick=\"showModal('close-conversation-modal')\""
        )
        self.assertContains(response, 'id="close-conversation-modal"')


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

    def test_returns_only_messages_after_the_cursor(self) -> None:
        seen = self.send(self.borrower, "Free Saturday?")
        fresh = self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": seen.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saturday works.")
        self.assertNotContains(response, "Free Saturday?")
        self.assertContains(response, f'id="message-{fresh.pk}"')
        self.assertNotContains(response, 'id="chat-composer"')

    def test_prerequest_poll_does_not_query_transaction_state(self) -> None:
        self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, {"after": 0})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(
                "borrowd_items_transaction" in query["sql"]
                for query in queries.captured_queries
            )
        )

    def test_zero_cursor_returns_the_whole_thread_in_order(self) -> None:
        self.send(self.borrower, "Free Saturday?")
        self.send(self.lender, "Saturday works.")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": 0})
        body = response.content.decode()

        self.assertContains(response, "Free Saturday?")
        self.assertContains(response, "Saturday works.")
        self.assertLess(body.index("Free Saturday?"), body.index("Saturday works."))

    def test_poll_refreshes_the_status_when_a_dispute_is_raised(self) -> None:
        seen = self.send(self.borrower, "Free Saturday?")
        self.dispute()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": seen.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Disputed")
        self.assertEqual(
            _element_attributes(response, "chat-conversation-status").get(
                "hx-swap-oob"
            ),
            "true",
        )

    def test_final_poll_replaces_the_status_with_the_archive_reason(self) -> None:
        transaction = self.dispute()
        dispute_notice = Message.objects.filter(thread=self.thread).latest("pk")
        transaction.status = TransactionStatus.RETURNED
        transaction.save()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": dispute_notice.pk})

        self.assertEqual(response.status_code, 286)
        self.assertEqual(
            _element_attributes(response, "chat-conversation-status").get(
                "hx-swap-oob"
            ),
            "true",
        )
        self.assertNotContains(response, "Disputed", status_code=286)
        self.assertContains(response, "Returned", status_code=286)

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
        self.assertEqual(
            _element_attributes(response, "chat-composer").get("hx-swap-oob"),
            "true",
        )

    def test_settled_archived_thread_stops_the_poller_with_nothing_to_add(self) -> None:
        self.send(self.borrower, "Free Saturday?")
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        latest = Message.objects.filter(thread=self.thread).order_by("id").last()
        assert latest is not None
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"after": latest.pk})

        self.assertEqual(response.status_code, 286)
        self.assertNotContains(response, 'id="message-', status_code=286)

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
        self.assertNotContains(
            response, reverse("chat-thread-poll", args=[self.thread.pk])
        )
        self.assertNotContains(
            response, reverse("chat-thread-pre-request-close", args=[self.thread.pk])
        )


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadPreRequestCloseViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-pre-request-close", args=[self.thread.pk])

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

    def test_closing_twice_reports_that_the_conversation_is_already_closed(
        self,
    ) -> None:
        self.client.force_login(self.borrower)

        self.client.post(self.url)
        response = self.client.post(self.url, follow=True)

        self.assertContains(
            response,
            "This conversation is already closed.",
        )

    def test_a_thread_with_a_transaction_reports_that_it_stays_open(self) -> None:
        self.thread.transaction = self.make_transaction()
        self.thread.save()
        self.client.force_login(self.borrower)

        response = self.client.post(self.url, follow=True)

        self.assertContains(
            response,
            "This conversation belongs to a request now, so it stays open.",
        )
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

    def test_non_participant_gets_a_404(self) -> None:
        self.client.force_login(self.make_user("stranger"))

        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_archived)

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
            reverse("chat-thread-pre-request-close", args=[self.thread.pk]),
        )


@override_settings(MESSAGING_ENABLED=True)
class ConversationStatusTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])

    def dispute(self) -> None:
        transaction = self.make_transaction()
        transaction.status = TransactionStatus.DISPUTED
        transaction.save()
        self.thread.refresh_from_db()

    def test_disputed_thread_shows_the_disputed_status(self) -> None:
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

    def test_ordinary_transaction_reads_as_active(self) -> None:
        self.make_transaction()
        self.thread.refresh_from_db()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, "Active")
        self.assertNotContains(response, "Disputed")

    def test_thread_without_a_request_reads_as_pre_request(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "Pre-request")

    def test_archived_thread_shows_its_archive_reason(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "Closed")


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadListViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("chat-thread-list")

    def cards(self, query: str = "") -> list[Any]:
        """Fetch the hub and return the cards on the selected tab."""
        return list(self.client.get(f"{self.url}{query}").context["cards"])

    def thread_ids(self, query: str = "") -> list[int]:
        return [card.conversation.thread_id for card in self.cards(query)]

    def make_archived_threads(self, count: int) -> None:
        """Archived threads escape the one-active-pre-request-thread constraint."""
        ChatThread.objects.bulk_create(
            ChatThread(
                item=self.item,
                lender=self.lender,
                borrower=self.borrower,
                created_by=self.borrower,
                updated_by=self.borrower,
                archived_at=timezone.now(),
                archive_reason=ArchiveReason.CLOSED,
            )
            for _ in range(count)
        )

    def make_active_threads(self, count: int) -> None:
        """One active pre-request thread per Item, so each needs its own Item."""
        for index in range(count):
            self.make_thread(item=self.make_item(name=f"Item {index}"))

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

    def test_lists_a_thread_for_a_hard_deleted_item(self) -> None:
        thread = self.make_thread()
        item_name = self.item.name
        self.item.delete()
        thread.refresh_from_db()
        self.client.force_login(self.borrower)

        # Removing the Item archives its conversation, so it moves tabs.
        response = self.client.get(self.url, {"section": "archived"})

        self.assertIsNone(thread.item_id)
        self.assertContains(response, "Item unavailable")
        self.assertNotContains(response, item_name)
        self.assertContains(response, reverse("chat-thread-detail", args=[thread.pk]))

    def test_a_soft_deleted_item_keeps_its_name_on_the_card(self) -> None:
        thread = self.make_thread()
        item_name = self.item.name
        self.item.soft_delete(deleted_by=self.lender)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"section": "archived"})

        # Items are soft-deleted, so the row is still there to read.
        card = response.context["cards"][0]
        self.assertEqual((card.item_name, card.item_removed), (item_name, True))
        self.assertContains(response, item_name)
        self.assertContains(response, reverse("chat-thread-detail", args=[thread.pk]))

    def test_labels_an_archived_thread_with_its_reason(self) -> None:
        thread = self.make_thread()
        MessagingService.archive_thread(thread, ArchiveReason.CLOSED)
        self.client.force_login(self.borrower)

        self.assertContains(
            self.client.get(self.url, {"section": "archived"}), "Closed"
        )

    def test_thread_with_newest_message_comes_first(self) -> None:
        chatty = self.make_thread(item=self.make_item(name="Projector"))
        quiet = self.make_thread(item=self.make_item(name="Ladder"))
        Message.objects.create(thread=chatty, sender=self.borrower, body="Two")
        self.client.force_login(self.borrower)

        self.assertEqual(self.thread_ids(), [chatty.pk, quiet.pk])

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

        self.assertEqual(self.thread_ids(), [newer.pk, older.pk])

    def test_empty_state(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), "no conversations yet")

    def test_each_tab_shows_only_its_own_conversations(self) -> None:
        active = self.make_thread()
        self.make_archived_threads(1)
        archived = ChatThread.objects.get(archived_at__isnull=False)
        self.client.force_login(self.borrower)

        self.assertEqual(self.thread_ids(), [active.pk])
        self.assertEqual(self.thread_ids("?section=archived"), [archived.pk])

    def test_active_is_the_tab_an_unknown_section_falls_back_to(self) -> None:
        active = self.make_thread()
        self.make_archived_threads(1)
        self.client.force_login(self.borrower)

        for query in ("", "?section=", "?section=nonsense"):
            self.assertEqual(self.thread_ids(query), [active.pk])

    def test_an_empty_tab_says_so_while_the_other_tab_has_conversations(self) -> None:
        self.make_thread()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"section": "archived"})

        self.assertContains(response, "No archived conversations.")
        self.assertNotContains(response, "no conversations yet")

    def test_a_tab_holds_twenty_five_conversations_per_page(self) -> None:
        self.make_archived_threads(26)
        oldest = ChatThread.objects.filter(archived_at__isnull=False).earliest("pk")
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"section": "archived"})
        page = response.context["page_obj"]

        self.assertEqual(len(self.thread_ids("?section=archived")), 25)
        self.assertEqual((page.number, page.paginator.num_pages), (1, 2))
        self.assertEqual(self.thread_ids("?section=archived&page=2"), [oldest.pk])

    def test_page_links_stay_on_the_selected_tab(self) -> None:
        self.make_archived_threads(26)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"section": "archived", "page": "2"})

        self.assertContains(response, "?page=1&section=archived")

    def test_switching_tabs_starts_again_at_the_first_page(self) -> None:
        self.make_archived_threads(26)
        self.make_active_threads(26)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url, {"section": "archived", "page": "2"})

        self.assertEqual(response.context["page_obj"].number, 2)
        # The tab link carries no page, so the other tab opens at its first page.
        self.assertContains(response, 'href="?section=active"')
        self.assertEqual(
            self.client.get(self.url, {"section": "active"}).context["page_obj"].number,
            1,
        )

    def test_a_conversation_with_incoming_messages_is_marked_unread(self) -> None:
        thread = self.make_thread()
        message = Message.objects.create(
            thread=thread, sender=self.lender, body="Hello"
        )
        self.client.force_login(self.borrower)

        self.assertTrue(self.cards()[0].conversation.has_unread_messages)

        mark_thread_read(thread, self.borrower, through_message_id=message.pk)

        self.assertFalse(self.cards()[0].conversation.has_unread_messages)

    def test_page_cost_does_not_grow_with_the_number_of_conversations(self) -> None:
        self.make_active_threads(1)
        self.make_archived_threads(1)
        self.client.force_login(self.borrower)
        with CaptureQueriesContext(connection) as one_conversation:
            self.client.get(self.url)

        self.make_active_threads(24)
        self.make_archived_threads(24)
        with CaptureQueriesContext(connection) as a_full_page:
            self.client.get(self.url)

        self.assertEqual(len(a_full_page), len(one_conversation))

    def test_anonymous_user_is_sent_to_login(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_sidebar_links_to_messages(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), reverse("chat-thread-list"))

    @override_settings(MESSAGING_ENABLED=False)
    def test_sidebar_hides_messages_while_the_feature_flag_is_off(self) -> None:
        self.client.force_login(self.borrower)

        self.assertNotContains(
            self.client.get(reverse("item-list")), reverse("chat-thread-list")
        )


@override_settings(MESSAGING_ENABLED=True, MEDIA_ROOT=mkdtemp())
class ConversationItemPreviewTests(MessagingTestCase):
    """The Item card pinned above a conversation."""

    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-detail", args=[self.thread.pk])
        assign_perm(ItemOLP.VIEW, self.borrower, self.item)

    def add_photo(self) -> ItemPhoto:
        image = Image.new("RGB", (40, 40), color="red")
        content = BytesIO()
        image.save(content, format="JPEG")
        return ItemPhoto.objects.create(
            item=self.item,
            image=SimpleUploadedFile(
                name="photo.jpg", content=content.getvalue(), content_type="image/jpeg"
            ),
            created_by=self.lender,
            updated_by=self.lender,
        )

    def test_preview_names_the_item_and_links_to_its_page(self) -> None:
        photo = self.add_photo()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, self.item.name)
        self.assertContains(response, photo.thumbnail.url)
        self.assertContains(response, reverse("item-detail", args=[self.item.pk]))

    def test_preview_shows_the_other_participant(self) -> None:
        self.client.force_login(self.borrower)

        self.assertContains(self.client.get(self.url), self.lender.profile.full_name())

    def test_an_item_without_a_photo_still_renders(self) -> None:
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.name)

    def test_a_removed_item_keeps_its_name_but_offers_no_link(self) -> None:
        self.item.soft_delete(deleted_by=self.lender)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        # The Item page 404s once it is removed, so the name is not a link.
        self.assertEqual(response.context["item_name"], self.item.name)
        self.assertTrue(response.context["item_removed"])
        self.assertIsNone(response.context["item_url"])
        self.assertContains(response, self.item.name)

    def test_an_item_whose_row_is_gone_says_so(self) -> None:
        item_name = self.item.name
        self.item.delete()
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertIsNone(response.context["item_name"])
        self.assertContains(response, "Item unavailable")
        self.assertNotContains(response, item_name)

    def test_a_viewer_who_lost_item_access_keeps_the_name_without_a_link(self) -> None:
        remove_perm(ItemOLP.VIEW, self.borrower, self.item)
        self.client.force_login(self.borrower)

        response = self.client.get(self.url)

        self.assertContains(response, self.item.name)
        self.assertNotContains(response, reverse("item-detail", args=[self.item.pk]))

    def test_the_preview_costs_no_query_per_photo(self) -> None:
        self.add_photo()
        self.client.force_login(self.borrower)
        with CaptureQueriesContext(connection) as one_photo:
            self.client.get(self.url)

        for _ in range(4):
            self.add_photo()
        with CaptureQueriesContext(connection) as many_photos:
            self.client.get(self.url)

        self.assertEqual(len(many_photos), len(one_photo))
