from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class GroupPermissionTests(TestCase):
    member_perms = ["view_this_group"]
    moderator_perms = [
        "view_this_group",
        "edit_this_group",
        "delete_this_group",
    ]
    # Interesting to reflect that ultimately, owners are no more
    # special than moderators.
    owner_perms = moderator_perms

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )

    def test_group_owner_can_view_edit_delete(self) -> None:
        # Arrange
        owner = self.owner

        # Act
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )

        # Assert
        self.assertTrue(owner.has_perm("view_this_group", group))
        self.assertTrue(owner.has_perm("edit_this_group", group))
        self.assertTrue(owner.has_perm("delete_this_group", group))

    def test_group_member_can_view_only(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        # Act
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)

        # Assert
        self.assertTrue(member.has_perm("view_this_group", group))
        self.assertFalse(member.has_perm("edit_this_group", group))
        self.assertFalse(member.has_perm("delete_this_group", group))

    def test_group_moderator_can_view_edit_delete(self) -> None:
        # Arrange
        ## An extra user this time, to be a moderator
        owner = self.owner
        member = self.member
        moderator = BorrowdUser.objects.create(
            username="moderator", email="moderator@domain.com"
        )

        # Act
        ## Note the `is_moderator` settings
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)
        group.add_user(moderator, trust_level=TrustLevel.LOW, is_moderator=True)

        # Assert
        self.assertTrue(owner.has_perm("view_this_group", group))
        self.assertTrue(owner.has_perm("edit_this_group", group))
        self.assertTrue(owner.has_perm("delete_this_group", group))
        self.assertTrue(member.has_perm("view_this_group", group))
        self.assertFalse(member.has_perm("edit_this_group", group))
        self.assertFalse(member.has_perm("delete_this_group", group))
        self.assertTrue(moderator.has_perm("view_this_group", group))
        self.assertTrue(moderator.has_perm("edit_this_group", group))
        self.assertTrue(moderator.has_perm("delete_this_group", group))

    def test_moderator_permissions_are_removed_when_user_is_no_longer_moderator(
        self,
    ) -> None:
        # Arrange
        owner = self.owner
        moderator = self.member

        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        group.add_user(moderator, trust_level=TrustLevel.LOW, is_moderator=True)

        ## Check initial permissions
        self.assertTrue(moderator.has_perm("edit_this_group", group))

        # Act
        group.update_user_membership(moderator, is_moderator=False)

        # Assert
        self.assertFalse(moderator.has_perm("edit_this_group", group))

    def test_member_permissions_are_removed_when_user_is_removed_from_group(
        self,
    ) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)

        ## Check initial permissions
        self.assertTrue(member.has_perm("view_this_group", group))

        # Act
        group.remove_user(member)

        # Assert
        self.assertFalse(member.has_perm("view_this_group", group))
