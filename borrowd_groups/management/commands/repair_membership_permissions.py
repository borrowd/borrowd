from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
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

        found_count = 0
        repaired_count = 0
        failed_count = 0

        for membership in drifted_memberships.iterator():
            found_count += 1
            self.stdout.write(
                f"Drifted membership: user={membership.user} group={membership.group}"
            )
            if dry_run:
                continue

            try:
                repaired = self._repair_membership(membership.pk)
            except Exception as e:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to repair membership user={membership.user} "
                        f"group={membership.group}: {e}"
                    )
                )
                continue

            if repaired:
                repaired_count += 1
            else:
                self.stdout.write(
                    f"  already resolved before repair, skipping: "
                    f"user={membership.user} group={membership.group}"
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"{found_count} drifted membership(s) found (dry run)."
                )
            )
        elif failed_count:
            self.stdout.write(
                self.style.ERROR(
                    f"{repaired_count} of {found_count} drifted membership(s) "
                    f"repaired, {failed_count} failed."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{repaired_count} of {found_count} drifted membership(s) repaired."
                )
            )

    def _repair_membership(self, membership_id: int) -> bool:
        """
        Re-fetch and lock the membership immediately before repairing it,
        and re-validate it's still drifted. Guards against a concurrent
        status change (e.g. the user leaving the group) landing between
        detection and repair during a long-running pass; returns False
        without making changes if the drift was already resolved.
        """
        with transaction.atomic():
            membership = (
                Membership.objects.select_for_update()
                .select_related("group__perms_group", "user")
                .get(pk=membership_id)
            )
            perms_group = membership.group.perms_group
            if (
                membership.status != MembershipStatus.ACTIVE
                or perms_group is None
                or membership.user.groups.filter(pk=perms_group.pk).exists()
            ):
                return False
            sync_membership_permissions(membership)
            return True
