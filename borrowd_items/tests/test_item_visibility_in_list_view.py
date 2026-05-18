from django.http import Http404
from django.test import RequestFactory, TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item
from borrowd_items.views import ItemDetailView, ItemListView
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
        self.assertEqual(len(items), 0)  # this view does not show the owner's items

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
            created_by=owner,
            updated_by=owner,
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
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item2 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=member,
            created_by=member,
            updated_by=member,
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
        self.assertEqual(
            len(items_owner), 1
        )  # this should not show the owner's own item
        self.assertNotIn(item1, items_owner)
        self.assertIn(item2, items_owner)

        self.assertEqual(
            len(items_member), 1
        )  # this should not show the member's own item
        self.assertIn(item1, items_member)
        self.assertNotIn(item2, items_member)

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
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.HIGH,
        )
        item_low = Item.objects.create(
            name="Item Low",
            description="Description Low",
            owner=owner,
            created_by=owner,
            updated_by=owner,
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
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

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
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        group = BorrowdGroup.objects.create(
            name="Test Group 2",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD, is_moderator=True)

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

    def test_pending_member_cannot_see_active_members_group_items(self) -> None:
        """
        A pending member should not inherit item visibility from a group
        until their membership is approved.
        """
        owner = self.owner
        pending_member = self.member

        visible_to_active_members = Item.objects.create(
            name="Active Member Item",
            description="Should stay hidden from pending members.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        group = BorrowdGroup.objects.create(
            name="Approval Required Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=True,
        )
        membership = group.add_user(
            pending_member,
            trust_level=TrustLevel.STANDARD,
        )

        request = self.factory.get("/items/")
        request.user = pending_member
        items = ItemListView.as_view()(request).context_data["item_list"]

        self.assertEqual(membership.status, MembershipStatus.PENDING)
        self.assertNotIn(visible_to_active_members, items)
        self.assertEqual(len(items), 0)

    def test_active_member_cannot_see_pending_members_items(self) -> None:
        """
        Items posted by a pending member should not become visible to active
        members of the group.
        """
        active_member = self.owner
        pending_member = self.member

        group = BorrowdGroup.objects.create(
            name="Pending Owner Group",
            created_by=active_member,
            updated_by=active_member,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=True,
        )
        membership = group.add_user(
            pending_member,
            trust_level=TrustLevel.STANDARD,
        )
        pending_members_item = Item.objects.create(
            name="Pending Member Item",
            description="Should stay hidden until approval.",
            owner=pending_member,
            created_by=pending_member,
            updated_by=pending_member,
            trust_level_required=TrustLevel.STANDARD,
        )

        request = self.factory.get("/items/")
        request.user = active_member
        items = ItemListView.as_view()(request).context_data["item_list"]

        self.assertEqual(membership.status, MembershipStatus.PENDING)
        self.assertNotIn(pending_members_item, items)
        self.assertEqual(len(items), 0)

    def test_group_creator_sees_members_item_when_member_joins_first(self) -> None:
        """
        A group creator should see an item posted by an active member
        when that member joined before creating the item.
        """
        creator = self.owner
        member = self.member

        group = BorrowdGroup.objects.create(
            name="Join First Group",
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        member_item = Item.objects.create(
            name="Member Item",
            description="Created after joining the group.",
            owner=member,
            created_by=member,
            updated_by=member,
            trust_level_required=TrustLevel.STANDARD,
        )

        request = self.factory.get("/items/")
        request.user = creator
        items = ItemListView.as_view()(request).context_data["item_list"]

        self.assertIn(member_item, items)

    def test_members_see_each_others_items_when_both_joined_first(self) -> None:
        """
        Active members in the same group should see each other's items
        when both items are created after joining.
        """
        creator = self.owner
        member_b = self.member
        member_c = BorrowdUser.objects.create(
            username="member_c", email="member_c@example.com"
        )

        group = BorrowdGroup.objects.create(
            name="Three Member Group",
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member_b, trust_level=TrustLevel.STANDARD)
        group.add_user(member_c, trust_level=TrustLevel.STANDARD)

        item_b = Item.objects.create(
            name="Item B",
            description="Owned by member B.",
            owner=member_b,
            created_by=member_b,
            updated_by=member_b,
            trust_level_required=TrustLevel.STANDARD,
        )
        item_c = Item.objects.create(
            name="Item C",
            description="Owned by member C.",
            owner=member_c,
            created_by=member_c,
            updated_by=member_c,
            trust_level_required=TrustLevel.STANDARD,
        )

        request_for_b = self.factory.get("/items/")
        request_for_b.user = member_b
        items_for_b = ItemListView.as_view()(request_for_b).context_data["item_list"]

        request_for_c = self.factory.get("/items/")
        request_for_c.user = member_c
        items_for_c = ItemListView.as_view()(request_for_c).context_data["item_list"]

        self.assertIn(item_c, items_for_b)
        self.assertIn(item_b, items_for_c)

    def test_group_creator_can_open_member_item_detail_when_member_joins_first(
        self,
    ) -> None:
        """
        A group creator should be able to open item detail pages for active
        members' items created after joining.
        """
        creator = self.owner
        member = self.member

        group = BorrowdGroup.objects.create(
            name="Detail Visibility Group",
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        member_item = Item.objects.create(
            name="Detail Member Item",
            description="Detail page should be visible to creator.",
            owner=member,
            created_by=member,
            updated_by=member,
            trust_level_required=TrustLevel.STANDARD,
        )

        request = self.factory.get(f"/items/{member_item.pk}/")
        request.user = creator

        try:
            response = ItemDetailView.as_view()(request, pk=member_item.pk)
        except Http404:
            self.fail("Group creator should be able to view member item detail page")

        self.assertEqual(response.status_code, 200)

    def test_creator_loses_visibility_when_member_raises_item_trust_requirement(
        self,
    ) -> None:
        """
        When a member raises an item's trust requirement above their own
        trust level for the group, active group peers should lose access.
        """
        creator = self.owner
        member = self.member

        group = BorrowdGroup.objects.create(
            name="Trust Raise Group",
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        member_item = Item.objects.create(
            name="Trust Raise Item",
            description="Starts visible at STANDARD.",
            owner=member,
            created_by=member,
            updated_by=member,
            trust_level_required=TrustLevel.STANDARD,
        )

        request_before = self.factory.get("/items/")
        request_before.user = creator
        items_before = ItemListView.as_view()(request_before).context_data["item_list"]
        self.assertIn(member_item, items_before)

        member_item.trust_level_required = TrustLevel.HIGH
        member_item.updated_by = member
        member_item.save()

        request_after = self.factory.get("/items/")
        request_after.user = creator
        items_after = ItemListView.as_view()(request_after).context_data["item_list"]
        self.assertNotIn(member_item, items_after)

    def test_creator_gains_visibility_when_member_lowers_item_trust_requirement(
        self,
    ) -> None:
        """
        When a member lowers an item's trust requirement to match their
        trust level for the group, active group peers should gain access.
        """
        creator = self.owner
        member = self.member

        group = BorrowdGroup.objects.create(
            name="Trust Lower Group",
            created_by=creator,
            updated_by=creator,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        member_item = Item.objects.create(
            name="Trust Lower Item",
            description="Starts hidden at HIGH.",
            owner=member,
            created_by=member,
            updated_by=member,
            trust_level_required=TrustLevel.HIGH,
        )

        request_before = self.factory.get("/items/")
        request_before.user = creator
        items_before = ItemListView.as_view()(request_before).context_data["item_list"]
        self.assertNotIn(member_item, items_before)

        member_item.trust_level_required = TrustLevel.STANDARD
        member_item.updated_by = member
        member_item.save()

        request_after = self.factory.get("/items/")
        request_after.user = creator
        items_after = ItemListView.as_view()(request_after).context_data["item_list"]
        self.assertIn(member_item, items_after)

    def test_member_cannot_open_item_detail_after_leaving_group(self) -> None:
        """
        A user who leaves a shared group should no longer be able to open
        detail pages for items shared only through that group.
        """
        owner = self.owner
        member = self.member

        group = BorrowdGroup.objects.create(
            name="Leave Detail Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.STANDARD)

        item = Item.objects.create(
            name="Leave Detail Item",
            description="Only visible through shared group membership.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        group.remove_user(member)

        request = self.factory.get(f"/items/{item.pk}/")
        request.user = member

        with self.assertRaises(Http404):
            ItemDetailView.as_view()(request, pk=item.pk)

    def test_member_keeps_item_detail_access_with_another_shared_group(self) -> None:
        """
        Leaving one shared group should not remove item detail visibility
        when another shared group still grants access.
        """
        owner = self.owner
        member = self.member

        group_one = BorrowdGroup.objects.create(
            name="Primary Shared Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group_one.add_user(member, trust_level=TrustLevel.STANDARD)

        group_two = BorrowdGroup.objects.create(
            name="Secondary Shared Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        group_two.add_user(member, trust_level=TrustLevel.STANDARD)

        item = Item.objects.create(
            name="Still Shared Item",
            description="Should remain visible through second group.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            trust_level_required=TrustLevel.STANDARD,
        )

        group_one.remove_user(member)

        request = self.factory.get(f"/items/{item.pk}/")
        request.user = member
        response = ItemDetailView.as_view()(request, pk=item.pk)

        self.assertEqual(response.status_code, 200)
