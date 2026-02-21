from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_permissions.models import BorrowdGroupOLP
from borrowd_users.models import BorrowdUser


class GroupPermissionTests(TestCase):
    member_perms = [BorrowdGroupOLP.VIEW]
    moderator_perms = [
        BorrowdGroupOLP.VIEW,
        BorrowdGroupOLP.EDIT,
        BorrowdGroupOLP.DELETE,
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
            membership_requires_approval=False,
        )

        # Assert
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.DELETE, group))

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
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)

        # Assert
        self.assertTrue(member.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertFalse(member.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertFalse(member.has_perm(BorrowdGroupOLP.DELETE, group))

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
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)
        group.add_user(moderator, trust_level=TrustLevel.LOW, is_moderator=True)

        # Assert
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertTrue(owner.has_perm(BorrowdGroupOLP.DELETE, group))
        self.assertTrue(member.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertFalse(member.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertFalse(member.has_perm(BorrowdGroupOLP.DELETE, group))
        self.assertTrue(moderator.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertTrue(moderator.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertTrue(moderator.has_perm(BorrowdGroupOLP.DELETE, group))

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
            membership_requires_approval=False,
        )
        group.add_user(moderator, trust_level=TrustLevel.LOW, is_moderator=True)

        ## Check initial permissions
        self.assertTrue(moderator.has_perm(BorrowdGroupOLP.EDIT, group))

        # Act
        group.update_user_membership(moderator, is_moderator=False)

        # Assert
        self.assertFalse(moderator.has_perm(BorrowdGroupOLP.EDIT, group))

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
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=False)

        ## Check initial permissions
        self.assertTrue(member.has_perm(BorrowdGroupOLP.VIEW, group))

        # Act
        group.remove_user(member)

        # Assert
        self.assertFalse(member.has_perm(BorrowdGroupOLP.VIEW, group))
