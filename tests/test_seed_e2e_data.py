from io import StringIO

from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from borrowd.management.commands.seed_e2e_data import (
    E2E_GROUP_NAME,
    E2E_PASSWORD,
    E2E_USERS,
)
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_users.models import BorrowdUser


def _seed() -> None:
    call_command("seed_e2e_data", stdout=StringIO())


def _seed_and_dispatch(test: TestCase) -> None:
    # Notification delivery runs on transaction commit, which TestCase's
    # wrapping transaction never reaches unless callbacks are captured.
    with test.captureOnCommitCallbacks(execute=True):
        _seed()


@override_settings(DEBUG=True)
class SeedE2EDataTests(TestCase):
    def test_users_can_log_in_with_verified_emails(self) -> None:
        _seed()
        for username, email in E2E_USERS.values():
            self.assertTrue(
                self.client.login(username=username, password=E2E_PASSWORD),
                f"{username} cannot log in",
            )
            self.client.logout()
            self.assertTrue(
                EmailAddress.objects.filter(
                    email=email, verified=True, primary=True
                ).exists()
            )

    def test_all_users_are_active_members_of_the_shared_group(self) -> None:
        _seed()
        group = BorrowdGroup.objects.get(name=E2E_GROUP_NAME)
        for username, _ in E2E_USERS.values():
            membership = Membership.objects.get(
                user=BorrowdUser.objects.get(username=username), group=group
            )
            self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_user_has_unread_in_app_notifications(self) -> None:
        _seed_and_dispatch(self)
        user = BorrowdUser.objects.get(username=E2E_USERS["user"][0])
        notifications = user.notifications  # type: ignore[attr-defined]  # django-notifications is untyped
        visible_unread = notifications.unread().filter(
            borrowd_metadata__visible_in_app=True
        )
        self.assertGreaterEqual(visible_unread.count(), 1)

    def test_seeding_twice_changes_nothing(self) -> None:
        _seed()
        _seed()
        self.assertEqual(BorrowdGroup.objects.filter(name=E2E_GROUP_NAME).count(), 1)
        self.assertEqual(
            BorrowdUser.objects.filter(
                username__in=[u for u, _ in E2E_USERS.values()]
            ).count(),
            len(E2E_USERS),
        )
        user = BorrowdUser.objects.get(username=E2E_USERS["user"][0])
        self.assertEqual(
            user.notifications.count(),  # type: ignore[attr-defined]  # django-notifications is untyped
            len(E2E_USERS) - 1,
        )


class SeedE2EDataSafetyTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_without_debug_or_flag(self) -> None:
        with self.assertRaises(CommandError):
            _seed()
        self.assertFalse(BorrowdUser.objects.filter(username="e2e-user").exists())

    @override_settings(DEBUG=False)
    def test_flag_allows_running_without_debug(self) -> None:
        call_command("seed_e2e_data", "--allow-known-passwords", stdout=StringIO())
        self.assertTrue(BorrowdUser.objects.filter(username="e2e-user").exists())
