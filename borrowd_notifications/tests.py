from django.test import TestCase, TransactionTestCase
from notifications.models import Notification

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
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
            trust_level=TrustLevel.STANDARD,
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
            trust_level=TrustLevel.STANDARD,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.STANDARD)

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
            trust_level=TrustLevel.STANDARD,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.STANDARD)

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
            trust_level=TrustLevel.STANDARD,
        )

        # Clear any notifications from group creation
        Notification.objects.all().delete()

        group.add_user(self.user2, trust_level=TrustLevel.STANDARD)
        group.add_user(self.user3, trust_level=TrustLevel.STANDARD)

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
            trust_level=TrustLevel.STANDARD,
        )

        group.add_user(self.user2, trust_level=TrustLevel.STANDARD)

        # Clear notifications about user2 joining
        Notification.objects.all().delete()

        group.add_user(self.user3, trust_level=TrustLevel.STANDARD)

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


class ItemAvailableNotificationTests(TransactionTestCase):
    """Tests for item available notifications."""

    def setUp(self) -> None:
        """Set up test users and item."""
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.subscriber = BorrowdUser.objects.create_user(
            username="subscriber", email="subscriber@example.com", password="password"
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.subscription = AvailabilitySubscription.objects.create(
            user=self.subscriber,
            item=self.item,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )

    def test_notification_sent_when_transaction_returned(self) -> None:
        """Test that subscriber receives notification when item is returned."""
        # Create a transaction and set to RETURNED
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.RETURNED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        # Check notification is sent
        notifications = Notification.objects.filter(
            recipient=self.subscriber,
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(notifications.count(), 1)
        notification = notifications.first()
        self.assertEqual(notification.target, self.subscription)
        self.assertIn("now available", notification.description)

        # Check subscription is updated
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.NOTIFIED
        )
        self.assertIsNotNone(self.subscription.notified_at)

    def test_notification_sent_when_transaction_cancelled(self) -> None:
        """Test that subscriber receives notification when request is cancelled."""
        # Create a transaction and set to CANCELLED
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.CANCELLED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        # Check notification is sent
        notifications = Notification.objects.filter(
            recipient=self.subscriber,
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            1,
            "Subscriber should receive notification when transaction is cancelled",
        )

        # Check subscription is updated
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.NOTIFIED
        )

    def test_notification_sent_when_transaction_rejected(self) -> None:
        """Test that subscriber receives notification when request is rejected."""
        # Create a transaction and set to REJECTED
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.REJECTED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        # Check notification is sent
        notifications = Notification.objects.filter(
            recipient=self.subscriber,
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            1,
            "Subscriber should receive notification when transaction is rejected",
        )

        # Check subscription is updated
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.NOTIFIED
        )

    def test_no_notification_if_item_not_borrowable(self) -> None:
        """Test that no notification is sent if item is not borrowable."""
        # Make item not available (e.g., set status to BORROWED)
        self.item.status = ItemStatus.BORROWED
        self.item.save()

        # Create a transaction and set to RETURNED
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            created_by=self.subscriber,
            status=TransactionStatus.RETURNED,
            updated_by=self.owner,
        )

        # Check no notification is sent
        notifications = Notification.objects.filter(
            recipient=self.subscriber,
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(notifications.count(), 0)

        # Subscription should remain ACTIVE
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )

    def test_multiple_subscribers_receive_notifications(self) -> None:
        """Test that multiple subscribers receive notifications."""
        subscriber2 = BorrowdUser.objects.create_user(
            username="subscriber2", email="subscriber2@example.com", password="password"
        )
        subscription2 = AvailabilitySubscription.objects.create(
            user=subscriber2,
            item=self.item,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )

        # Create a transaction and set to RETURNED
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.RETURNED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        # Check both subscribers receive notifications
        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            2,
            "Both subscribers should receive notifications when item becomes available",
        )

        recipients = [n.recipient for n in notifications]
        self.assertIn(self.subscriber, recipients)
        self.assertIn(subscriber2, recipients)

        # Both subscriptions updated
        self.subscription.refresh_from_db()
        subscription2.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.NOTIFIED
        )
        self.assertEqual(subscription2.status, AvailabilitySubscriptionStatus.NOTIFIED)

    def test_no_notification_on_requested_status(self) -> None:
        """Test that no notification is sent when transaction is REQUESTED."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.REQUESTED,
            created_by=self.subscriber,
            updated_by=self.subscriber,
        )

        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            0,
            "No notification should be sent when transaction status is REQUESTED",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )

    def test_no_notification_on_accepted_status(self) -> None:
        """Test that no notification is sent when transaction is ACCEPTED."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.ACCEPTED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            0,
            "No notification should be sent when transaction status is ACCEPTED",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )

    def test_no_notification_on_collection_asserted_status(self) -> None:
        """Test that no notification is sent when transaction is COLLECTION_ASSERTED."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.COLLECTION_ASSERTED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            0,
            "No notification should be sent when transaction status is COLLECTION_ASSERTED",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )

    def test_no_notification_on_collected_status(self) -> None:
        """Test that no notification is sent when transaction is COLLECTED."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.COLLECTED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            0,
            "No notification should be sent when transaction status is COLLECTED",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )

    def test_no_notification_on_return_asserted_status(self) -> None:
        """Test that no notification is sent when transaction is RETURN_ASSERTED."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.subscriber,
            status=TransactionStatus.RETURN_ASSERTED,
            created_by=self.subscriber,
            updated_by=self.owner,
        )

        notifications = Notification.objects.filter(
            verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
        )
        self.assertEqual(
            notifications.count(),
            0,
            "No notification should be sent when transaction status is RETURN_ASSERTED",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.ACTIVE
        )
