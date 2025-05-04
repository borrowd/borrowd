from django.test import TestCase
from guardian.shortcuts import get_perms

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser


class GroupBasedItemPermissionsTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )

    def test_item_visible_to_owner(self) -> None:
        # Act
        owner = self.owner
        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Assert
        ## Check if the owner can see the item
        self.assertTrue(owner.has_perm("view_this_item", item))

    def test_owners_require_membership_to_groups_they_create(self) -> None:
        # Arrange
        owner = self.owner
        ## Create a group and add the owner to it
        # Not sure why mypy complains here; intellisense seems able
        # to infer the output of BorrowdGroup.create() correctly.
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]

        ## Owner creates an Item
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        ## Create another user who is a member of the Group
        member = self.member
        group.add_user(member, trust_level=TrustLevel.LOW)

        ## Check initial state: "member" cannot see owner's Item,
        ## because owner is not yet a Member of the Group.
        self.assertFalse(member.has_perm("view_this_item", item))

        # Act
        ## Create an item and assign it to the owner
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm("view_this_item", item))

    def test_item_visible_to_group_members_on_item_creation(self) -> None:
        # Arrange
        owner = self.owner
        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        ## Create another user who is a member of the group
        member = self.member
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Act
        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm("view_this_item", item))

    def test_item_visible_to_group_members_on_joining_group(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm("view_this_item", item))

    def test_item_not_visible_to_group_with_lower_trust_on_joining_group(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.LOW)

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.HIGH)

        # Assert
        ## Member should not be able to see Item,
        ## because Item requires a High trust level,
        ## and Owner only has Low trust with this group.
        self.assertFalse(member.has_perm("view_this_item", item))

    def test_item_not_visible_to_group_members_on_leaving_group(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm("view_this_item", item))

        group.remove_user(member)
        ## Check if the group member can still see the item
        self.assertFalse(member.has_perm("view_this_item", item))

    def test_item_not_visible_to_non_members(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member
        non_member = BorrowdUser.objects.create(
            username="non_member", email="non-member@example.com"
        )

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)
        group.add_user(member, trust_level=TrustLevel.LOW)

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Do not add the non_member to the group

        # Assert
        ## Check if the non-member cannot see the item
        self.assertTrue(member.has_perm("view_this_item", item))
        self.assertFalse(non_member.has_perm("view_this_item", item))

    def test_item_visible_to_groups_with_higher_trust_level(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        # Act
        ## Create an Items with low, med and high levels
        item1 = Item.objects.create(
            name="Test Item 1", owner=owner, trust_level_required=TrustLevel.LOW
        )
        item2 = Item.objects.create(
            name="Test Item 2", owner=owner, trust_level_required=TrustLevel.MEDIUM
        )
        item3 = Item.objects.create(
            name="Test Item 3", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert
        ## Check the group can see all three of these Items, given its High trust level
        self.assertTrue("view_this_item" in get_perms(group, item1))
        self.assertTrue("view_this_item" in get_perms(group, item2))
        self.assertTrue("view_this_item" in get_perms(group, item3))

    def test_item_not_visible_to_groups_with_lower_trust_level(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.LOW)

        # Act
        ## Create an Items with low, med and high levels
        item1 = Item.objects.create(
            name="Test Item 1", owner=owner, trust_level_required=TrustLevel.LOW
        )
        item2 = Item.objects.create(
            name="Test Item 2", owner=owner, trust_level_required=TrustLevel.MEDIUM
        )
        item3 = Item.objects.create(
            name="Test Item 3", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert
        ## Check the group can see all three of these Items, given its High trust level
        self.assertTrue("view_this_item" in get_perms(group, item1))
        self.assertFalse("view_this_item" in get_perms(group, item2))
        self.assertFalse("view_this_item" in get_perms(group, item3))

    def test_item_visibility_revoked_when_group_trust_lowered(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.HIGH)

        ## Create an item with a HIGH trust level
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert initial visibility
        self.assertTrue("view_this_item" in get_perms(group, item))

        # Act
        ## Lower the group's trust level
        group.update_user_membership(owner, TrustLevel.LOW)

        # Assert
        ## Check that the group can no longer see the item
        self.assertFalse("view_this_item" in get_perms(group, item))

    def test_item_visibility_granted_when_group_trust_raised(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )  # type: ignore[assignment]
        group.add_user(owner, trust_level=TrustLevel.LOW)

        ## Create an item with a HIGH trust level
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert initial visibility
        self.assertFalse("view_this_item" in get_perms(group, item))

        # Act
        ## Raise the group's trust level
        group.update_user_membership(owner, TrustLevel.HIGH)

        # Assert
        ## Check that the group can no longer see the item
        self.assertTrue("view_this_item" in get_perms(group, item))
