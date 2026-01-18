from django.contrib.auth.models import Group
from django.test import TestCase
from guardian.shortcuts import get_perms

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item
from borrowd_permissions.models import ItemOLP
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
        self.assertTrue(owner.has_perm(ItemOLP.VIEW, item))

    def test_owners_have_automatic_membership_to_groups_they_create(self) -> None:
        # Arrange
        owner = self.owner
        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )

        ## Owner creates an Item
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Create another user who is a member of the Group
        member = self.member
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

    def test_item_visible_to_group_members_on_item_creation(self) -> None:
        # Arrange
        owner = self.owner
        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )

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
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

    def test_item_visible_to_group_members_on_joining_group(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

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
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
            membership_requires_approval=False,
        )

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.HIGH)

        # Assert
        ## Member should not be able to see Item,
        ## because Item requires a High trust level,
        ## and Owner only has Low trust with this group.
        self.assertFalse(member.has_perm(ItemOLP.VIEW, item))

    def test_item_not_visible_to_group_members_on_leaving_group(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Create another user who is a member of the group
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group member can see the item
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

        group.remove_user(member)
        ## Check if the group member can still see the item
        self.assertFalse(member.has_perm(ItemOLP.VIEW, item))

    def test_item_not_visible_to_group_owner_on_leaving_group(self) -> None:
        # Arrange
        moderator = self.owner
        member = self.member

        ## Create a group
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=moderator, updated_by=moderator
        )

        ## Create an item, owned by *Member*
        item = Item.objects.create(
            name="Test Item", owner=member, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Add the member to the group
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Assert
        ## Check if the group Moderator can see the item
        self.assertTrue(moderator.has_perm(ItemOLP.VIEW, item))

        ## Remove the member from the group
        group.remove_user(member)

        ## Confirm the group Moderator can no longer see the item
        self.assertFalse(moderator.has_perm(ItemOLP.VIEW, item))

    def test_item_not_visible_to_non_members(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member
        non_member = BorrowdUser.objects.create(
            username="non_member", email="non-member@example.com"
        )

        ## Create a group and add the owner to it
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

        ## Create an item and assign it to the owner
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Act
        ## Do not add the non_member to the group

        # Assert
        ## Check if the non-member cannot see the item
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))
        self.assertFalse(non_member.has_perm(ItemOLP.VIEW, item))

    def test_item_visible_to_groups_with_higher_trust_level(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        borrowd_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        perms_group = Group.objects.get(name=borrowd_group.name)

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
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item1))
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item2))
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item3))

    def test_item_not_visible_to_groups_with_lower_trust_level(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        borrowd_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        perms_group = Group.objects.get(name=borrowd_group.name)

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
        ## Check the group can only see item1, since it only has a LOW trust level
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item1))
        self.assertFalse(ItemOLP.VIEW in get_perms(perms_group, item2))
        self.assertFalse(ItemOLP.VIEW in get_perms(perms_group, item3))

    def test_item_visibility_revoked_when_group_trust_lowered(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        borrowd_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group", created_by=owner, updated_by=owner
        )
        perms_group = Group.objects.get(name=borrowd_group.name)

        ## Create an item with a HIGH trust level
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert initial visibility
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item))

        # Act
        ## Lower the group's trust level
        borrowd_group.update_user_membership(owner, TrustLevel.LOW)

        # Assert
        ## Check that the group can no longer see the item
        self.assertFalse(ItemOLP.VIEW in get_perms(perms_group, item))

    def test_item_visibility_granted_when_group_trust_raised(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group and add the owner to it with a HIGH trust level
        borrowd_group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )
        perms_group = Group.objects.get(name=borrowd_group.name)

        ## Create an item with a HIGH trust level
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.HIGH
        )

        # Assert initial visibility
        self.assertFalse(ItemOLP.VIEW in get_perms(perms_group, item))

        # Act
        ## Raise the group's trust level
        borrowd_group.update_user_membership(owner, TrustLevel.HIGH)

        # Assert
        ## Check that the group can no longer see the item
        self.assertTrue(ItemOLP.VIEW in get_perms(perms_group, item))

    def test_item_visibility_revoked_when_group_deleted(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the member
        group: BorrowdGroup = BorrowdGroup.objects.create(
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

        ## Create an item
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Assert initial visibility
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

        # Act
        ## Delete the group
        group.delete()

        # Assert
        ## Check that the erstwhile group member can no longer see the item
        self.assertFalse(member.has_perm(ItemOLP.VIEW, item))

    def test_item_owner_still_sees_item_when_group_deleted(self) -> None:
        # Arrange
        owner = self.owner

        ## Create a group (owner is automatically a member)
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )

        ## Create an item
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Assert initial visibility
        self.assertTrue(owner.has_perm(ItemOLP.VIEW, item))

        # Act
        ## Delete the group
        group.delete()

        # Assert
        ## Check that the erstwhile group member can no longer see the item
        self.assertTrue(owner.has_perm(ItemOLP.VIEW, item))

    def test_item_still_visible_if_another_group_remains(self) -> None:
        # Arrange
        owner = self.owner
        member = self.member

        ## Create a group and add the member
        group1: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group1",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group1.add_user(member, trust_level=TrustLevel.LOW)

        ## Same again with another group
        group2: BorrowdGroup = BorrowdGroup.objects.create(
            name="Test Group2",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group2.add_user(member, trust_level=TrustLevel.LOW)

        ## Create an item
        item = Item.objects.create(
            name="Test Item", owner=owner, trust_level_required=TrustLevel.LOW
        )

        # Assert initial visibility
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))

        # Act
        ## Delete the group
        group1.delete()

        # Assert
        ## Member should still be able to see the item
        ## because of group2
        self.assertTrue(member.has_perm(ItemOLP.VIEW, item))
        self.assertTrue(
            ItemOLP.VIEW in get_perms(Group.objects.get(name=group2.name), item)
        )
