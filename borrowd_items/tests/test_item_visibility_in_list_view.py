from django.http import Http404
from django.test import RequestFactory, TestCase

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
        BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
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
        )

        ## Create Group and add member (owner is in by default)
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)

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
        )
        item2 = Item.objects.create(
            name="Item 1",
            description="Description 1",
            owner=member,
            created_by=member,
            updated_by=member,
        )

        ## Create Group and add member (owner is in by default)
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)

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
        )

        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)

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
        )

        group = BorrowdGroup.objects.create_group(
            name="Test Group 2",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member, is_moderator=True)

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
        )

        group = BorrowdGroup.objects.create_group(
            name="Approval Required Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=True,
        )
        membership = group.add_user(pending_member)

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

        group = BorrowdGroup.objects.create_group(
            name="Pending Owner Group",
            created_by=active_member,
            updated_by=active_member,
            membership_requires_approval=True,
        )
        membership = group.add_user(pending_member)
        pending_members_item = Item.objects.create(
            name="Pending Member Item",
            description="Should stay hidden until approval.",
            owner=pending_member,
            created_by=pending_member,
            updated_by=pending_member,
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

        group = BorrowdGroup.objects.create_group(
            name="Join First Group",
            created_by=creator,
            updated_by=creator,
            membership_requires_approval=False,
        )
        group.add_user(member)

        member_item = Item.objects.create(
            name="Member Item",
            description="Created after joining the group.",
            owner=member,
            created_by=member,
            updated_by=member,
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

        group = BorrowdGroup.objects.create_group(
            name="Three Member Group",
            created_by=creator,
            updated_by=creator,
            membership_requires_approval=False,
        )
        group.add_user(member_b)
        group.add_user(member_c)

        item_b = Item.objects.create(
            name="Item B",
            description="Owned by member B.",
            owner=member_b,
            created_by=member_b,
            updated_by=member_b,
        )
        item_c = Item.objects.create(
            name="Item C",
            description="Owned by member C.",
            owner=member_c,
            created_by=member_c,
            updated_by=member_c,
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

        group = BorrowdGroup.objects.create_group(
            name="Detail Visibility Group",
            created_by=creator,
            updated_by=creator,
            membership_requires_approval=False,
        )
        group.add_user(member)

        member_item = Item.objects.create(
            name="Detail Member Item",
            description="Detail page should be visible to creator.",
            owner=member,
            created_by=member,
            updated_by=member,
        )

        request = self.factory.get(f"/items/{member_item.pk}/")
        request.user = creator

        try:
            response = ItemDetailView.as_view()(request, pk=member_item.pk)
        except Http404:
            self.fail("Group creator should be able to view member item detail page")

        self.assertEqual(response.status_code, 200)

    def test_member_cannot_open_item_detail_after_leaving_group(self) -> None:
        """
        A user who leaves a shared group should no longer be able to open
        detail pages for items shared only through that group.
        """
        owner = self.owner
        member = self.member

        group = BorrowdGroup.objects.create_group(
            name="Leave Detail Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)

        item = Item.objects.create(
            name="Leave Detail Item",
            description="Only visible through shared group membership.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
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

        group_one = BorrowdGroup.objects.create_group(
            name="Primary Shared Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_one.add_user(member)

        group_two = BorrowdGroup.objects.create_group(
            name="Secondary Shared Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_two.add_user(member)

        item = Item.objects.create(
            name="Still Shared Item",
            description="Should remain visible through second group.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
        )

        group_one.remove_user(member)

        request = self.factory.get(f"/items/{item.pk}/")
        request.user = member
        response = ItemDetailView.as_view()(request, pk=item.pk)

        self.assertEqual(response.status_code, 200)


class PerGroupSharingVisibilityTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.factory = RequestFactory()

    def _items_for(self, user: BorrowdUser) -> list[Item]:
        request = self.factory.get("/items/")
        request.user = user
        return list(ItemListView.as_view()(request).context_data["item_list"])

    def test_item_not_shared_with_any_group_is_hidden_from_group_members(
        self,
    ) -> None:
        """
        An item with share_with_all_groups=False and no shared_with_groups
        should be invisible to group members even if they share a group with
        the owner.
        """
        owner = self.owner
        member = self.member

        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)

        Item.objects.create(
            name="Private Item",
            description="Not shared with any group.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=False,
        )

        self.assertEqual(self._items_for(member), [])

    def test_item_shared_with_specific_group_visible_only_to_that_group(
        self,
    ) -> None:
        """
        An item with share_with_all_groups=False and shared_with_groups=[group_a]
        should be visible to members of group_a but not to members of group_b.
        """
        owner = self.owner
        member_in = self.member
        member_out = BorrowdUser.objects.create(
            username="member_out", email="member_out@example.com"
        )

        group_a = BorrowdGroup.objects.create_group(
            name="Group A",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_a.add_user(member_in)

        group_b = BorrowdGroup.objects.create_group(
            name="Group B",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_b.add_user(member_out)

        item = Item.objects.create(
            name="Group A Only Item",
            description="Shared only with Group A.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=False,
        )
        item.shared_with_groups.add(group_a)

        self.assertIn(item, self._items_for(member_in))
        self.assertNotIn(item, self._items_for(member_out))

    def test_item_shared_with_multiple_groups_visible_to_all_of_them(
        self,
    ) -> None:
        """
        An item with share_with_all_groups=False and two explicit groups should
        be visible to active members of both groups.
        """
        owner = self.owner
        member_a = self.member
        member_b = BorrowdUser.objects.create(
            username="member_b", email="member_b@example.com"
        )

        group_a = BorrowdGroup.objects.create_group(
            name="Group A",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_a.add_user(member_a)

        group_b = BorrowdGroup.objects.create_group(
            name="Group B",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_b.add_user(member_b)

        item = Item.objects.create(
            name="Multi-Group Item",
            description="Shared with Group A and Group B.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=False,
        )
        item.shared_with_groups.add(group_a, group_b)

        self.assertIn(item, self._items_for(member_a))
        self.assertIn(item, self._items_for(member_b))

    def test_switching_to_per_group_sharing_revokes_unselected_groups(
        self,
    ) -> None:
        """
        Changing share_with_all_groups from True to False and setting an explicit
        shared_with_groups should immediately revoke visibility for groups not in
        the new list.
        """
        owner = self.owner
        member_a = self.member
        member_b = BorrowdUser.objects.create(
            username="member_b", email="member_b@example.com"
        )

        group_a = BorrowdGroup.objects.create_group(
            name="Group A",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_a.add_user(member_a)

        group_b = BorrowdGroup.objects.create_group(
            name="Group B",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group_b.add_user(member_b)

        item = Item.objects.create(
            name="Toggled Item",
            description="Starts shared with all groups.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=True,
        )

        # Both members can see it before the change
        self.assertIn(item, self._items_for(member_a))
        self.assertIn(item, self._items_for(member_b))

        # Narrow sharing to group_a only
        item.share_with_all_groups = False
        item.save()
        item.shared_with_groups.set([group_a])

        self.assertIn(item, self._items_for(member_a))
        self.assertNotIn(item, self._items_for(member_b))

    def test_new_group_member_sees_share_all_item_when_owner_joins(
        self,
    ) -> None:
        """
        When the owner joins a new group, members of that group should gain
        visibility of the owner's items that have share_with_all_groups=True.
        """
        owner = self.owner
        new_member = self.member

        item = Item.objects.create(
            name="All Groups Item",
            description="Shared with all groups.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=True,
        )

        # new_member creates a group; owner then joins it
        new_group = BorrowdGroup.objects.create_group(
            name="New Group",
            created_by=new_member,
            updated_by=new_member,
            membership_requires_approval=False,
        )
        new_group.add_user(owner)

        self.assertIn(item, self._items_for(new_member))

    def test_new_group_member_cannot_see_item_not_shared_with_their_group(
        self,
    ) -> None:
        """
        When the owner joins a new group, members of that group should NOT gain
        visibility of items that have share_with_all_groups=False and don't
        include the new group in shared_with_groups.
        """
        owner = self.owner
        new_member = self.member

        Item.objects.create(
            name="Specific Groups Item",
            description="Not shared with the new group.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=False,
        )

        new_group = BorrowdGroup.objects.create_group(
            name="New Group",
            created_by=new_member,
            updated_by=new_member,
            membership_requires_approval=False,
        )
        new_group.add_user(owner)

        self.assertEqual(self._items_for(new_member), [])

    def test_item_loses_visibility_when_owner_leaves_explicitly_shared_group(
        self,
    ) -> None:
        """
        When the owner leaves a group that is listed in shared_with_groups,
        that group's members should lose visibility — the owner's active membership
        is required even for explicitly shared groups.
        """
        owner = self.owner
        member = self.member

        # member creates and moderates the group so owner can leave freely
        group = BorrowdGroup.objects.create_group(
            name="Shared Group",
            created_by=member,
            updated_by=member,
            membership_requires_approval=False,
        )
        group.add_user(owner)

        item = Item.objects.create(
            name="Explicitly Shared Item",
            description="Shared with one group that the owner later leaves.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
            share_with_all_groups=False,
        )
        item.shared_with_groups.add(group)

        # Member can see the item while the owner is active in the group
        self.assertIn(item, self._items_for(member))

        group.remove_user(owner)

        # Member loses visibility once the owner leaves
        self.assertNotIn(item, self._items_for(member))
