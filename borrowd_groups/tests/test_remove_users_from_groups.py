from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class RemoveUsersFromGroupsTests(TestCase):
    # Unfortunately mypy is struggling here. It fails with:
    #   error: Incompatible types in assignment (expression has
    #   type "Group", variable has type "BorrowdGroup")  [assignment]
    # Don't have time to chase down the specifics.
    def test_remove_user_from_group(self) -> None:
        # Arrange
        ## Create a user
        user = BorrowdUser.objects.create_user(username="user1", password="password1")

        ## Create a group and add the user
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group", created_by=user, updated_by=user
        )  # type: ignore
        group.add_user(user, trust_level=TrustLevel.HIGH)

        # Act
        ## Remove the user from the group
        group.remove_user(user)

        # Assert
        ## The user is no longer in the group
        self.assertEqual(list(user.groups.all()), [])
        ## The group no longer contains the user
        self.assertEqual(list(group.users.all()), [])

    def test_remove_multiple_users_from_group(self) -> None:
        # Arrange
        ## Create users
        user1 = BorrowdUser.objects.create_user(username="user1", password="password1")
        user2 = BorrowdUser.objects.create_user(username="user2", password="password2")
        user3 = BorrowdUser.objects.create_user(username="user3", password="password3")

        ## Create a group and add all users
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group", created_by=user1, updated_by=user1
        )  # type: ignore
        for user in [user1, user2, user3]:
            group.add_user(user, trust_level=TrustLevel.MEDIUM)

        # Act
        ## Remove all users from the group
        for user in [user1, user2, user3]:
            group.remove_user(user)

        # Assert
        ## No users are in the group
        self.assertEqual(list(group.users.all()), [])
        ## Each user is no longer in the group
        self.assertEqual(list(user1.groups.all()), [])
        self.assertEqual(list(user2.groups.all()), [])
        self.assertEqual(list(user3.groups.all()), [])

    def test_remove_user_not_in_group(self) -> None:
        # Arrange
        ## Create a user
        user = BorrowdUser.objects.create_user(username="user1", password="password1")

        ## Create a group without adding the user
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group", created_by=user, updated_by=user
        )  # type: ignore

        # Act
        ## Attempt to remove the user from the group
        # TODO: Should this raise an exception?
        group.remove_user(user)

        # Assert
        ## The user is still not in the group
        self.assertEqual(list(user.groups.all()), [])
        ## The group still does not contain the user
        self.assertEqual(list(group.users.all()), [])
