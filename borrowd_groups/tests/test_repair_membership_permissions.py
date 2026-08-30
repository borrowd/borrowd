from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from borrowd_groups.models import BorrowdGroup
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

    def _drift_membership(self) -> None:
        """
        Simulate the symptom left behind by migrations 0008/0009: an ACTIVE
        Membership whose user was never enrolled in the group's perms_group,
        because the post_save signal never dispatched (there, because the
        .save() ran against a historical model; here, reproduced directly).
        """
        self.member.groups.remove(self.perms_group)

    def test_command_detects_and_repairs_drifted_membership(self) -> None:
        self._drift_membership()
        self.assertFalse(self.member.groups.filter(pk=self.perms_group.pk).exists())

        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("1 drifted membership(s) repaired", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_dry_run_reports_without_repairing(self) -> None:
        self._drift_membership()

        out = StringIO()
        call_command("repair_membership_permissions", "--dry-run", stdout=out)

        self.assertIn("1 drifted membership(s) found", out.getvalue())
        self.assertFalse(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_healthy_data_is_a_no_op(self) -> None:
        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("0 drifted membership(s) repaired", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())

    def test_rerun_after_repair_is_idempotent(self) -> None:
        self._drift_membership()
        call_command("repair_membership_permissions", stdout=StringIO())

        out = StringIO()
        call_command("repair_membership_permissions", stdout=out)

        self.assertIn("0 drifted membership(s) repaired", out.getvalue())
        self.assertTrue(self.member.groups.filter(pk=self.perms_group.pk).exists())
