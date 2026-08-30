from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from borrowd_groups.management.commands.repair_membership_permissions import (
    Command,
)
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_groups.signals import sync_membership_permissions
from borrowd_users.models import BorrowdUser


class RepairMembershipPermissionsTests(TestCase):
    def setUp(self) -> None:
        self.creator = BorrowdUser.objects.create_user(
            username="creator", password="password1"
        )
        self.member = BorrowdUser.objects.create_user(
            username="member", password="password2"
        )
        self.group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=False,
        )
        self.group.add_user(self.member)
        assert self.group.perms_group is not None
        self.perms_group = self.group.perms_group

    def _drift_membership(self, user: BorrowdUser | None = None) -> None:
        """
        Simulate the symptom left behind when a Membership is saved through
        a historical model class (e.g. from a data migration's
        apps.get_model()): an ACTIVE Membership whose user was never
        enrolled in the group's perms_group, because the post_save signal
        never dispatched. Reproduced directly here rather than via an
        actual migration.
        """
        (user or self.member).groups.remove(self.perms_group)

    def test_command_detects_and_repairs_drifted_membership(self) -> None:
        self._drift_membership()
        self.assertFalse(self.member.groups.filter(pk=self.perms_group.pk).exists())

        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("Resynced 2 of 2 active membership(s)", out.getvalue())
        self.assertIn("1 were missing perms_group enrollment", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_dry_run_reports_without_repairing(self) -> None:
        self._drift_membership()

        out = StringIO()
        call_command("repair_membership_permissions", "--dry-run", stdout=out)

        self.assertIn("1 of 2 active membership(s) missing", out.getvalue())
        self.assertFalse(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_healthy_data_is_resynced_with_no_drift_reported(self) -> None:
        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("Resynced 2 of 2 active membership(s)", out.getvalue())
        self.assertIn("0 were missing perms_group enrollment", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_rerun_after_repair_is_idempotent(self) -> None:
        self._drift_membership()
        call_command("repair_membership_permissions", stdout=StringIO())

        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("Resynced 2 of 2 active membership(s)", out.getvalue())
        self.assertIn("0 were missing perms_group enrollment", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_resyncs_stale_moderator_permissions_even_without_enrollment_drift(
        self,
    ) -> None:
        """
        A membership can be fully enrolled in perms_group yet still have
        stale BorrowdGroupOLP moderator permissions (e.g. is_moderator was
        toggled through a historical-model .save() that skipped the
        signal). The narrow enrollment check alone would never flag or fix
        this row; the unconditional resync must.
        """
        from guardian.shortcuts import get_perms

        from borrowd_permissions.models import BorrowdGroupOLP

        membership = self.group.membership_set.get(user=self.member)
        Membership.objects.filter(pk=membership.pk).update(is_moderator=True)
        self.assertNotIn(BorrowdGroupOLP.EDIT, get_perms(self.member, self.group))

        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("0 were missing perms_group enrollment", out.getvalue())
        self.assertIn(BorrowdGroupOLP.EDIT, get_perms(self.member, self.group))

    def test_summary_reflects_partial_failure_not_full_success(self) -> None:
        other_member = BorrowdUser.objects.create_user(
            username="other_member", password="password3"
        )
        self.group.add_user(other_member)
        self._drift_membership(self.member)
        self._drift_membership(other_member)

        def side_effect(membership: Membership) -> None:
            if membership.user == other_member:
                raise RuntimeError("simulated repair failure")
            sync_membership_permissions(membership)

        out = StringIO()
        with patch(
            "borrowd_groups.management.commands.repair_membership_permissions"
            ".sync_membership_permissions",
            side_effect=side_effect,
        ):
            call_command("repair_membership_permissions", stdout=out, stderr=StringIO())

        # One of three active rows failed to resync — the summary must not
        # claim full success, and the failed row must stay drifted.
        self.assertIn("Resynced 2 of 3 active membership(s)", out.getvalue())
        self.assertIn("1 failed", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())
        self.assertFalse(other_member.groups.filter(pk=self.perms_group.pk).exists())

    def test_repair_membership_skips_when_no_longer_active(self) -> None:
        """
        Directly exercises the lock-and-recheck guard: if a membership's
        status changed to non-ACTIVE between the initial scan and the
        repair acquiring its row lock (e.g. the user left the group
        concurrently), it must not re-apply ACTIVE-membership permissions.
        """
        membership = self.group.membership_set.get(user=self.member)

        # Simulate a concurrent status change landing before the repair's own lock.
        Membership.objects.filter(pk=membership.pk).update(
            status=MembershipStatus.ENDED
        )

        resynced = Command()._repair_membership(membership.pk)

        self.assertFalse(resynced)

    def test_repair_membership_skips_when_deleted_concurrently(self) -> None:
        """
        If a membership is hard-deleted (e.g. via the leave-group flow)
        between the initial scan and the repair acquiring its row lock,
        the benign DoesNotExist race must be treated as "nothing to
        repair", not reported as a repair failure.
        """
        membership = self.group.membership_set.get(user=self.member)
        membership_id = membership.pk
        membership.delete()

        resynced = Command()._repair_membership(membership_id)

        self.assertFalse(resynced)
