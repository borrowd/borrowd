from django.test import Client, override_settings
from django.urls import reverse

from borrowd_messaging.models import ArchiveReason, Message
from borrowd_messaging.read_state import unread_threads_for
from borrowd_messaging.services import MessagingService

from .base import MessagingTestCase
from .test_views import _element_attributes


@override_settings(MESSAGING_ENABLED=True)
class ChatThreadReadViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.message = Message.objects.create(
            thread=self.thread, sender=self.lender, body="Saturday works."
        )
        self.url = reverse("chat-thread-read", args=[self.thread.pk])
        self.client.force_login(self.borrower)

    def test_each_participant_updates_only_their_own_bookmark(self) -> None:
        response = self.client.post(self.url, {"through": self.message.pk})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["HX-Trigger"], "messaging:read")
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)
        self.assertIsNone(self.thread.lender_last_read_message_id)

        self.client.force_login(self.lender)
        self.assertEqual(
            self.client.post(self.url, {"through": self.message.pk}).status_code, 204
        )
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.lender_last_read_message_id, self.message.pk)

    def test_later_message_stays_unread_and_old_acknowledgments_do_not_regress(
        self,
    ) -> None:
        newer = Message.objects.create(
            thread=self.thread, sender=self.lender, body="After noon, please."
        )
        self.client.post(self.url, {"through": self.message.pk})
        self.assertTrue(unread_threads_for(self.borrower).exists())
        self.client.post(self.url, {"through": newer.pk})

        for through in (newer.pk, self.message.pk, 0):
            with self.subTest(through=through):
                self.assertEqual(
                    self.client.post(self.url, {"through": through}).status_code, 204
                )
                self.thread.refresh_from_db()
                self.assertEqual(self.thread.borrower_last_read_message_id, newer.pk)
        self.assertFalse(unread_threads_for(self.borrower).exists())

    def test_zero_does_not_mark_existing_messages_read(self) -> None:
        self.assertEqual(self.client.post(self.url, {"through": 0}).status_code, 204)
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_invalid_or_foreign_message_is_rejected(self) -> None:
        other = self.make_thread(item=self.make_item(name="Ladder"))
        foreign = Message.objects.create(
            thread=other, sender=self.lender, body="Another conversation."
        )
        cases = (
            {},
            *(
                {"through": value}
                for value in (
                    "",
                    "abc",
                    "1.5",
                    -1,
                    foreign.pk,
                    foreign.pk + 1000,
                    2**100,
                )
            ),
        )
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_outsider_including_superuser_cannot_acknowledge(self) -> None:
        outsider = self.make_user("outsider")
        self.client.force_login(outsider)
        for superuser in (False, True):
            outsider.is_superuser = superuser
            outsider.save(update_fields=["is_superuser"])
            with self.subTest(superuser=superuser):
                self.assertEqual(
                    self.client.post(
                        self.url, {"through": self.message.pk}
                    ).status_code,
                    404,
                )
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_anonymous_user_is_redirected_without_updating(self) -> None:
        self.client.logout()
        self.assertEqual(
            self.client.post(self.url, {"through": self.message.pk}).status_code, 302
        )
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    @override_settings(MESSAGING_ENABLED=False)
    def test_disabled_messaging_returns_404(self) -> None:
        self.assertEqual(
            self.client.post(self.url, {"through": self.message.pk}).status_code, 404
        )
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)

    def test_only_post_is_allowed(self) -> None:
        for method in (
            self.client.get,
            self.client.head,
            self.client.put,
            self.client.delete,
        ):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self.url).status_code, 405)

    def test_archived_and_deleted_item_history_can_be_acknowledged(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        self.item.delete()
        self.thread.refresh_from_db()
        before = (
            self.thread.updated_at,
            self.thread.updated_by_id,
            self.thread.archived_at,
            self.thread.archive_reason,
        )
        message_ids = list(self.thread.messages.values_list("pk", flat=True))

        self.assertEqual(
            self.client.post(self.url, {"through": self.message.pk}).status_code, 204
        )

        self.thread.refresh_from_db()
        self.assertEqual(self.thread.borrower_last_read_message_id, self.message.pk)
        self.assertEqual(
            before,
            (
                self.thread.updated_at,
                self.thread.updated_by_id,
                self.thread.archived_at,
                self.thread.archive_reason,
            ),
        )
        self.assertCountEqual(
            self.thread.messages.values_list("pk", flat=True), message_ids
        )

    def test_initial_page_asks_htmx_to_acknowledge_only_the_last_message(self) -> None:
        newest = Message.objects.create(
            thread=self.thread, sender=self.lender, body="After noon, please."
        )
        detail = self.client.get(reverse("chat-thread-detail", args=[self.thread.pk]))

        older_attrs = _element_attributes(detail, f"message-{self.message.pk}")
        newest_attrs = _element_attributes(detail, f"message-{newest.pk}")
        self.assertNotIn("hx-post", older_attrs)
        self.assertEqual(newest_attrs["hx-post"], self.url)
        self.assertEqual(newest_attrs["hx-trigger"], "load")
        self.assertEqual(newest_attrs["hx-vals"], f'{{"through":"{newest.pk}"}}')
        self.assertEqual(newest_attrs["hx-swap"], "none")

    def test_poll_and_send_ask_htmx_to_acknowledge_their_last_message(self) -> None:
        incoming = Message.objects.create(
            thread=self.thread, sender=self.lender, body="After noon, please."
        )
        poll = self.client.get(
            reverse("chat-thread-poll", args=[self.thread.pk]),
            {"after": self.message.pk},
        )
        self.assertEqual(poll.status_code, 200)
        self.assertEqual(
            _element_attributes(poll, f"message-{incoming.pk}")["hx-post"],
            self.url,
        )

        sent = self.client.post(
            reverse("chat-thread-send", args=[self.thread.pk]),
            {"after": incoming.pk, "body": "Sounds good."},
        )
        self.assertEqual(sent.status_code, 200)
        reply = self.thread.messages.latest("pk")
        reply_attrs = _element_attributes(sent, f"message-{reply.pk}")
        self.assertEqual(reply_attrs["hx-post"], self.url)
        self.assertEqual(reply_attrs["hx-vals"], f'{{"through":"{reply.pk}"}}')

    def test_final_archive_poll_asks_htmx_to_acknowledge_before_polling_stops(
        self,
    ) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        notice = self.thread.messages.latest("pk")

        response = self.client.get(
            reverse("chat-thread-poll", args=[self.thread.pk]),
            {"after": self.message.pk},
        )

        self.assertEqual(response.status_code, 286)
        notice_attrs = _element_attributes(response, f"message-{notice.pk}")
        self.assertEqual(notice_attrs["hx-post"], self.url)
        self.assertEqual(notice_attrs["hx-trigger"], "load")
        self.assertEqual(notice_attrs["hx-vals"], f'{{"through":"{notice.pk}"}}')
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)
        self.assertTrue(unread_threads_for(self.borrower).exists())

    def test_rendering_messages_does_not_write_read_state_on_the_server(self) -> None:
        self.client.get(reverse("chat-thread-detail", args=[self.thread.pk]))
        self.client.get(
            reverse("chat-thread-poll", args=[self.thread.pk]), {"after": 0}
        )
        self.client.post(
            reverse("chat-thread-send", args=[self.thread.pk]),
            {"after": 0, "body": "Sounds good."},
        )
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)
        self.assertTrue(unread_threads_for(self.borrower).exists())

    def test_closing_notice_needs_acknowledgment_even_from_the_person_who_closed(
        self,
    ) -> None:
        response = self.client.post(
            reverse("chat-thread-pre-request-close", args=[self.thread.pk])
        )
        self.assertEqual(response.status_code, 302)
        notice = self.thread.messages.latest("pk")
        self.assertTrue(notice.is_system)

        detail = self.client.get(reverse("chat-thread-detail", args=[self.thread.pk]))
        self.assertContains(detail, f'id="message-{notice.pk}"')
        self.assertEqual(
            _element_attributes(detail, f"message-{notice.pk}")["hx-post"], self.url
        )
        self.client.post(self.url, {"through": self.message.pk})
        for viewer in (self.borrower, self.lender):
            self.assertTrue(unread_threads_for(viewer).exists())

        for viewer in (self.borrower, self.lender):
            with self.subTest(viewer=viewer.pk):
                self.client.force_login(viewer)
                self.assertEqual(
                    self.client.post(self.url, {"through": notice.pk}).status_code,
                    204,
                )
                self.assertFalse(unread_threads_for(viewer).exists())
                if viewer == self.borrower:
                    self.assertTrue(unread_threads_for(self.lender).exists())

    def test_archived_detail_supplies_csrf_cookie_and_endpoint(self) -> None:
        MessagingService.archive_thread(self.thread, ArchiveReason.CLOSED)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.borrower)

        detail = client.get(reverse("chat-thread-detail", args=[self.thread.pk]))
        notice = self.thread.messages.latest("pk")

        self.assertEqual(
            _element_attributes(detail, f"message-{notice.pk}")["hx-post"],
            self.url,
        )
        self.assertIn("csrftoken", client.cookies)
        self.assertEqual(
            client.post(self.url, {"through": self.message.pk}).status_code, 403
        )
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.borrower_last_read_message_id)
        self.assertEqual(
            client.post(
                self.url,
                {"through": self.message.pk},
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            ).status_code,
            204,
        )
