from django.test import TestCase

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_users.models import BorrowdUser


class GroupCreationTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create(
            username="owner", email="owner@example.com"
        )

    def test_group_creator_is_moderator(self) -> None:
        # Arrange
        owner = self.owner

        # Act
        ## Create the Group with created_by
        group: BorrowdGroup = BorrowdGroup.objects.create_group(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
        )

        # Assert
        ## Group creator should be member and moderator
        self.assertTrue(
            Membership.objects.get(
                user=owner,
                group=group,
                is_moderator=True,
            )
        )
