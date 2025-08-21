from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_groups.views import GroupDetailView
from borrowd_users.models import BorrowdUser


class GroupDetailViewTests(TestCase):
    def setUp(self) -> None:
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )
        self.factory = RequestFactory()

    def test_group_member_can_view_detail_page(self) -> None:
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner

        ## Create Group
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )

        ## Preare the request
        request = self.factory.get(f"/groups/{group.pk}")
        request.user = owner

        #
        # Act
        #
        response = GroupDetailView.as_view()(request, pk=group.pk)

        #
        #  Assert
        #
        self.assertEqual(response.status_code, 200)

    def test_logged_in_non_member_cannot_view_detail_page(self) -> None:
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner
        another = self.member

        ## Create Group
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )

        ## Preare the request
        request = self.factory.get(f"/groups/{group.pk}")
        request.user = another

        #
        # Act
        #
        response = GroupDetailView.as_view()(request, pk=group.pk)

        #
        #  Assert
        #
        # Forbidden error
        self.assertEqual(response.status_code, 403)

    def test_logged_out_user_cannot_view_detail_page(self) -> None:
        #
        #  Arrange
        #

        ## Get Users
        owner = self.owner

        ## Create Group
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.HIGH,
        )

        ## Preare the request
        request = self.factory.get(f"/groups/{group.pk}")
        request.user = AnonymousUser()

        #
        # Act
        #
        response = GroupDetailView.as_view()(request, pk=group.pk)

        #
        #  Assert
        #
        # Redirect to login page
        self.assertEqual(response.status_code, 302)
