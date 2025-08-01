from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_groups.exceptions import ExistingMemberException
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class AddUsersToGroupsTests(TestCase):
    def test_cannot_add_existing_members_to_group(self) -> None:
        # Assert
        ## The add_user call below should raise this exception
        with self.assertRaises(ExistingMemberException):
            # Arrange
            ## Create users
            user1 = BorrowdUser.objects.create_user(
                username="user1", password="password1"
            )
            ## Create a group
            group: BorrowdGroup = BorrowdGroup.objects.create(
                name="Group",
                created_by=user1,
                updated_by=user1,
                membership_requires_approval=False,
            )

            # Act
            ## Add user1 to the group
            group.add_user(user1, trust_level=TrustLevel.MEDIUM)

    def test_users_only_in_added_groups(self) -> None:
        # Arrange

        ## Create users
        user1 = BorrowdUser.objects.create(username="user1", password="password1")
        user2 = BorrowdUser.objects.create(username="user2", password="password2")

        # Act
        ## Create groups
        # Unfortunately mypy is struggling here. It fails with:
        #   error: Incompatible types in assignment (expression has
        #   type "Group", variable has type "BorrowdGroup")  [assignment]
        # Don't have time to chase down the specifics.
        borrowd_group1: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 1",
            created_by=user1,
            updated_by=user1,
            membership_requires_approval=False,
        )
        borrowd_group2: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group 2",
            created_by=user2,
            updated_by=user2,
            membership_requires_approval=False,
        )

        # Assert

        ## user1 is only in group1
        self.assertEqual(list(user1.borrowd_groups.all()), [borrowd_group1])

        ## user2 is only in group2
        self.assertEqual(list(user2.borrowd_groups.all()), [borrowd_group2])

        ## group1 contains only user1
        self.assertEqual(list(borrowd_group1.users.all()), [user1])

        ## group2 contains only user2
        self.assertEqual(list(borrowd_group2.users.all()), [user2])

    def test_add_multiple_users_to_group(self) -> None:
        # Arrange
        ## Create users
        user1 = BorrowdUser.objects.create_user(username="user1", password="password1")
        user2 = BorrowdUser.objects.create_user(username="user2", password="password2")
        user3 = BorrowdUser.objects.create_user(username="user3", password="password3")

        ## Create a group
        group: BorrowdGroup = BorrowdGroup.objects.create(
            name="Group",
            created_by=user1,
            updated_by=user1,
            membership_requires_approval=False,
        )

        # Act
        ## Add multiple users to the group
        for user in [user2, user3]:
            group.add_user(user, trust_level=TrustLevel.MEDIUM)

        # Assert

        ## All users are in the group
        self.assertEqual(set(group.users.all()), {user1, user2, user3})

        ## Each user is in the group
        # User1 in Group by default as creator
        self.assertEqual(list(user1.borrowd_groups.all()), [group])
        self.assertEqual(list(user2.borrowd_groups.all()), [group])
        self.assertEqual(list(user3.borrowd_groups.all()), [group])
