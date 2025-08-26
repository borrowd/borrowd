from django.test import RequestFactory, TestCase

from borrowd.models import TrustLevel
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
        BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
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
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

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
        BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
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
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

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
