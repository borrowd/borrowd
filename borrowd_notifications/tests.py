from django.test import TestCase
from notifications.models import Notification

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_users.models import BorrowdUser

from .services import NotificationType


class GroupMemberJoinedNotificationTests(TestCase):
    """Tests for group member joined notifications."""

    def setUp(self) -> None:
        """Set up test users."""
        # Create and delete a dummy user to offset user IDs, otherwise UserID and MembershipID will match.
        dummy = BorrowdUser.objects.create_user(
            username="dummy", email="dummy@example.com", password="password"
        )
        dummy.delete()

        self.user1 = BorrowdUser.objects.create_user(
            username="user1", email="user1@example.com", password="password1"
        )
        self.user2 = BorrowdUser.objects.create_user(
            username="user2", email="user2@example.com", password="password2"
        )
        self.user3 = BorrowdUser.objects.create_user(
            username="user3", email="user3@example.com", password="password3"
        )

    def test_group_creator_does_not_receive_self_notification(self) -> None:
        """Test that group creator does not receive notification about their own join."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.LOW,
        )

        membership = Membership.objects.get(user=self.user1, group=group)

        creator_notifications = Notification.objects.filter(recipient=self.user1)

        self.assertEqual(
            creator_notifications.count(),
            0,
            f"Group creator should not receive notification about their own join (user_id={self.user1.id}, membership_id={membership.id})",  # type: ignore[attr-defined]
        )

    def test_new_member_does_not_receive_self_notification(self) -> None:
        """Test that a user joining a group does not receive notification about their own join."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.LOW,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.MEDIUM)

        membership = Membership.objects.get(user=self.user2, group=group)

        user2_notifications = Notification.objects.filter(recipient=self.user2)

        self.assertEqual(
            user2_notifications.count(),
            0,
            f"New member should not receive notification about their own join (user_id={self.user2.id}, membership_id={membership.id})",  # type: ignore[attr-defined]
        )

    def test_group_creator_receives_notification_when_first_member_joins(
        self,
    ) -> None:
        """Test that creator receives notification when the first member joins."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.LOW,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.MEDIUM)

        # User1 (creator) should receive a notification
        user1_notifications = Notification.objects.filter(recipient=self.user1)
        self.assertEqual(
            user1_notifications.count(),
            1,
            "Existing member should receive notification when the first new member joins",
        )

        # Notification is proper type and mentions user 2 "joined"
        notification = user1_notifications.first()
        self.assertEqual(notification.verb, NotificationType.GROUP_MEMBER_JOINED.value)
        self.assertEqual(notification.target, group)
        self.assertIn(
            "joined", notification.description.lower()
        )  # Fragile but I can't think of a better way to do this at the moment.

    def test_group_creator_receives_notification_when_multiple_members_join(
        self,
    ) -> None:
        """Test that creator receives notification when multiple new members join."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.LOW,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.MEDIUM)
        group.add_user(self.user3, trust_level=TrustLevel.MEDIUM)

        # User1 (creator) should receive 2 notifications
        user1_notifications = Notification.objects.filter(recipient=self.user1)
        self.assertEqual(
            user1_notifications.count(),
            2,
            "Existing member should receive multiple notifications when multiple new members join",
        )

        notifications_list = list(user1_notifications.order_by("timestamp"))

        # First notification should be about user2 joining
        first_notification = notifications_list[0]
        self.assertEqual(
            first_notification.verb, NotificationType.GROUP_MEMBER_JOINED.value
        )
        self.assertEqual(first_notification.target, group)
        self.assertIn("joined", first_notification.description.lower())
        self.assertIsInstance(first_notification.action_object, Membership)
        self.assertEqual(first_notification.action_object.user, self.user2)

        # Second notification should be about user3 joining
        second_notification = notifications_list[1]
        self.assertEqual(
            second_notification.verb, NotificationType.GROUP_MEMBER_JOINED.value
        )
        self.assertEqual(second_notification.target, group)
        self.assertIn("joined", second_notification.description.lower())
        self.assertIsInstance(second_notification.action_object, Membership)
        self.assertEqual(second_notification.action_object.user, self.user3)

    def test_all_existing_members_receive_notifications(self) -> None:
        """Test that all existing members receive notification when a new member joins."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.LOW,
        )

        group.add_user(self.user2, trust_level=TrustLevel.MEDIUM)

        # Clear notifications about user2 joining
        Notification.objects.all().delete()

        group.add_user(self.user3, trust_level=TrustLevel.MEDIUM)

        # Both user1 and user2 should receive notifications
        user1_notifications = Notification.objects.filter(recipient=self.user1)
        user2_notifications = Notification.objects.filter(recipient=self.user2)

        self.assertEqual(
            user1_notifications.count(),
            1,
            "User1 should receive notification when user3 joins",
        )
        self.assertEqual(
            user2_notifications.count(),
            1,
            "User2 should receive notification when user3 joins",
        )
