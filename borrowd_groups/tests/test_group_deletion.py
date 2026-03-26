from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_users.models import BorrowdUser


class GroupDeletionTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", password="password"
        )
        self.member = BorrowdUser.objects.create_user(
            username="member", password="password"
        )

    def test_deleting_group_removes_linked_perms_group(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Delete Me",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        group.add_user(self.member, trust_level=TrustLevel.STANDARD)
        perms_group_id = group.perms_group.pk
        group_id = group.pk

        group.delete()

        self.assertFalse(BorrowdGroup.objects.filter(pk=group_id).exists())
        self.assertFalse(Membership.objects.filter(group_id=group_id).exists())
        self.assertFalse(Group.objects.filter(pk=perms_group_id).exists())

    def test_delete_view_removes_group_and_linked_perms_group(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Delete Via View",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        perms_group_id = group.perms_group.pk

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("borrowd_groups:group-delete", args=[group.pk])
        )

        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(BorrowdGroup.objects.filter(pk=group.pk).exists())
        self.assertFalse(Group.objects.filter(pk=perms_group_id).exists())

    def test_can_create_new_group_with_same_name_after_deletion(self) -> None:
        original_group = BorrowdGroup.objects.create(
            name="Reusable Name",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        original_perms_group_id = original_group.perms_group.pk

        original_group.delete()

        replacement_group = BorrowdGroup.objects.create(
            name="Reusable Name",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )

        self.assertFalse(Group.objects.filter(pk=original_perms_group_id).exists())
        self.assertEqual(replacement_group.name, "Reusable Name")
        self.assertIsNotNone(replacement_group.perms_group.pk)
        self.assertNotEqual(replacement_group.perms_group.pk, original_perms_group_id)
        self.assertTrue(
            Group.objects.filter(pk=replacement_group.perms_group.pk).exists()
        )
