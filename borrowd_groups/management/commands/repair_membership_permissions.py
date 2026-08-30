from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import F

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_groups.signals import sync_membership_permissions


class Command(BaseCommand):
    help = (
        "Resyncs permissions for every ACTIVE membership, deriving group- "
        "and item-level guardian permissions and perms_group auth.Group "
        "enrollment straight from each Membership row. Intentionally "
        "unconditional rather than targeting only rows missing perms_group "
        "enrollment: a narrower check would miss other permission facets "
        "(e.g. stale moderator permissions) left behind by the same root "
        "cause — a Membership row saved through a historical model (e.g. a "
        "data migration using apps.get_model()), which does not dispatch "
        "to the live post_save receiver. Safe to re-run: already-correct "
        "rows are a no-op."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report memberships missing perms_group enrollment without "
                "making any changes."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]

        active_memberships = Membership.objects.filter(
            status=MembershipStatus.ACTIVE,
            group__perms_group__isnull=False,
        ).select_related("group__perms_group", "user")

        # Missing perms_group enrollment is the loudest, most visible
        # symptom of the drift this command fixes, so it's worth reporting
        # on its own — but it is only used for reporting/scope-verification
        # here. The repair pass below always resyncs every ACTIVE
        # membership, since other permission facets (e.g. stale moderator
        # perms) can be out of sync even when enrollment itself is fine.
        enrollment_drifted_ids = set(
            active_memberships.exclude(
                user__groups=F("group__perms_group")
            ).values_list("pk", flat=True)
        )

        scanned_count = 0
        repaired_count = 0
        skipped_count = 0
        failed_count = 0

        for membership in active_memberships.iterator():
            scanned_count += 1
            if membership.pk in enrollment_drifted_ids:
                self.stdout.write(
                    f"Missing perms_group enrollment: user={membership.user} "
                    f"group={membership.group}"
                )
            if dry_run:
                continue

            try:
                resynced = self._repair_membership(membership.pk)
            except Exception as e:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to resync membership user={membership.user} "
                        f"group={membership.group}: {e}"
                    )
                )
                continue

            if resynced:
                repaired_count += 1
            else:
                skipped_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(enrollment_drifted_ids)} of {scanned_count} active "
                    f"membership(s) missing perms_group enrollment (dry run)."
                )
            )
            return

        summary = (
            f"Resynced {repaired_count} of {scanned_count} active "
            f"membership(s) ({len(enrollment_drifted_ids)} were missing "
            f"perms_group enrollment)"
        )
        if skipped_count:
            summary += f", {skipped_count} skipped (no longer active)"
        if failed_count:
            summary += f", {failed_count} failed"
        summary += "."
        self.stdout.write(
            (self.style.ERROR if failed_count else self.style.SUCCESS)(summary)
        )

    def _repair_membership(self, membership_id: int) -> bool:
        """
        Re-fetch and lock the membership immediately before resyncing its
        permissions, using freshly-locked state rather than the row read
        during the initial scan. Guards against a concurrent status change
        (e.g. the user leaving the group) landing between scan and repair
        during a long-running pass; returns False without making changes
        if the membership is no longer eligible.

        Deliberately calls sync_membership_permissions() rather than
        membership.save() — resyncing permissions during a backend data
        repair should not re-dispatch Membership's other post_save
        receivers (e.g. membership-lifecycle notifications).
        """
        with transaction.atomic():
            membership = (
                Membership.objects.select_for_update()
                .select_related("group__perms_group", "user")
                .get(pk=membership_id)
            )
            if (
                membership.status != MembershipStatus.ACTIVE
                or membership.group.perms_group is None
            ):
                return False
            sync_membership_permissions(membership)
            return True
