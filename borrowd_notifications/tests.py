from typing import cast
from unittest.mock import patch

from django.http import HttpResponse
from django.test import TestCase, TransactionTestCase, override_settings
from django.core import mail
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
from borrowd_notifications.channels import (
    AppNotificationStrategy,
    EmailNotificationStrategy,
)
from borrowd_notifications.services import NotificationService
from borrowd_users.models import BorrowdUser

from .models import NotificationPreference, NotificationType


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

        # Notification is proper type and mentions user 2 wanting to join
        notification = user1_notifications.first()
        self.assertEqual(notification.verb, NotificationType.MEMBERSHIP_PENDING.value)
        self.assertEqual(notification.target, group)
        self.assertIn("join", notification.description.lower())

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

        # First notification should be about user2 requesting to join
        first_notification = notifications_list[0]
        self.assertEqual(
            first_notification.verb, NotificationType.MEMBERSHIP_PENDING.value
        )
        self.assertEqual(first_notification.target, group)
        self.assertIn("join", first_notification.description.lower())
        self.assertIsInstance(first_notification.action_object, Membership)
        self.assertEqual(first_notification.action_object.user, self.user2)

        # Second notification should be about user3 requesting to join
        second_notification = notifications_list[1]
        self.assertEqual(
            second_notification.verb, NotificationType.MEMBERSHIP_PENDING.value
        )
        self.assertEqual(second_notification.target, group)
        self.assertIn("join", second_notification.description.lower())
        self.assertIsInstance(second_notification.action_object, Membership)
        self.assertEqual(second_notification.action_object.user, self.user3)

    def test_only_moderators_receive_membership_pending_notification(self) -> None:
        """Test that only moderators receive notification when a new member requests to join."""
        group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=self.user1,
            updated_by=self.user1,
            trust_level=TrustLevel.STANDARD,
        )

        group.add_user(self.user2, trust_level=TrustLevel.STANDARD)

        # Clear notifications about user2's request
        Notification.objects.all().delete()

        group.add_user(self.user3, trust_level=TrustLevel.STANDARD)

        # Only user1 (moderator) should receive notification; user2 is not a moderator
        user1_notifications = Notification.objects.filter(recipient=self.user1)
        user2_notifications = Notification.objects.filter(recipient=self.user2)

        self.assertEqual(
            user1_notifications.count(),
            1,
            "Moderator should receive notification when user3 requests to join",
        )
        self.assertEqual(
            user2_notifications.count(),
            0,
            "Non-moderator user2 should not receive notification for a pending membership",
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


class TransactionNotificationTests(TestCase):
    """Tests for lending lifecycle notifications fired by the Transaction post_save signal."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower", email="borrower@example.com", password="password"
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _create_transaction(
        self, status: TransactionStatus, updated_by: BorrowdUser | None = None
    ) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=updated_by if updated_by else self.owner,
        )

    def test_requested_notifies_owner(self) -> None:
        """Owner receives ITEM_REQUESTED from the borrower; borrower receives nothing."""
        self._create_transaction(TransactionStatus.REQUESTED)

        notifications = Notification.objects.filter(
            recipient=self.owner, verb=NotificationType.ITEM_REQUESTED.value
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.borrower)
        self.assertEqual(
            Notification.objects.filter(recipient=self.borrower).count(), 0
        )

    def test_accepted_notifies_borrower(self) -> None:
        """Borrower receives ITEM_REQUEST_ACCEPTED from the owner; owner receives nothing."""
        self._create_transaction(TransactionStatus.ACCEPTED)

        notifications = Notification.objects.filter(
            recipient=self.borrower, verb=NotificationType.ITEM_REQUEST_ACCEPTED.value
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.owner)
        self.assertEqual(Notification.objects.filter(recipient=self.owner).count(), 0)

    def test_rejected_notifies_borrower(self) -> None:
        """Borrower receives ITEM_REQUEST_DENIED from the owner; owner receives nothing."""
        self._create_transaction(TransactionStatus.REJECTED)

        notifications = Notification.objects.filter(
            recipient=self.borrower, verb=NotificationType.ITEM_REQUEST_DENIED.value
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.owner)
        self.assertEqual(Notification.objects.filter(recipient=self.owner).count(), 0)

    def test_collection_asserted_notifies_owner(self) -> None:
        """Counterpartie receives COLLECTION_ASSERTED from the asserter; asserter receives nothing."""
        transaction = self._create_transaction(TransactionStatus.COLLECTION_ASSERTED)
        updated_by = cast(BorrowdUser, transaction.updated_by)

        notifications = Notification.objects.filter(
            recipient=transaction.counter_party(updated_by),
            verb=NotificationType.COLLECTION_ASSERTED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, updated_by)
        self.assertEqual(Notification.objects.filter(recipient=updated_by).count(), 0)

    def test_collection_confirmed_notifies_counterparty(self) -> None:
        """Counterpartie receives COLLECTION_CONFIRMED from the confirmer; confirmer receives nothing."""
        transaction = self._create_transaction(TransactionStatus.COLLECTED)
        updated_by = cast(BorrowdUser, transaction.updated_by)

        notifications = Notification.objects.filter(
            recipient=transaction.counter_party(updated_by),
            verb=NotificationType.COLLECTION_CONFIRMED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, updated_by)
        self.assertEqual(Notification.objects.filter(recipient=updated_by).count(), 0)

    def test_return_asserted_notifies_counterpartie(self) -> None:
        """Counterparty receives RETURN_ASSERTED from the the asserter; and asserter receives nothing themselves."""
        transaction = self._create_transaction(TransactionStatus.RETURN_ASSERTED)
        updated_by = cast(BorrowdUser, transaction.updated_by)

        notifications = Notification.objects.filter(
            recipient=transaction.counter_party(updated_by),
            verb=NotificationType.RETURN_ASSERTED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, updated_by)
        self.assertEqual(Notification.objects.filter(recipient=updated_by).count(), 0)

    def test_return_confirmed_notifies_borrower(self) -> None:
        """Borrower receives RETURN_CONFIRMED from the owner; owner receives nothing."""
        transaction = self._create_transaction(TransactionStatus.RETURNED)
        updated_by = cast(BorrowdUser, transaction.updated_by)

        notifications = Notification.objects.filter(
            recipient=transaction.counter_party(updated_by),
            verb=NotificationType.RETURN_CONFIRMED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, updated_by)
        self.assertEqual(Notification.objects.filter(recipient=updated_by).count(), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationPreferenceRoutingTests(TransactionTestCase):
    """Tests that NotificationService dispatches to channels according to user preferences."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower", email="borrower@example.com", password="password"
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _set_preference(
        self,
        user: BorrowdUser,
        ntype: NotificationType,
        *,
        in_app: bool,
        email: bool,
    ) -> NotificationPreference:
        obj, _ = NotificationPreference.objects.get_or_create(
            user=user,
            notification_type=ntype.value,
            defaults={
                "in_app_enabled": in_app,
                "email_enabled": email,
                "push_enabled": False,
            },
        )
        obj.in_app_enabled = in_app
        obj.email_enabled = email
        obj.save()
        return obj

    def _trigger_accepted(self) -> Notification:
        """owner accepts → borrower gets ITEM_REQUEST_ACCEPTED (optional type)."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.owner,
        )
        n = Notification.objects.get(
            recipient=self.borrower,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        n.refresh_from_db()
        return n

    def _trigger_requested(self) -> Notification:
        """borrower requests → owner gets ITEM_REQUESTED (mandatory type)."""
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.REQUESTED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )
        n = Notification.objects.get(
            recipient=self.owner,
            verb=NotificationType.ITEM_REQUESTED.value,
        )
        n.refresh_from_db()
        return n

    def test_no_preference_row_suppresses_optional_notification(self) -> None:
        """Without a preference row, an optional notification is not dispatched to any channel."""
        n = self._trigger_accepted()
        self.assertEqual(NotificationService._dispatched_channels(n), set())

    def test_in_app_only_dispatches_app_channel(self) -> None:
        """With in_app_enabled=True and email_enabled=False, only APP channel is dispatched."""
        self._set_preference(
            self.borrower,
            NotificationType.ITEM_REQUEST_ACCEPTED,
            in_app=True,
            email=False,
        )
        n = self._trigger_accepted()
        channels = NotificationService._dispatched_channels(n)
        self.assertIn("APP", channels)
        self.assertNotIn("EMAIL", channels)

    def test_email_only_dispatches_email_channel(self) -> None:
        """With in_app_enabled=False and email_enabled=True, only EMAIL channel is dispatched."""
        self._set_preference(
            self.borrower,
            NotificationType.ITEM_REQUEST_ACCEPTED,
            in_app=False,
            email=True,
        )
        n = self._trigger_accepted()
        channels = NotificationService._dispatched_channels(n)
        self.assertNotIn("APP", channels)
        self.assertIn("EMAIL", channels)

    def test_both_disabled_suppresses_optional_notification(self) -> None:
        """With both channels disabled, an optional notification is not dispatched."""
        self._set_preference(
            self.borrower,
            NotificationType.ITEM_REQUEST_ACCEPTED,
            in_app=False,
            email=False,
        )
        n = self._trigger_accepted()
        self.assertEqual(NotificationService._dispatched_channels(n), set())

    def test_both_enabled_dispatches_all_channels(self) -> None:
        """With both channels enabled, APP and EMAIL are both dispatched."""
        self._set_preference(
            self.borrower,
            NotificationType.ITEM_REQUEST_ACCEPTED,
            in_app=True,
            email=True,
        )
        n = self._trigger_accepted()
        channels = NotificationService._dispatched_channels(n)
        self.assertIn("APP", channels)
        self.assertIn("EMAIL", channels)

    def test_mandatory_type_bypasses_disabled_preferences(self) -> None:
        """A mandatory notification dispatches to APP+EMAIL even when both are disabled in preferences."""
        self._set_preference(
            self.owner,
            NotificationType.ITEM_REQUESTED,
            in_app=False,
            email=False,  # should never happen, by just in case
        )
        n = self._trigger_requested()
        channels = NotificationService._dispatched_channels(n)
        self.assertIn("APP", channels)
        self.assertIn("EMAIL", channels)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationChannelErrorTests(TransactionTestCase):
    """Tests that a failing channel records an error without blocking other channels."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower", email="borrower@example.com", password="password"
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )
        NotificationPreference.objects.create(
            user=self.borrower,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            in_app_enabled=True,
            email_enabled=True,
            push_enabled=False,
        )

    def _trigger_accepted(self) -> Notification:
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.owner,
        )
        n = Notification.objects.get(
            recipient=self.borrower,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        n.refresh_from_db()
        return n

    def test_email_failure_recorded_and_app_still_succeeds(self) -> None:
        """When EMAIL raises, the error is recorded and APP is still dispatched successfully."""
        with patch.object(
            EmailNotificationStrategy,
            "send",
            side_effect=RuntimeError("SMTP unavailable"),
        ):
            n = self._trigger_accepted()

        results = NotificationService._channel_results(n)
        self.assertEqual(results.get("APP", {}).get("status"), "SUCCESS")
        self.assertEqual(results.get("EMAIL", {}).get("status"), "ERROR")
        self.assertIn("SMTP unavailable", results.get("EMAIL", {}).get("error", ""))

    def test_app_failure_recorded_and_email_still_succeeds(self) -> None:
        """When APP raises, the error is recorded and EMAIL is still dispatched successfully."""
        with patch.object(
            AppNotificationStrategy,
            "send",
            side_effect=RuntimeError("Push service down"),
        ):
            n = self._trigger_accepted()

        results = NotificationService._channel_results(n)
        self.assertEqual(results.get("APP", {}).get("status"), "ERROR")
        self.assertIn("Push service down", results.get("APP", {}).get("error", ""))
        self.assertEqual(results.get("EMAIL", {}).get("status"), "SUCCESS")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationEmailThrottleTests(TransactionTestCase):
    """Tests for the per-recipient hourly email cap and summary digest scheduling."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower", email="borrower@example.com", password="password"
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )
        NotificationPreference.objects.create(
            user=self.borrower,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            in_app_enabled=True,
            email_enabled=True,
            push_enabled=False,
        )

    def _trigger_accepted(self) -> Notification:
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.owner,
        )
        n = Notification.objects.get(
            recipient=self.borrower,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        n.refresh_from_db()
        return n

    def test_throttled_email_drops_email_and_keeps_app(self) -> None:
        """When the hourly email cap is reached, EMAIL is not dispatched but APP still is."""
        with patch.object(
            NotificationService, "_is_email_throttled", return_value=True
        ):
            n = self._trigger_accepted()

        channels = (
            set(n.data.get("channels", {}).keys())
            if isinstance(n.data, dict)
            else set()
        )
        self.assertIn("APP", channels)
        self.assertNotIn("EMAIL", channels)

    def test_throttled_email_schedules_summary_digest(self) -> None:
        """When EMAIL is throttled, a summary_digest entry is added to notification.data."""
        with patch.object(
            NotificationService, "_is_email_throttled", return_value=True
        ):
            n = self._trigger_accepted()

        self.assertIsInstance(n.data, dict)
        self.assertIn("summary_digest", n.data)
        digest = n.data["summary_digest"]
        self.assertEqual(digest.get("recipient_id"), self.borrower.pk)
        self.assertEqual(digest.get("status"), "PENDING")
        self.assertIn("scheduled_for", digest)

    def test_email_only_preference_throttled_saves_digest_and_skips_dispatch(
        self,
    ) -> None:
        """When only EMAIL is enabled and it is throttled, no channels fire but digest is saved."""
        NotificationPreference.objects.filter(
            user=self.borrower,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        ).update(in_app_enabled=False, email_enabled=True)

        with patch.object(
            NotificationService, "_is_email_throttled", return_value=True
        ):
            n = self._trigger_accepted()

        self.assertIsInstance(n.data, dict)
        self.assertEqual(n.data.get("channels", {}), {})
        self.assertIn("summary_digest", n.data)

    def test_mandatory_type_throttled_still_dispatches_app(self) -> None:
        """Mandatory notifications still dispatch APP when EMAIL is throttled."""
        NotificationPreference.objects.create(
            user=self.owner,
            notification_type=NotificationType.ITEM_REQUESTED.value,
            in_app_enabled=False,
            email_enabled=False,
            push_enabled=False,
        )
        with patch.object(
            NotificationService, "_is_email_throttled", return_value=True
        ):
            Transaction.objects.create(
                item=self.item,
                party1=self.owner,
                party2=self.borrower,
                status=TransactionStatus.REQUESTED,
                created_by=self.borrower,
                updated_by=self.borrower,
            )

        n = Notification.objects.get(
            recipient=self.owner,
            verb=NotificationType.ITEM_REQUESTED.value,
        )
        n.refresh_from_db()
        channels = (
            set(n.data.get("channels", {}).keys())
            if isinstance(n.data, dict)
            else set()
        )
        self.assertIn("APP", channels)
        self.assertNotIn("EMAIL", channels)
        self.assertIn("summary_digest", n.data)


class NotificationPreferenceToggleViewTests(TestCase):
    """Tests for the toggle_preference and bulk_toggle_preferences endpoints."""

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user", email="user@example.com", password="password"
        )
        self.client.force_login(self.user)

    def _toggle(
        self, ntype: NotificationType, channel: str, enabled: bool
    ) -> HttpResponse:
        return self.client.post(  # type: ignore[return-value]
            "/settings/notifications/toggle/",
            {
                "notification_type": ntype.value,
                "channel": channel,
                "enabled": str(enabled).lower(),
            },
        )

    def _bulk_toggle(self, scope: str, channel: str, enabled: bool) -> HttpResponse:
        return self.client.post(  # type: ignore[return-value]
            "/settings/notifications/bulk-toggle/",
            {"scope": scope, "channel": channel, "enabled": str(enabled).lower()},
        )

    def test_toggle_creates_preference_row_on_first_call(self) -> None:
        """The first toggle for a user+type creates the preference row."""
        self.assertFalse(
            NotificationPreference.objects.filter(
                user=self.user,
                notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            ).exists()
        )
        response = self._toggle(NotificationType.ITEM_REQUEST_ACCEPTED, "EMAIL", False)
        self.assertEqual(response.status_code, 204)
        pref = NotificationPreference.objects.get(
            user=self.user,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        self.assertFalse(pref.email_enabled)

    def test_toggle_updates_existing_preference(self) -> None:
        """Toggling again flips the stored value."""
        NotificationPreference.objects.create(
            user=self.user,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            in_app_enabled=True,
            email_enabled=True,
            push_enabled=False,
        )
        self._toggle(NotificationType.ITEM_REQUEST_ACCEPTED, "EMAIL", False)
        pref = NotificationPreference.objects.get(
            user=self.user,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        self.assertFalse(pref.email_enabled)
        self.assertTrue(pref.in_app_enabled)

    def test_toggle_mandatory_type_returns_403(self) -> None:
        """Attempting to toggle a mandatory type is rejected."""
        response = self._toggle(NotificationType.ITEM_REQUESTED, "EMAIL", False)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            NotificationPreference.objects.filter(
                user=self.user, notification_type=NotificationType.ITEM_REQUESTED.value
            ).exists()
        )

    def test_toggle_invalid_notification_type_returns_400(self) -> None:
        """An unrecognised notification_type value returns 400."""
        response = self.client.post(
            "/settings/notifications/toggle/",
            {"notification_type": "not-a-type", "channel": "EMAIL", "enabled": "false"},
        )
        self.assertEqual(response.status_code, 400)

    def test_toggle_invalid_channel_returns_400(self) -> None:
        """An unrecognised channel value returns 400."""
        response = self.client.post(
            "/settings/notifications/toggle/",
            {
                "notification_type": NotificationType.ITEM_REQUEST_ACCEPTED.value,
                "channel": "CARRIER_PIGEON",
                "enabled": "false",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_toggle_disables_all_optional_types_in_category(self) -> None:
        """Bulk-disable EMAIL for the lending category updates all existing rows in that scope."""
        for ntype, _ in [
            (NotificationType.ITEM_REQUEST_ACCEPTED, "accepted"),
            (NotificationType.ITEM_REQUEST_DENIED, "denied"),
        ]:
            NotificationPreference.objects.create(
                user=self.user,
                notification_type=ntype.value,
                in_app_enabled=True,
                email_enabled=True,
                push_enabled=False,
            )

        response = self._bulk_toggle("lending", "EMAIL", False)
        self.assertEqual(response.status_code, 204)

        for ntype in [
            NotificationType.ITEM_REQUEST_ACCEPTED,
            NotificationType.ITEM_REQUEST_DENIED,
        ]:
            pref = NotificationPreference.objects.get(
                user=self.user, notification_type=ntype.value
            )
            self.assertFalse(pref.email_enabled, f"{ntype} should have email disabled")
            self.assertTrue(pref.in_app_enabled, f"{ntype} in_app should be unchanged")

    def test_bulk_toggle_invalid_channel_returns_400(self) -> None:
        """An unrecognised channel in a bulk-toggle returns 400."""
        response = self._bulk_toggle("lending", "FAX", False)
        self.assertEqual(response.status_code, 400)

    def test_bulk_toggle_invalid_scope_returns_400(self) -> None:
        """An unrecognised scope in a bulk-toggle returns 400."""
        response = self._bulk_toggle("nonexistent-scope", "EMAIL", False)
        self.assertEqual(response.status_code, 400)
class ReturnFlowNotificationTests(TestCase):
    """Tests for return-request and dispute notification emails."""

    def setUp(self) -> None:
        """Set up a lender, borrower, and item."""
        self.lender = BorrowdUser.objects.create_user(
            username="lender",
            email="lender@example.com",
            password="password",
            first_name="Lena",
            last_name="Lender",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
            first_name="Bo",
            last_name="Borrower",
        )
        self.item = Item.objects.create(
            name="Test Drill",
            description="A test item",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )

    def _create_transaction(
        self,
        status: TransactionStatus,
        dispute_raised_by: BorrowdUser | None = None,
    ) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            status=status,
            dispute_raised_by=dispute_raised_by,
            created_by=self.borrower,
            updated_by=self.lender,
        )

    def test_return_request_emails_borrower(self) -> None:
        """Borrower is notified when the lender requests the item back."""
        self._create_transaction(TransactionStatus.RETURN_REQUESTED)

        notifications = Notification.objects.filter(
            recipient=self.borrower,
            verb=NotificationType.ITEM_RETURN_REQUESTED.value,
        )
        self.assertEqual(notifications.count(), 1)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Return requested")
        self.assertEqual(email.to, [self.borrower.email])
        self.assertIn("Test Drill", email.body)
        self.assertIn("requested its return", email.body)
        self.assertIn("/inventory/", email.body)

    def test_borrower_raised_dispute_emails_lender(self) -> None:
        """Lender is notified when the borrower raises the dispute."""
        self._create_transaction(
            TransactionStatus.DISPUTED, dispute_raised_by=self.borrower
        )

        notifications = Notification.objects.filter(
            recipient=self.lender,
            verb=NotificationType.ITEM_DISPUTED.value,
        )
        self.assertEqual(notifications.count(), 1)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "A dispute has been raised")
        self.assertEqual(email.to, [self.lender.email])
        self.assertIn("Hi Lena Lender", email.body)
        self.assertIn("Test Drill", email.body)
        self.assertIn(
            "good faith effort to resolve this directly with the other person",
            email.body,
        )
        self.assertIn(
            "disputes are reflected on user profiles within Borrow'd", email.body
        )

    def test_lender_raised_dispute_emails_borrower(self) -> None:
        """Borrower is notified when the lender raises the dispute."""
        self._create_transaction(
            TransactionStatus.DISPUTED, dispute_raised_by=self.lender
        )

        notifications = Notification.objects.filter(
            recipient=self.borrower,
            verb=NotificationType.ITEM_DISPUTED.value,
        )
        self.assertEqual(notifications.count(), 1)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "A dispute has been raised")
        self.assertEqual(email.to, [self.borrower.email])
        self.assertIn("Hi Bo Borrower", email.body)
        self.assertIn(
            "good faith effort to resolve this directly with the other person",
            email.body,
        )
        self.assertIn(
            "disputes are reflected on user profiles within Borrow'd", email.body
        )

    def test_dispute_without_raiser_sends_nothing(self) -> None:
        """No notification goes out if a dispute has no recorded raiser."""
        self._create_transaction(TransactionStatus.DISPUTED)

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
