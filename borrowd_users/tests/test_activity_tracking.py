"""Tests for RecordUserActivityMiddleware and UserActivityDay."""

from datetime import timedelta
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone

from borrowd_users.middleware import SESSION_KEY, _is_excluded_path
from borrowd_users.models import BorrowdUser, UserActivityDay


class RecordUserActivityMiddlewareTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="activity_user",
            email="activity_user@example.com",
            password="password",
        )

    def test_authenticated_request_writes_one_row_for_today(self) -> None:
        self.client.force_login(self.user)
        self.client.get("/")

        rows = list(UserActivityDay.objects.filter(user=self.user))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].date, timezone.now().date())

    def test_repeated_requests_same_day_write_only_one_row(self) -> None:
        self.client.force_login(self.user)
        self.client.get("/")
        self.client.get("/")
        self.client.get("/")

        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_no_write_when_session_value_is_current(self) -> None:
        self.client.force_login(self.user)
        self.client.get("/")

        with mock.patch(
            "borrowd_users.middleware.UserActivityDay.objects.get_or_create"
        ) as mocked:
            self.client.get("/")
            mocked.assert_not_called()

    def test_anonymous_request_writes_no_row(self) -> None:
        self.client.get("/")

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_admin_path_writes_no_row(self) -> None:
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

        self.client.get("/admin/")

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_static_path_writes_no_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get("/static/does-not-matter.js")

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_notification_count_poll_writes_no_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get(
            "/notifications/notification-count/", headers={"HX-Request": "true"}
        )

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_messages_unread_badge_poll_writes_no_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get("/messages/unread-badge/", headers={"HX-Request": "true"})

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_chat_thread_poll_writes_no_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get("/messages/1/poll/", headers={"HX-Request": "true"})

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_notification_inbox_htmx_refresh_writes_no_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get("/notifications/", headers={"HX-Request": "true"})

        self.assertEqual(UserActivityDay.objects.count(), 0)

    def test_notification_inbox_direct_visit_writes_one_row(self) -> None:
        self.client.force_login(self.user)

        self.client.get("/notifications/")

        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_stale_session_value_from_a_previous_day_still_writes_todays_row(
        self,
    ) -> None:
        yesterday = timezone.now().date() - timedelta(days=1)
        UserActivityDay.objects.create(user=self.user, date=yesterday)

        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_KEY] = yesterday.isoformat()
        session.save()

        self.client.get("/")

        rows = UserActivityDay.objects.filter(user=self.user)
        self.assertEqual(rows.count(), 2)
        self.assertTrue(rows.filter(date=timezone.now().date()).exists())

    def test_database_error_does_not_break_the_request_and_is_retried_next_time(
        self,
    ) -> None:
        self.client.force_login(self.user)

        with mock.patch(
            "borrowd_users.middleware.UserActivityDay.objects.get_or_create",
            side_effect=DatabaseError("connection lost"),
        ):
            response = self.client.get("/")

        self.assertLess(response.status_code, 500)
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 0)
        self.assertNotIn(SESSION_KEY, self.client.session)

        # No session key was set on failure, so the next request retries.
        self.client.get("/")
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)


class IsExcludedPathTests(TestCase):
    def test_admin_static_and_media_paths_are_excluded(self) -> None:
        self.assertTrue(
            _is_excluded_path("/admin/borrowd_items/item/", is_htmx_request=False)
        )
        self.assertTrue(_is_excluded_path("/static/js/main.js", is_htmx_request=False))
        self.assertTrue(
            _is_excluded_path("/media/profile_pics/1.jpg", is_htmx_request=False)
        )

    def test_ordinary_path_is_not_excluded(self) -> None:
        self.assertFalse(_is_excluded_path("/items/", is_htmx_request=False))

    def test_an_empty_media_url_does_not_match_every_path(self) -> None:
        # override_settings normalizes MEDIA_URL to end with "/", turning ""
        # into "/", so an actually-empty value can only be exercised by
        # patching the settings object the module reads directly.
        with mock.patch("borrowd_users.middleware.settings") as mocked_settings:
            mocked_settings.STATIC_URL = "static/"
            mocked_settings.MEDIA_URL = ""

            self.assertFalse(_is_excluded_path("/items/", is_htmx_request=False))

    def test_fixed_polling_paths_are_excluded_regardless_of_htmx_header(
        self,
    ) -> None:
        self.assertTrue(
            _is_excluded_path(
                "/notifications/notification-count/", is_htmx_request=False
            )
        )
        self.assertTrue(
            _is_excluded_path("/messages/unread-badge/", is_htmx_request=False)
        )
        self.assertTrue(_is_excluded_path("/messages/42/poll/", is_htmx_request=False))

    def test_notification_inbox_is_excluded_only_for_htmx_requests(self) -> None:
        self.assertTrue(_is_excluded_path("/notifications/", is_htmx_request=True))
        self.assertFalse(_is_excluded_path("/notifications/", is_htmx_request=False))
