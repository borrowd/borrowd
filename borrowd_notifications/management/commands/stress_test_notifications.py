"""
Stress-tests notification channel dispatch latency.

Usage:
    uv run manage.py stress_test_notifications
    uv run manage.py stress_test_notifications --count 50
    uv run manage.py stress_test_notifications --count 50 --push-destinations 5
    uv run manage.py stress_test_notifications --count 50 --group-size 10
    uv run manage.py stress_test_notifications --count 50 --no-cleanup

Two sections are reported:

  1:1 sends — one notification, one recipient, repeated --count times.
  Group sends — one broadcast to --group-size recipients, repeated --count times.
              Reports total fanout time and derived per-recipient cost.

EMAIL uses the dummy backend (no real mail sent).
PUSH creates fake PushSubscription rows and patches webpush() to a no-op —
measures the per-destination iteration and DB overhead without real network calls.
--push-destinations controls how many device subscriptions each recipient has.
"""

import statistics
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.test.utils import override_settings
from notifications.signals import notify

from borrowd_notifications.models import (
    NotificationPreference,
    NotificationType,
    PushSubscription,
)
from borrowd_users.models import BorrowdUser


class Command(BaseCommand):
    help = "Stress-test notification channel dispatch latency."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=20,
            help="Number of notifications per scenario (default: 20).",
        )
        parser.add_argument(
            "--push-destinations",
            type=int,
            default=1,
            help="Number of fake push subscriptions per recipient user (default: 1).",
        )
        parser.add_argument(
            "--group-size",
            type=int,
            default=5,
            help="Number of recipients per group broadcast scenario (default: 5).",
        )
        parser.add_argument(
            "--no-cleanup",
            action="store_true",
            help="Keep test user and notifications after the run.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        count: int = options["count"]
        push_destinations: int = options["push_destinations"]
        group_size: int = options["group_size"]
        cleanup: bool = not options["no_cleanup"]

        sender, recipient = self._setup_users()
        self._create_push_subscriptions(recipient, push_destinations)
        group = self._setup_group(sender, group_size, push_destinations)

        try:
            self._run(sender, recipient, group, count, push_destinations, group_size)
        finally:
            if cleanup:
                for u in [sender, recipient, *group]:
                    u.delete()
                self.stdout.write(self.style.SUCCESS("Test users cleaned up."))
            else:
                self.stdout.write(
                    f"Test users kept — sender pk={sender.pk}, recipient pk={recipient.pk}"
                )

    def _setup_group(
        self, sender: BorrowdUser, size: int, push_destinations: int
    ) -> list[BorrowdUser]:
        BorrowdUser.objects.filter(username__startswith="stress_group_").delete()
        pw = make_password("stress-test-pw")
        members = []
        for i in range(size):
            u = BorrowdUser.objects.create(
                username=f"stress_group_{i}",
                email=f"stress_group_{i}@example.com",
                password=pw,
            )
            NotificationPreference.objects.create(
                user=u,
                notification_type=NotificationType.MEMBERSHIP_APPROVED.value,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=True,
            )
            self._create_push_subscriptions(
                u, push_destinations, offset=i * push_destinations + 1000
            )
            members.append(u)
        return members

    def _create_push_subscriptions(
        self, recipient: BorrowdUser, count: int, offset: int = 0
    ) -> None:
        for i in range(count):
            PushSubscription.objects.get_or_create(
                endpoint=f"https://fcm.example.com/stress-test-device-{offset + i}",
                defaults={
                    "user": recipient,
                    "p256dh": f"fake-p256dh-{offset + i}",
                    "auth": f"fake-auth-{offset + i}",
                },
            )

    def _setup_users(self) -> tuple[BorrowdUser, BorrowdUser]:
        BorrowdUser.objects.filter(
            username__in=["stress_sender", "stress_recipient"]
        ).delete()
        pw = make_password("stress-test-pw")
        sender = BorrowdUser.objects.create(
            username="stress_sender",
            email="stress_sender@example.com",
            password=pw,
        )
        recipient = BorrowdUser.objects.create(
            username="stress_recipient",
            email="stress_recipient@example.com",
            password=pw,
        )
        return sender, recipient

    def _set_prefs(
        self,
        recipient: BorrowdUser,
        *,
        app: bool,
        email: bool,
        push: bool,
        ntype: NotificationType = NotificationType.MEMBERSHIP_APPROVED,
    ) -> None:
        NotificationPreference.objects.update_or_create(
            user=recipient,
            notification_type=ntype.value,
            defaults={
                "in_app_enabled": app,
                "email_enabled": email,
                "push_enabled": push,
            },
        )

    def _run_with_patches(
        self, push: bool, fn: Callable[[], list[float]]
    ) -> list[float]:
        """Run fn() inside silent-email + webpush-mock context."""
        timings: list[float] = []
        with (
            override_settings(
                EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend"
            ),
            patch("builtins.print"),
            patch("borrowd_notifications.channels.webpush", MagicMock())
            if push
            else nullcontext(),
        ):
            timings = fn()
        return timings

    def _send_one(self, sender: BorrowdUser, recipient: BorrowdUser) -> float:
        start = time.perf_counter()
        notify.send(
            sender,
            recipient=recipient,
            verb=NotificationType.MEMBERSHIP_APPROVED.value,
            target=recipient,
        )
        return time.perf_counter() - start

    def _send_group(self, sender: BorrowdUser, members: list[BorrowdUser]) -> float:
        start = time.perf_counter()
        notify.send(
            sender,
            recipient=members,
            verb=NotificationType.MEMBERSHIP_APPROVED.value,
            target=sender,
        )
        return time.perf_counter() - start

    def _print_row(
        self, label: str, channels: str, ms: list[float], extra: str = ""
    ) -> None:
        self.stdout.write(
            f"  {label:<34} channels={channels:<20} "
            f"mean={statistics.mean(ms):6.1f}ms  "
            f"median={statistics.median(ms):6.1f}ms  "
            f"p95={sorted(ms)[int(len(ms) * 0.95)]:6.1f}ms  "
            f"min={min(ms):6.1f}ms  max={max(ms):6.1f}ms"
            + (f"  {extra}" if extra else "")
        )

    def _run_scenario(
        self,
        label: str,
        sender: BorrowdUser,
        recipient: BorrowdUser,
        count: int,
        *,
        app: bool,
        email: bool,
        push: bool,
    ) -> None:
        self._set_prefs(recipient, app=app, email=email, push=push)

        def fn() -> list[float]:
            return [self._send_one(sender, recipient) for _ in range(count)]

        timings = self._run_with_patches(push, fn)
        channels = (
            "+".join(
                c for c, on in [("APP", app), ("EMAIL", email), ("PUSH", push)] if on
            )
            or "none"
        )
        self._print_row(label, channels, [t * 1000 for t in timings])

    def _run_group_scenario(
        self,
        label: str,
        sender: BorrowdUser,
        members: list[BorrowdUser],
        count: int,
        *,
        push: bool,
    ) -> None:
        def fn() -> list[float]:
            return [self._send_group(sender, members) for _ in range(count)]

        timings = self._run_with_patches(push, fn)
        ms = [t * 1000 for t in timings]
        per_recipient = [t / len(members) for t in ms]
        self._print_row(
            label,
            "APP+EMAIL+PUSH" if push else "APP+EMAIL",
            ms,
            extra=f"(per-recipient mean={statistics.mean(per_recipient):.1f}ms)",
        )

    def _run(
        self,
        sender: BorrowdUser,
        recipient: BorrowdUser,
        group: list[BorrowdUser],
        count: int,
        push_destinations: int,
        group_size: int,
    ) -> None:
        self.stdout.write(
            f"\nStress-testing notifications — {count} sends per scenario, "
            f"{push_destinations} push destination(s) per user\n"
        )

        self.stdout.write("── 1:1 sends ──" + "─" * 95)
        for label, prefs in [
            ("APP only", dict(app=True, email=False, push=False)),
            ("EMAIL only", dict(app=False, email=True, push=False)),
            ("PUSH only", dict(app=False, email=False, push=True)),
            ("APP + EMAIL", dict(app=True, email=True, push=False)),
            ("APP + PUSH", dict(app=True, email=False, push=True)),
            ("EMAIL + PUSH", dict(app=False, email=True, push=True)),
            ("APP + EMAIL + PUSH", dict(app=True, email=True, push=True)),
        ]:
            self._run_scenario(label, sender, recipient, count, **prefs)

        self.stdout.write(f"\n── Group sends ({group_size} recipients) ──" + "─" * 74)
        self._run_group_scenario(
            "Broadcast (no push)", sender, group, count, push=False
        )
        self._run_group_scenario(
            "Broadcast (all channels)", sender, group, count, push=True
        )

        self.stdout.write("─" * 110)
        self.stdout.write(self.style.SUCCESS("Done.\n"))
