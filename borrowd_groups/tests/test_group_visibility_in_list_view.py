from unittest.mock import PropertyMock, patch

from django.test import RequestFactory, TestCase

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_groups.views import GroupListView
from borrowd_users.models import BorrowdUser


class GroupListViewVisibilityTests(TestCase):
    def setUp(self) -> None:
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.factory = RequestFactory()

    def test_group_owner_can_list_group(self) -> None:
        """
        A User should be able to see Groups which they create (just
        because they are a member, but we'll check it separately).
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner

        ## Create Group
        BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
        )

        ## Preare the request
        request = self.factory.get("/groups/")
        request.user = owner

        #
        # Act
        #
        response = GroupListView.as_view()(request)
        page_memberships = response.context_data["object_list"]

        user_memberships = Membership.objects.filter(user=owner)

        #
        #  Assert
        #
        self.assertEqual(len(page_memberships), 1)
        self.assertEqual(len(user_memberships), 1)
        self.assertQuerySetEqual(user_memberships, page_memberships)

    def test_group_member_can_list_group(self) -> None:
        """
        A User should be able to see Groups of which they are a
        member.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Group
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
        )
        group.add_user(member)

        ## Preare the request
        request = self.factory.get("/groups/")
        request.user = member

        #
        # Act
        #
        response = GroupListView.as_view()(request)
        page_memberships = response.context_data["object_list"]

        user_memberships = Membership.objects.filter(user=member)

        #
        #  Assert
        #
        self.assertEqual(len(page_memberships), 1)
        self.assertEqual(len(user_memberships), 1)
        self.assertQuerySetEqual(user_memberships, page_memberships)

    def test_cannot_list_group_where_not_a_member(self) -> None:
        """
        A User should be able to see Groups of which they are a
        member.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Group
        BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
        )

        ## Preare the request
        request = self.factory.get("/groups/")
        request.user = member

        #
        # Act
        #
        response = GroupListView.as_view()(request)
        groups = response.context_data["object_list"]

        #
        #  Assert
        #
        self.assertEqual(len(groups), 0)

    def test_group_member_can_view_group_details(self) -> None:
        """
        A User should be able to see Groups of which they are a
        member.
        """
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        member = self.member

        ## Create Group
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
        )
        group.add_user(member)

        ## Preare the request
        request = self.factory.get(f"/groups/{group.pk}/")
        request.user = member

        #
        # Act
        #
        response = GroupListView.as_view()(request)

        #
        #  Assert
        #
        self.assertEqual(response.status_code, 200)

    def test_group_list_marks_groups_that_need_moderator_without_property_lookup(
        self,
    ) -> None:
        owner = self.owner
        member = self.member
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            membership_requires_approval=False,
        )
        group.add_user(member)
        Membership.objects.filter(user=owner, group=group).update(is_moderator=False)

        request = self.factory.get("/groups/")
        request.user = member

        with patch.object(
            BorrowdGroup,
            "needs_moderator",
            new_callable=PropertyMock,
            side_effect=AssertionError("group list should use annotated flag"),
        ):
            response = GroupListView.as_view()(request)
            response.render()

        page_membership = response.context_data["object_list"][0]

        self.assertTrue(page_membership.group_needs_moderator)
        self.assertContains(response, "group-needs-moderator-indicator")


class GroupListViewScopeTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.factory = RequestFactory()

    def test_default_scope_is_all(self) -> None:
        BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=self.owner,
            updated_by=self.owner,
        )

        request = self.factory.get("/groups/")
        request.user = self.owner

        response = GroupListView.as_view()(request)

        self.assertEqual(response.context_data["active_scope"], "all")

    def test_manage_scope_shows_only_moderated_groups(self) -> None:
        moderated_group = BorrowdGroup.objects.create_group(
            name="Moderated Group",
            created_by=self.member,
            updated_by=self.member,
        )
        other_group = BorrowdGroup.objects.create_group(
            name="Other Group",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )
        other_group.add_user(self.member)

        request = self.factory.get("/groups/", {"scope": "manage"})
        request.user = self.member

        response = GroupListView.as_view()(request)
        memberships = response.context_data["object_list"]

        self.assertEqual([m.group_id for m in memberships], [moderated_group.pk])

    def test_legacy_moderator_only_true_maps_to_manage_scope(self) -> None:
        moderated_group = BorrowdGroup.objects.create_group(
            name="Moderated Group",
            created_by=self.member,
            updated_by=self.member,
        )
        other_group = BorrowdGroup.objects.create_group(
            name="Other Group",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )
        other_group.add_user(self.member)

        request = self.factory.get("/groups/", {"moderator_only": "true"})
        request.user = self.member

        response = GroupListView.as_view()(request)
        memberships = response.context_data["object_list"]

        self.assertEqual(response.context_data["active_scope"], "manage")
        self.assertEqual([m.group_id for m in memberships], [moderated_group.pk])

    def test_groups_with_a_chip_sort_before_other_active_before_pending(self) -> None:
        viewer = self.member

        needs_moderator_group = BorrowdGroup.objects.create_group(
            name="Needs Moderator",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )
        needs_moderator_group.add_user(viewer)
        Membership.objects.filter(group=needs_moderator_group, user=self.owner).update(
            is_moderator=False
        )

        plain_group = BorrowdGroup.objects.create_group(
            name="Plain Group",
            created_by=viewer,
            updated_by=viewer,
        )

        pending_group = BorrowdGroup.objects.create_group(
            name="Pending Group",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=True,
        )
        pending_group.add_user(viewer)

        request = self.factory.get("/groups/")
        request.user = viewer

        response = GroupListView.as_view()(request)
        memberships = response.context_data["object_list"]

        self.assertEqual(
            [m.group_id for m in memberships],
            [needs_moderator_group.pk, plain_group.pk, pending_group.pk],
        )
