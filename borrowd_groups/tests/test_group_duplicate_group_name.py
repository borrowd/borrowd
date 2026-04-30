from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser


class DuplicateGroupNameTests(TestCase):
    """
    Test that users can create groups with the same name as other users' groups,
    but cannot create two groups with the same name within their own account.
    """

    def setUp(self) -> None:
        self.user1 = BorrowdUser.objects.create_user(
            username="user1", password="password"
        )
        self.user2 = BorrowdUser.objects.create_user(
            username="user2", password="password"
        )
        self.group_name = "Shared Group Name"

    def test_different_users_can_create_groups_with_same_name(self) -> None:
        """Two different users should be able to create groups with identical names."""
        group1 = BorrowdGroup.objects.create(
            name=self.group_name,
            created_by=self.user1,
            updated_by=self.user1,
        )
        group2 = BorrowdGroup.objects.create(
            name=self.group_name,
            created_by=self.user2,
            updated_by=self.user2,
        )

        self.assertEqual(group1.name, group2.name)
        self.assertNotEqual(group1.created_by, group2.created_by)
        self.assertEqual(BorrowdGroup.objects.filter(name=self.group_name).count(), 2)

    def test_same_user_cannot_create_duplicate_group_via_form(self) -> None:
        """A user should not be able to create a second group with the same name via form."""
        # Create first group
        BorrowdGroup.objects.create(
            name=self.group_name,
            created_by=self.user1,
            updated_by=self.user1,
        )

        # Try to create second group with same name via form submission
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": self.group_name,
                "description": "Duplicate group",
                "trust_level": TrustLevel.STANDARD,
                "membership_requires_approval": False,
            },
        )

        # Should not redirect (form invalid)
        self.assertEqual(response.status_code, 200)
        # Should still only have 1 group with that name
        self.assertEqual(
            BorrowdGroup.objects.filter(
                name=self.group_name, created_by=self.user1
            ).count(),
            1,
        )

    def test_same_user_can_create_groups_with_different_names(self) -> None:
        """A user should be able to create multiple groups with different names."""
        self.client.force_login(self.user1)

        for i in range(3):
            response = self.client.post(
                reverse("borrowd_groups:group-create"),
                {
                    "name": f"Group {i}",
                    "description": f"Test group {i}",
                    "trust_level": TrustLevel.STANDARD,
                    "membership_requires_approval": False,
                },
            )
            # Should redirect on success
            self.assertEqual(response.status_code, 302)

        self.assertEqual(BorrowdGroup.objects.filter(created_by=self.user1).count(), 3)

    def test_duplicate_error_message_displayed_on_form_invalid(self) -> None:
        """User should see an error message when trying to create a duplicate group."""
        # Create first group
        BorrowdGroup.objects.create(
            name=self.group_name,
            created_by=self.user1,
            updated_by=self.user1,
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": self.group_name,
                "description": "Duplicate group",
                "trust_level": TrustLevel.STANDARD,
                "membership_requires_approval": False,
            },
        )

        # Check that the error message is in the response
        self.assertContains(
            response, "You already have a group with this name.", status_code=200
        )

    def test_user_can_update_group_keeping_same_name(self) -> None:
        """A user should be able to update their group and keep the same name."""
        group = BorrowdGroup.objects.create(
            name=self.group_name,
            description="Original description",
            created_by=self.user1,
            updated_by=self.user1,
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-edit", args=[group.pk]),
            {
                "name": self.group_name,  # Same name
                "description": "Updated description",
                "membership_requires_approval": True,
            },
        )

        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        group.refresh_from_db()
        self.assertEqual(group.description, "Updated description")
        self.assertEqual(group.name, self.group_name)

    def test_user_cannot_update_to_existing_group_name(self) -> None:
        """A user should not be able to rename a group to an existing group name they own."""
        group1 = BorrowdGroup.objects.create(
            name="Group A",
            created_by=self.user1,
            updated_by=self.user1,
        )
        BorrowdGroup.objects.create(
            name="Group B",
            created_by=self.user1,
            updated_by=self.user1,
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-edit", args=[group1.pk]),
            {
                "name": "Group B",  # Try to rename to existing group
                "description": "Trying to rename",
                "membership_requires_approval": False,
            },
        )

        # Should not redirect (form invalid)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "You already have a group with this name.", status_code=200
        )

    def test_case_sensitive_group_names(self) -> None:
        """Group names should be case-sensitive for duplicate checking."""
        BorrowdGroup.objects.create(
            name="my group",
            created_by=self.user1,
            updated_by=self.user1,
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "My Group",  # Different case
                "description": "Different case test",
                "trust_level": TrustLevel.STANDARD,
                "membership_requires_approval": False,
            },
        )

        # Should succeed (different case is treated as different name)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BorrowdGroup.objects.filter(created_by=self.user1).count(), 2)

    def test_whitespace_in_group_names(self) -> None:
        """Group names with different whitespace should be treated as different."""
        BorrowdGroup.objects.create(
            name="my  group",  # Double space
            created_by=self.user1,
            updated_by=self.user1,
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("borrowd_groups:group-create"),
            {
                "name": "my group",  # Single space
                "description": "Whitespace test",
                "trust_level": TrustLevel.STANDARD,
                "membership_requires_approval": False,
            },
        )

        # Should succeed (different whitespace is treated as different name)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BorrowdGroup.objects.filter(created_by=self.user1).count(), 2)
