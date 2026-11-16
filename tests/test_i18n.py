from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language, override
from notifications.models import Notification

from borrowd_notifications.models import NotificationState, NotificationType
from borrowd_notifications.services import NotificationService
from borrowd_users.models import BorrowdUser


class LocaleInfrastructureTests(TestCase):
    def test_foreign_accept_language_falls_back_to_english(self) -> None:
        response = self.client.get(reverse("account_login"), HTTP_ACCEPT_LANGUAGE="es")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Language"], "en")

    def test_urls_have_no_language_prefix(self) -> None:
        self.assertFalse(reverse("account_signup").startswith("/en/"))
        self.assertFalse(reverse("item-list").startswith("/en/"))


class NotificationLanguageIsolationTests(TestCase):
    def test_dispatch_ignores_active_request_language(self) -> None:
        seen: list[str | None] = []
        with (
            patch.object(
                NotificationService,
                "_dispatch",
                side_effect=lambda _: seen.append(get_language()),
            ),
            override("es"),
        ):
            NotificationService.send_notification(MagicMock())
            self.assertEqual(get_language(), "es")
        self.assertEqual(seen, [settings.LANGUAGE_CODE])

    def test_digest_ignores_active_request_language(self) -> None:
        user = BorrowdUser.objects.create(username="digest")
        Notification.objects.create(
            recipient=user,
            actor=user,
            verb=NotificationType.ITEM_REQUESTED.value,
            data={
                "summary_digest": {
                    "status": NotificationState.PENDING.value,
                    "scheduled_for": (timezone.now() - timedelta(hours=1)).isoformat(),
                }
            },
        )
        seen: list[str | None] = []
        with (
            patch.object(
                NotificationService,
                "_send_digest_for_recipient",
                side_effect=lambda *_: seen.append(get_language()),
            ),
            override("es"),
        ):
            NotificationService.send_pending_digests()
        self.assertEqual(seen, [settings.LANGUAGE_CODE])
