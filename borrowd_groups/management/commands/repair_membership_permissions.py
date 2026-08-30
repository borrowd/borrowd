from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import F

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_groups.signals import sync_membership_permissions


class Command(BaseCommand):
    help = (
        "Repairs ACTIVE memberships whose user was never enrolled in their "
        "group's perms_group auth.Group — the symptom left behind when a "
        "Membership row is saved through a historical model (e.g. a data "
        "migration using apps.get_model()), which does not dispatch to the "
        "live post_save receiver. Safe to re-run: healthy rows are left alone."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report drifted memberships without making any changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]

        drifted_memberships = (
            Membership.objects.filter(
                status=MembershipStatus.ACTIVE,
                group__perms_group__isnull=False,
            )
            .exclude(user__groups=F("group__perms_group"))
            .select_related("group__perms_group", "user")
        )

        count = 0
        for membership in drifted_memberships.iterator():
            count += 1
            self.stdout.write(
                f"Drifted membership: user={membership.user} group={membership.group}"
            )
            if dry_run:
                continue
            try:
                sync_membership_permissions(membership)
            except ValueError as e:
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to repair membership user={membership.user} "
                        f"group={membership.group}: {e}"
                    )
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"{count} drifted membership(s) found (dry run).")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"{count} drifted membership(s) repaired.")
            )
