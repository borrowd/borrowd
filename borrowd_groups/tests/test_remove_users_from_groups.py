from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_groups.exceptions import ModeratorRequiredException
from borrowd_groups.models import BorrowdGroup, Membership
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
        member = BorrowdUser.objects.create_user(username="user2", password="password2")

        ## Create a group and add the user
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group",
            created_by=user,
            updated_by=user,
            membership_requires_approval=False,
        )
        group.add_user(member, trust_level=TrustLevel.LOW)

        # Act
        ## Remove the user from the group
        group.remove_user(member)

        # Assert
        ## The user is no longer in the group
        self.assertEqual(list(member.groups.all()), [])
        ## The group no longer contains the user
        self.assertEqual(list(group.users.all()), [user])

    def test_remove_multiple_users_from_group(self) -> None:
        # Arrange
        ## Create users
        user1 = BorrowdUser.objects.create_user(username="user1", password="password1")
        user2 = BorrowdUser.objects.create_user(username="user2", password="password2")
        user3 = BorrowdUser.objects.create_user(username="user3", password="password3")

        ## Create a group and add all users
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group",
            created_by=user1,
            updated_by=user1,
            membership_requires_approval=False,
        )
        for user in [user2, user3]:
            group.add_user(user, is_moderator=True, trust_level=TrustLevel.MEDIUM)

        # Act
        ## Remove all users from the group
        for user in [user1, user2]:
            group.remove_user(user)

        # Assert
        ## Last remaining moderator is still in the group
        self.assertEqual(list(group.users.all()), [user3])
        ## Owner and second member no longer in the group
        self.assertEqual(list(user1.groups.all()), [])
        self.assertEqual(list(user2.groups.all()), [])

    def test_remove_user_not_in_group(self) -> None:
        # Arrange
        ## Create a user
        user = BorrowdUser.objects.create_user(username="user1", password="password1")
        other = BorrowdUser.objects.create_user(username="user2", password="password2")

        ## Create a group without adding the user
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group",
            created_by=user,
            updated_by=user,
            membership_requires_approval=False,
        )

        # Assert
        ## Attempt to remove the user from the group
        with self.assertRaises(Membership.DoesNotExist):
            # Act
            group.remove_user(other)

    def test_cannot_remove_last_moderator_from_group(
        self,
    ) -> None:
        # Arrange
        owner = BorrowdUser.objects.create_user(username="user1", password="password1")

        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )

        # Assert
        ## The remove_user call below should raise this exception
        with self.assertRaises(ModeratorRequiredException):
            # Act
            group.remove_user(owner)

    def test_cannot_demote_last_moderator_from_group(
        self,
    ) -> None:
        # Arrange
        owner = BorrowdUser.objects.create_user(username="user1", password="password1")

        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=owner,
            updated_by=owner,
            trust_level=TrustLevel.LOW,
        )

        # Assert
        ## The update_user_membership call below should raise this exception
        with self.assertRaises(ModeratorRequiredException):
            # Act
            group.update_user_membership(owner, is_moderator=False)
