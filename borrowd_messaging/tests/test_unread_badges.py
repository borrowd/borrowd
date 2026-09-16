from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.template import Context, Template
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from borrowd_messaging.context_processors import messaging_enabled
from borrowd_messaging.models import ArchiveReason, Message
from borrowd_messaging.read_state import mark_thread_read
from borrowd_messaging.services import MessagingService
from borrowd_messaging.views import ChatThreadUnreadBadgeView

from .base import MessagingTestCase
from .test_views import _element_attributes


@override_settings(MESSAGING_ENABLED=True)
class UnreadBadgeContextTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.notice = MessagingService.post_system_message(self.thread, "An update.")
        self.request = RequestFactory().get("/")
        self.request.user = self.borrower

    def test_count_is_lazy_and_reused_within_one_render(self) -> None:
        with self.assertNumQueries(0):
            context = messaging_enabled(self.request)
        template = Template(
            "{% if unread_conversation_count %}"
            "{{ unread_conversation_count }}:{{ unread_conversation_count }}"
            "{% endif %}"
        )
        with self.assertNumQueries(1):
            self.assertEqual(template.render(Context(context)), "1:1")

    def test_fragment_without_badge_does_not_evaluate_the_count(self) -> None:
        with self.assertNumQueries(0):
            context = messaging_enabled(self.request)
            self.assertEqual(
                Template("Message fragment").render(Context(context)),
                "Message fragment",
            )

    def test_a_new_context_reads_fresh_state(self) -> None:
        before = messaging_enabled(self.request)
        self.assertEqual(str(before["unread_conversation_count"]), "1")
        mark_thread_read(self.thread, self.borrower, through_message_id=self.notice.pk)
        after = messaging_enabled(self.request)
        self.assertEqual(str(after["unread_conversation_count"]), "0")

    @override_settings(MESSAGING_ENABLED=False)
    def test_disabled_messaging_does_not_prepare_or_query_a_count(self) -> None:
        with self.assertNumQueries(0):
            self.assertEqual(
                messaging_enabled(self.request), {"messaging_enabled": False}
            )

    def test_anonymous_request_does_not_prepare_or_query_a_count(self) -> None:
        self.request.user = AnonymousUser()
        with self.assertNumQueries(0):
            self.assertEqual(
                messaging_enabled(self.request), {"messaging_enabled": True}
            )


@override_settings(MESSAGING_ENABLED=True)
class UnreadBadgeViewTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.url = reverse("chat-thread-unread-badge")
        self.client.force_login(self.borrower)

    def test_zero_has_no_visible_badge(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0 unread conversations")
        self.assertNotContains(response, 'data-testid="nav-messages-unread-count"')

    def test_counts_threads_in_both_roles_including_archived_notices(self) -> None:
        for _ in range(3):
            Message.objects.create(
                thread=self.thread, sender=self.lender, body="Hello."
            )
        lending_thread = self.make_thread(
            item=self.make_item(owner=self.borrower),
            lender=self.borrower,
            borrower=self.lender,
        )
        MessagingService.archive_thread(lending_thread, ArchiveReason.CLOSED)
        unrelated = self.make_thread(borrower=self.make_user("outsider"))
        MessagingService.post_system_message(unrelated, "Private notice.")

        response = self.client.get(self.url)

        self.assertContains(response, "2 unread conversations")
        self.assertContains(
            response, 'data-testid="nav-messages-unread-count">2</span>'
        )
        self.assertNotContains(response, "Hello.")
        self.assertNotContains(response, "Private notice.")

    def test_own_human_messages_do_not_produce_a_badge(self) -> None:
        Message.objects.create(
            thread=self.thread, sender=self.borrower, body="My message."
        )
        self.assertNotContains(
            self.client.get(self.url), 'data-testid="nav-messages-unread-count"'
        )

    def test_read_acknowledgment_clears_only_the_viewers_badge(self) -> None:
        notice = MessagingService.post_system_message(self.thread, "An update.")
        self.assertContains(self.client.get(self.url), "1 unread conversation</span>")
        response = self.client.post(
            reverse("chat-thread-read", args=[self.thread.pk]), {"through": notice.pk}
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotContains(
            self.client.get(self.url), 'data-testid="nav-messages-unread-count"'
        )
        self.client.force_login(self.lender)
        self.assertContains(self.client.get(self.url), "1 unread conversation</span>")

    def test_badge_get_does_not_mark_anything_read(self) -> None:
        MessagingService.post_system_message(self.thread, "An update.")
        before = (self.thread.updated_at, self.thread.updated_by_id)
        self.client.get(self.url)
        self.thread.refresh_from_db()
        self.assertIsNone(self.thread.lender_last_read_message_id)
        self.assertIsNone(self.thread.borrower_last_read_message_id)
        self.assertEqual((self.thread.updated_at, self.thread.updated_by_id), before)

    def test_archived_history_survives_item_deletion_in_badge(self) -> None:
        self.item.delete()
        self.assertContains(self.client.get(self.url), "1 unread conversation</span>")

    def test_fragment_costs_one_query_without_page_context_processors(self) -> None:
        MessagingService.post_system_message(self.thread, "An update.")
        request = RequestFactory().get(self.url)
        request.user = self.borrower
        with self.assertNumQueries(1):
            response = ChatThreadUnreadBadgeView.as_view()(request)
        self.assertContains(response, "1 unread conversation</span>")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="nav-messages-unread"')

    def test_fragment_cannot_be_cached(self) -> None:
        response = self.client.get(self.url)
        for directive in ("private", "no-store", "no-cache", "max-age=0"):
            self.assertIn(directive, response["Cache-Control"])

    def test_anonymous_requests_are_denied_without_login_html_redirects(self) -> None:
        self.client.logout()
        for headers in ({}, {"HX-Request": "true"}):
            with self.subTest(headers=headers):
                self.assertEqual(
                    self.client.get(self.url, headers=headers).status_code, 403
                )

    def test_superuser_count_is_still_participant_only(self) -> None:
        MessagingService.post_system_message(self.thread, "Private notice.")
        outsider = self.make_user("admin")
        outsider.is_superuser = True
        outsider.save(update_fields=["is_superuser"])
        self.client.force_login(outsider)
        self.assertContains(self.client.get(self.url), "0 unread conversations")

    @override_settings(MESSAGING_ENABLED=False)
    def test_feature_flag_hides_fragment(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_post_is_not_allowed(self) -> None:
        self.assertEqual(self.client.post(self.url).status_code, 405)


@override_settings(MESSAGING_ENABLED=True)
class UnreadBadgeNavigationTests(MessagingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.thread = self.make_thread()
        self.client.force_login(self.borrower)
        self.url = reverse("chat-thread-list")

    def test_navigation_renders_count_once_with_refresh_hooks(self) -> None:
        MessagingService.post_system_message(self.thread, "An update.")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)

        self.assertContains(response, 'id="nav-messages-unread"', count=1)
        self.assertContains(response, "1 unread conversation</span>")
        attrs = _element_attributes(response, "nav-messages-unread")
        self.assertEqual(attrs["hx-get"], reverse("chat-thread-unread-badge"))
        self.assertEqual(attrs["hx-sync"], "this:queue last")
        self.assertEqual(attrs["hx-swap"], "innerHTML")
        self.assertEqual(attrs["hx-request"], '{"timeout":10000}')
        self.assertEqual(attrs["aria-live"], "polite")
        triggers = attrs["hx-trigger"]
        assert triggers is not None
        self.assertIn("every 30s [document.visibilityState === 'visible']", triggers)
        self.assertIn(
            "messaging:read[document.visibilityState === 'visible'] from:document",
            triggers,
        )
        self.assertIn(
            "visibilitychange[document.visibilityState === 'visible'] from:document",
            triggers,
        )
        self.assertIn(
            "online[document.visibilityState === 'visible'] from:window", triggers
        )
        self.assertIn(
            "pageshow[persisted && document.visibilityState === 'visible'] from:window",
            triggers,
        )
        unread_counts = [
            query["sql"]
            for query in queries.captured_queries
            if "COUNT(" in query["sql"] and "borrowd_messaging_message" in query["sql"]
        ]
        self.assertEqual(len(unread_counts), 1)

    def test_zero_keeps_refresh_target_but_hides_visible_badge(self) -> None:
        response = self.client.get(self.url)
        self.assertContains(response, 'id="nav-messages-unread"')
        self.assertNotContains(response, 'data-testid="nav-messages-unread-count"')

    @override_settings(MESSAGING_ENABLED=False)
    def test_disabled_navigation_has_no_badge_or_messaging_count_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("item-list"))
        self.assertNotContains(response, 'id="nav-messages-unread"')
        self.assertNotContains(response, reverse("chat-thread-unread-badge"))
        self.assertFalse(
            any(
                "borrowd_messaging" in query["sql"]
                for query in queries.captured_queries
            )
        )

    def test_message_poll_does_not_run_an_unread_count(self) -> None:
        MessagingService.post_system_message(self.thread, "An update.")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                reverse("chat-thread-poll", args=[self.thread.pk]), {"after": 0}
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(
                "COUNT(" in query["sql"] and "borrowd_messaging_message" in query["sql"]
                for query in queries.captured_queries
            )
        )
