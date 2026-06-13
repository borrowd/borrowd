from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_notifications.services import NotificationType
from borrowd_users.models import BorrowdUser


class ModeratorHandoffTests(TestCase):
    """
    Tests covering moderator handoff flow:

    - When last moderator leaves, the group is flagged
    - Remaining members are notified
    - A member can become moderator
    - Notifications are cleared once moderator is assigned
    - Only the first member can claim moderator role
    """

    def setUp(self) -> None:
        """
        Set up:
        - group with one moderator (owner)
        - two regular members
        """
        self.owner = BorrowdUser.objects.create_user(
            username="owner",
            password="password",
        )
        self.member = BorrowdUser.objects.create_user(
            username="member",
            password="password",
        )
        self.other_member = BorrowdUser.objects.create_user(
            username="other_member",
            password="password",
        )

        self.group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )

        # Owner is moderator by default
        self.group.add_user(self.member, trust_level=TrustLevel.STANDARD)
        self.group.add_user(self.other_member, trust_level=TrustLevel.STANDARD)

        # Ensure clean notification state
        Notification.objects.all().delete()

    def test_last_moderator_leaving_flags_group_and_notifies_members(self) -> None:
        """
        When the last moderator leaves:
        - group.needs_moderator should be True
        - remaining active members should receive notifications
        - leaving user should NOT be notified
        """
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("borrowd_groups:leave-group", args=[self.group.pk])
        )

        # Expect redirect to group list after leaving
        self.assertRedirects(response, reverse("borrowd_groups:group-list"))

        self.group.refresh_from_db()

        # Assert group is flagged as needing a moderator
        self.assertTrue(self.group.needs_moderator)

        notifications = Notification.objects.filter(
            verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
            target_object_id=self.group.pk,
        )

        # Expect notifications for remaining members only
        self.assertEqual(notifications.count(), 2)
        self.assertTrue(notifications.filter(recipient=self.member).exists())
        self.assertTrue(notifications.filter(recipient=self.other_member).exists())
        self.assertFalse(notifications.filter(recipient=self.owner).exists())

    def test_member_can_become_moderator(self) -> None:
        """
        A member can claim moderator role when:
        - group.needs_moderator = True
        - no existing moderator exists
        """
        # Simulate "no moderator" state
        Membership.objects.filter(
            user=self.owner,
            group=self.group,
        ).update(is_moderator=False)

        Membership.objects.filter(user=self.owner, group=self.group).update(
            is_moderator=False
        )

        self.client.force_login(self.member)

        response = self.client.post(
            reverse("borrowd_groups:become-moderator", args=[self.group.pk])
        )

        # Expect redirect back to group detail
        self.assertRedirects(
            response,
            reverse("borrowd_groups:group-detail", args=[self.group.pk]),
        )

        self.group.refresh_from_db()

        # Assert group no longer needs moderator
        self.assertFalse(self.group.needs_moderator)

        membership = Membership.objects.get(user=self.member, group=self.group)

        # Assert member is now moderator
        self.assertTrue(membership.is_moderator)

    def test_become_moderator_clears_notifications_for_all_members(self) -> None:
        """
        Once a moderator is assigned:
        - all moderator-needed notifications should be marked as read
        """
        Membership.objects.filter(
            user=self.owner,
            group=self.group,
        ).update(is_moderator=False)

        Membership.objects.filter(user=self.owner, group=self.group).update(
            is_moderator=False
        )

        # Create unread notifications
        Notification.objects.create(
            recipient=self.member,
            actor=self.owner,
            verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
            action_object=self.group,
            target=self.group,
            description="Group needs a new moderator",
        )
        Notification.objects.create(
            recipient=self.other_member,
            actor=self.owner,
            verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
            action_object=self.group,
            target=self.group,
            description="Group needs a new moderator",
        )

        self.client.force_login(self.member)

        self.client.post(
            reverse("borrowd_groups:become-moderator", args=[self.group.pk])
        )

        unread_notifications = Notification.objects.filter(
            verb=NotificationType.GROUP_NEEDS_MODERATOR.value,
            target_object_id=self.group.pk,
            unread=True,
        )

        # Assert all notifications are cleared
        self.assertEqual(unread_notifications.count(), 0)

    def test_second_member_cannot_become_moderator_after_role_claimed(self) -> None:
        """
        Only the first member to claim moderator role should succeed.
        Subsequent attempts should not change moderator state.
        """
        Membership.objects.filter(
            user=self.owner,
            group=self.group,
        ).update(is_moderator=False)

        # Simulate someone already became moderator
        Membership.objects.filter(user=self.owner, group=self.group).update(
            is_moderator=False
        )
        Membership.objects.filter(user=self.member, group=self.group).update(
            is_moderator=True
        )

        self.client.force_login(self.other_member)

        response = self.client.post(
            reverse("borrowd_groups:become-moderator", args=[self.group.pk])
        )

        # Expect redirect (no crash)
        self.assertRedirects(
            response,
            reverse("borrowd_groups:group-detail", args=[self.group.pk]),
        )

        # Assert second member did NOT become moderator
        self.assertFalse(
            Membership.objects.get(
                user=self.other_member,
                group=self.group,
            ).is_moderator
        )
