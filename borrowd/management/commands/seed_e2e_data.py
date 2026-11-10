"""Seed the fixed users and shared group the E2E regression suite logs in with.

Adding the borrower and lender to the group also gives the E2E user unread
"member joined" notifications, so the notification bell shows a badge.

The data is deterministic and idempotent so the suite can run against a freshly
migrated database in CI. It sets known passwords, so it refuses to run unless
``DEBUG`` is on or ``--allow-known-passwords`` is passed.
"""

from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_users.models import BorrowdUser

E2E_PASSWORD = "e2e-password-not-a-secret"
E2E_GROUP_NAME = "E2E Seed Group"

# (username, email) for each account the suite authenticates as.
E2E_USERS = {
    "user": ("e2e-user", "e2e-user@example.com"),
    "borrower": ("e2e-borrower", "e2e-borrower@example.com"),
    "lender": ("e2e-lender", "e2e-lender@example.com"),
}


class Command(BaseCommand):
    help = (
        "Create the deterministic users, shared group and the unread notifications "
        "used by the E2E regression suite. Safe to run repeatedly."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--allow-known-passwords",
            action="store_true",
            help="Run even when DEBUG is off. The seeded accounts share a "
            "publicly known password, so only use this on throwaway databases.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["allow_known_passwords"]:
            raise CommandError(
                "Refusing to create accounts with a known password while DEBUG "
                "is off. Pass --allow-known-passwords on a throwaway database."
            )

        users = {role: self._ensure_user(*creds) for role, creds in E2E_USERS.items()}
        group = self._ensure_group(users["user"])
        for role in ("borrower", "lender"):
            if not Membership.objects.filter(user=users[role], group=group).exists():
                group.add_user(users[role])

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(users)} users and group '{group.name}' for the E2E suite."
            )
        )

    def _ensure_user(self, username: str, email: str) -> BorrowdUser:
        user, _ = BorrowdUser.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        user.email = email
        user.set_password(E2E_PASSWORD)
        user.save()
        EmailAddress.objects.update_or_create(
            user=user,
            email=email,
            defaults={"verified": True, "primary": True},
        )
        return user

    def _ensure_group(self, owner: BorrowdUser) -> BorrowdGroup:
        existing = BorrowdGroup.objects.filter(name=E2E_GROUP_NAME).first()
        if existing is not None:
            return existing
        return BorrowdGroup.objects.create_group(
            name=E2E_GROUP_NAME,
            description="Group shared by the E2E user, borrower and lender.",
            membership_requires_approval=False,
            created_by=owner,
            updated_by=owner,
        )
