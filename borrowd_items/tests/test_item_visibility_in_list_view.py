from django.test import RequestFactory, TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Item
from borrowd_items.views import ItemListView
from borrowd_users.models import BorrowdUser


class ItemListViewVisibilityTests(TestCase):
    def setUp(self) -> None:
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.factory = RequestFactory()

    def test_list_own_items(self) -> None:
        """
        `owner` should see their own items in the ItemListView.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner

        ## Create Item
        item1 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item2 = Item.objects.create(
            name="Item 2",
            description="Description 2",
            owner=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        ## Create Group and add member (owner is in by default)
        BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )

        ## Preare the request
        request = self.factory.get("/items/")
        request.user = owner

        #
        # Act
        #
        response = ItemListView.as_view()(request)
        items = response.context_data["item_list"]

        #
        #  Assert
        #
        self.assertEqual(len(items), 2)
        self.assertIn(item1, items)
        self.assertIn(item2, items)

    def test_list_items_from_group_membership(self) -> None:
        """
        `owner` has one item, `member` is in a group with `owner`,
        therefore `member` should see `owner`'s item in the
        ItemListView.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Item
        item1 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        ## Create Group and add member (owner is in by default)
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        ## Preare the request
        request = self.factory.get("/items/")
        request.user = member

        #
        # Act
        #
        response = ItemListView.as_view()(request)
        items = response.context_data["item_list"]

        #
        #  Assert
        #
        self.assertIn(item1, items)
        self.assertEqual(len(items), 1)

    def test_list_mix_of_own_and_group_items(self) -> None:
        """
        `owner` has one item, `member` has one item, both share a
        group, so each should be able to see two items in the
        ItemListView.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Item
        item1 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item2 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=member,
            trust_level_required=TrustLevel.STANDARD,
        )

        ## Create Group and add member (owner is in by default)
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        ## Preare the request
        request_owner = self.factory.get("/items/")
        request_owner.user = owner

        request_member = self.factory.get("/items/")
        request_member.user = member

        #
        # Act
        #
        response_owner = ItemListView.as_view()(request_owner)
        items_owner = response_owner.context_data["item_list"]

        response_member = ItemListView.as_view()(request_member)
        items_member = response_member.context_data["item_list"]

        #
        #  Assert
        #
        self.assertEqual(len(items_owner), 2)
        self.assertIn(item1, items_owner)
        self.assertIn(item2, items_owner)

        self.assertEqual(len(items_member), 2)
        self.assertIn(item1, items_member)
        self.assertIn(item2, items_member)

    def test_list_items_from_group_membership_with_different_trust_level(self) -> None:
        """
        `owner` has one High trust item and one Standard trust item, is in
        a Standard trust group with `member`, therefore `member` should
        only see the Standard trust item in the ItemListView.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Item
        item_high = Item.objects.create(
            name="Item High",
            description="Description High",
            owner=owner,
            trust_level_required=TrustLevel.HIGH,
        )
        item_low = Item.objects.create(
            name="Item Low",
            description="Description Low",
            owner=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        ## Create Group and add member (owner is in by default)
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
        ## Member trusts the group a lot, although that doesn't matter
        ## for the purposes of this test.
        group.add_user(member, trust_level=TrustLevel.HIGH)

        ## Preare the request
        request = self.factory.get("/items/")
        request.user = member

        #
        # Act
        #
        response = ItemListView.as_view()(request)
        items = response.context_data["item_list"]

        #
        #  Assert
        #
        self.assertEqual(len(items), 1)
        self.assertIn(item_low, items)
        self.assertNotIn(item_high, items)

    def test_removed_member_loses_access_to_group_items(self) -> None:
        """
        `member` is removed from `group`, therefore `member` should no longer
        see items owned by `owner` in the ItemListView.
        """
        owner = self.owner
        member = self.member

        item = Item.objects.create(
            name="Owner Item",
            description="Owned by group owner.",
            owner=owner,
            trust_level_required=TrustLevel.LOW,
        )

        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Confirm access before removal
        request = self.factory.get("/items/")
        request.user = member
        items_before = ItemListView.as_view()(request).context_data["item_list"]
        self.assertIn(item, items_before)

        # Remove via the model method
        group.remove_user(member)

        # Access must be revoked
        request = self.factory.get("/items/")
        request.user = member
        items_after = ItemListView.as_view()(request).context_data["item_list"]
        self.assertNotIn(item, items_after)
        self.assertEqual(len(items_after), 0)

    def test_direct_membership_deletion_revokes_access_to_group_items(self) -> None:
        """
        `member` is removed from `group` via `membership.delete()`,
        therefore `member` should no longer see items owned by `owner`
        in the ItemListView.
        """
        owner = self.owner
        member = self.member

        item = Item.objects.create(
            name="Owner Item",
            description="Owned by group owner.",
            owner=owner,
            trust_level_required=TrustLevel.LOW,
        )

        group = BorrowdGroup.objects.create(
            name="Test Group 2",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW, is_moderator=True)

        # Confirm access before removal
        request = self.factory.get("/items/")
        request.user = member
        items_before = ItemListView.as_view()(request).context_data["item_list"]
        self.assertIn(item, items_before)

        # Delete the Membership directly, bypassing group.remove_user()
        Membership.objects.get(user=member, group=group).delete()

        # Access must still be revoked via the pre_delete signal
        request = self.factory.get("/items/")
        request.user = member
        items_after = ItemListView.as_view()(request).context_data["item_list"]
        self.assertNotIn(item, items_after)
        self.assertEqual(len(items_after), 0)
