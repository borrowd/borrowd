from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.http import HttpResponseBase
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
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

from .models import NotificationMetadata, NotificationPreference, NotificationType


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
        group = BorrowdGroup.objects.create_group(
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
            f"Group creator should not receive notification about their own join (user_id={self.user1.id}, membership_id={membership.id})",
        )

    def test_new_member_does_not_receive_self_notification(self) -> None:
        """Test that a user joining a group does not receive notification about their own join."""
        group = BorrowdGroup.objects.create_group(
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
            f"New member should not receive notification about their own join (user_id={self.user2.id}, membership_id={membership.id})",
        )

    def test_group_creator_receives_notification_when_first_member_joins(
        self,
    ) -> None:
        """Test that creator receives notification when the first member joins."""
        group = BorrowdGroup.objects.create_group(
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
        group = BorrowdGroup.objects.create_group(
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
        group = BorrowdGroup.objects.create_group(
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
        updated_by = transaction.updated_by

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
        updated_by = transaction.updated_by

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
        updated_by = transaction.updated_by

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
        updated_by = transaction.updated_by

        notifications = Notification.objects.filter(
            recipient=transaction.counter_party(updated_by),
            verb=NotificationType.RETURN_CONFIRMED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, updated_by)
        self.assertEqual(Notification.objects.filter(recipient=updated_by).count(), 0)


class GiveawayNotificationTests(TestCase):
    """Tests for giveaway notifications fired by the Transaction post_save signal."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password",
            first_name="Priya",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
            first_name="Marcus",
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _create_transaction(self, status: TransactionStatus) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.borrower,
            updated_by=self.owner,
        )

    def test_offer_notifies_borrower(self) -> None:
        """Borrower receives GIVEAWAY_OFFER_SENT from the owner."""
        self._create_transaction(TransactionStatus.GIVEAWAY_OFFERED)

        notifications = Notification.objects.filter(
            recipient=self.borrower, verb=NotificationType.GIVEAWAY_OFFER_SENT.value
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.owner)
        self.assertEqual(Notification.objects.filter(recipient=self.owner).count(), 0)

    def test_accept_notifies_owner(self) -> None:
        """Owner receives GIVEAWAY_ACCEPTED from the borrower."""
        self._create_transaction(TransactionStatus.OWNERSHIP_TRANSFERRED)

        notifications = Notification.objects.filter(
            recipient=self.owner, verb=NotificationType.GIVEAWAY_ACCEPTED.value
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.borrower)

    def test_decline_notifies_owner(self) -> None:
        """A declined offer (reverting to COLLECTED) notifies the owner, not a
        spurious collection-confirmed."""
        tx = self._create_transaction(TransactionStatus.GIVEAWAY_OFFERED)
        tx.status = TransactionStatus.COLLECTED
        tx.save()

        declined = Notification.objects.filter(
            recipient=self.owner, verb=NotificationType.GIVEAWAY_DECLINED.value
        )
        self.assertEqual(declined.count(), 1)
        self.assertEqual(declined.first().actor, self.borrower)
        self.assertEqual(
            Notification.objects.filter(
                verb=NotificationType.COLLECTION_CONFIRMED.value
            ).count(),
            0,
        )

    def test_offer_in_app_copy(self) -> None:
        """The in-app message renders with the giveaway context."""
        self._create_transaction(TransactionStatus.GIVEAWAY_OFFERED)
        notification = Notification.objects.get(
            verb=NotificationType.GIVEAWAY_OFFER_SENT.value
        )
        ntype = NotificationType(notification.verb)
        context = NotificationType._get_template_context_for(notification)
        message = ntype.message_template.format(**context)
        self.assertIn(self.owner.first_name, message)
        self.assertIn(self.item.name, message)


class GiveawayRequestNotificationTests(TestCase):
    """Tests for giveaway-listing request notifications fired by the
    Transaction post_save signal."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password",
            first_name="Sofia",
        )
        self.requester = BorrowdUser.objects.create_user(
            username="requester",
            email="requester@example.com",
            password="password",
            first_name="Marcus",
        )
        self.item = Item.objects.create(
            name="Test Item",
            description="A test item",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def _create_request(self) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.requester,
            status=TransactionStatus.GIVEAWAY_REQUESTED,
            created_by=self.requester,
            updated_by=self.requester,
        )

    def test_request_notifies_owner(self) -> None:
        """Owner receives GIVEAWAY_REQUEST_RECEIVED from the requester."""
        self._create_request()

        notifications = Notification.objects.filter(
            recipient=self.owner,
            verb=NotificationType.GIVEAWAY_REQUEST_RECEIVED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().actor, self.requester)
        self.assertEqual(
            Notification.objects.filter(recipient=self.requester).count(), 0
        )

    def test_approve_notifies_both_parties(self) -> None:
        """An approved request confirms both sides, without the offer-flow
        GIVEAWAY_ACCEPTED."""
        tx = self._create_request()
        tx.status = TransactionStatus.OWNERSHIP_TRANSFERRED
        tx.save()

        approved = Notification.objects.filter(
            recipient=self.requester,
            verb=NotificationType.GIVEAWAY_REQUEST_APPROVED.value,
        )
        self.assertEqual(approved.count(), 1)
        self.assertEqual(approved.first().actor, self.owner)
        completed = Notification.objects.filter(
            recipient=self.owner,
            verb=NotificationType.GIVEAWAY_COMPLETED.value,
        )
        self.assertEqual(completed.count(), 1)
        self.assertEqual(
            Notification.objects.filter(
                verb=NotificationType.GIVEAWAY_ACCEPTED.value
            ).count(),
            0,
        )

    def test_decline_notifies_requester(self) -> None:
        """A declined request notifies the requester, not a spurious
        borrow-request denial."""
        tx = self._create_request()
        tx.status = TransactionStatus.REJECTED
        tx.save()

        declined = Notification.objects.filter(
            recipient=self.requester,
            verb=NotificationType.GIVEAWAY_REQUEST_DECLINED.value,
        )
        self.assertEqual(declined.count(), 1)
        self.assertEqual(declined.first().actor, self.owner)
        self.assertEqual(
            Notification.objects.filter(
                verb=NotificationType.ITEM_REQUEST_DENIED.value
            ).count(),
            0,
        )

    def test_cancel_sends_nothing(self) -> None:
        """A cancelled request fires no notification beyond the initial one."""
        tx = self._create_request()
        tx.status = TransactionStatus.CANCELLED
        tx.save()

        self.assertEqual(
            Notification.objects.exclude(
                verb=NotificationType.GIVEAWAY_REQUEST_RECEIVED.value
            ).count(),
            0,
        )

    def test_request_in_app_copy(self) -> None:
        """The in-app message renders with the giveaway context."""
        self._create_request()
        notification = Notification.objects.get(
            verb=NotificationType.GIVEAWAY_REQUEST_RECEIVED.value
        )
        ntype = NotificationType(notification.verb)
        context = NotificationType._get_template_context_for(notification)
        message = ntype.message_template.format(**context)
        self.assertIn(self.requester.first_name, message)
        self.assertIn(self.item.name, message)


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
        self.assertEqual(
            NotificationService._dispatched_channels(n), set({"EMAIL", "APP"})
        )
        self.assertTrue(n.borrowd_metadata.visible_in_app)

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
        self.assertTrue(n.borrowd_metadata.visible_in_app)

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
        self.assertFalse(n.borrowd_metadata.visible_in_app)

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
        self.assertFalse(n.borrowd_metadata.visible_in_app)

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
        self.assertTrue(n.borrowd_metadata.visible_in_app)

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
        self.assertTrue(n.borrowd_metadata.visible_in_app)


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
        NotificationPreference.objects.update_or_create(
            user=self.borrower,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            defaults={
                "in_app_enabled": True,
                "email_enabled": True,
                "push_enabled": False,
            },
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
        self.assertTrue(n.borrowd_metadata.visible_in_app)

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
        self.assertFalse(n.borrowd_metadata.visible_in_app)
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
        NotificationPreference.objects.update_or_create(
            user=self.borrower,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            defaults={
                "in_app_enabled": True,
                "email_enabled": True,
                "push_enabled": False,
            },
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
        NotificationPreference.objects.update_or_create(
            user=self.owner,
            notification_type=NotificationType.ITEM_REQUESTED.value,
            defaults={
                "in_app_enabled": False,
                "email_enabled": False,
                "push_enabled": False,
            },
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

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_emailed_is_persisted_after_successful_send(self) -> None:
        """A successful email dispatch writes emailed=True to the DB row."""
        n = self._trigger_accepted()
        self.assertTrue(n.emailed)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_throttle_to_digest_to_send_full_flow(self) -> None:
        """End-to-end: throttled notification schedules a digest; the command sends it."""
        from io import StringIO

        from django.contrib.contenttypes.models import ContentType
        from django.core.management import call_command

        ct = ContentType.objects.get_for_model(self.owner)

        # Hit the hourly email cap so the next notification is throttled.
        Notification.objects.bulk_create(
            [
                Notification(
                    actor_content_type=ct,
                    actor_object_id=str(self.owner.pk),
                    recipient=self.borrower,
                    verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
                    emailed=True,
                )
                for _ in range(10)
            ]
        )

        max_seeded_pk = (
            Notification.objects.order_by("-pk").values_list("pk", flat=True).first()
        )

        # Trigger a real notification — email is throttled, digest is scheduled.
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.owner,
        )
        n = Notification.objects.filter(
            recipient=self.borrower,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            pk__gt=max_seeded_pk,
        ).get()
        n.refresh_from_db()
        self.assertIsInstance(n.data, dict)
        self.assertEqual(n.data["summary_digest"]["status"], "PENDING")

        # Move scheduled_for into the past so the command considers it due.
        past = (timezone.now() - timedelta(minutes=5)).isoformat()
        data = dict(n.data)
        data["summary_digest"]["scheduled_for"] = past
        Notification.objects.filter(pk=n.pk).update(data=data)

        mail.outbox = []
        call_command("send_summary_digests", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.borrower.email])
        n.refresh_from_db()
        self.assertEqual(n.data["summary_digest"]["status"], "SUCCESS")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_throttle_engages_after_ten_real_rows(self) -> None:
        """_is_email_throttled counts real DB rows; the cap fires when 10 exist."""
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(self.owner)
        Notification.objects.bulk_create(
            [
                Notification(
                    actor_content_type=ct,
                    actor_object_id=str(self.owner.pk),
                    recipient=self.borrower,
                    verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
                    emailed=True,
                )
                for _ in range(10)
            ]
        )

        max_seeded_pk = (
            Notification.objects.order_by("-pk").values_list("pk", flat=True).first()
        )
        Transaction.objects.create(
            item=self.item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.ACCEPTED,
            created_by=self.borrower,
            updated_by=self.owner,
        )
        n = Notification.objects.filter(
            recipient=self.borrower,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            pk__gt=max_seeded_pk,
        ).get()
        n.refresh_from_db()

        self.assertFalse(n.emailed)
        channels = (
            set(n.data.get("channels", {}).keys())
            if isinstance(n.data, dict)
            else set()
        )
        self.assertNotIn("EMAIL", channels)
        self.assertIn("APP", channels)


class NotificationPreferenceToggleViewTests(TestCase):
    """Tests for the toggle_preference and bulk_toggle_preferences endpoints."""

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user", email="user@example.com", password="password"
        )
        self.client.force_login(self.user)

    def _toggle(
        self, ntype: NotificationType, channel: str, enabled: bool
    ) -> HttpResponseBase:
        return self.client.post(
            "/settings/notifications/toggle/",
            {
                "notification_type": ntype.value,
                "channel": channel,
                "enabled": str(enabled).lower(),
            },
        )

    def _bulk_toggle(self, scope: str, channel: str, enabled: bool) -> HttpResponseBase:
        return self.client.post(
            "/settings/notifications/bulk-toggle/",
            {"scope": scope, "channel": channel, "enabled": str(enabled).lower()},
        )

    def test_toggle_creates_preference_row_on_first_call(self) -> None:
        """Toggling an optional type sets the stored value correctly."""

        response = self._toggle(NotificationType.ITEM_REQUEST_ACCEPTED, "EMAIL", False)
        self.assertEqual(response.status_code, 204)
        pref = NotificationPreference.objects.get(
            user=self.user,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
        )
        self.assertFalse(pref.email_enabled)

    def test_toggle_updates_existing_preference(self) -> None:
        """Toggling again flips the stored value."""
        NotificationPreference.objects.update_or_create(
            user=self.user,
            notification_type=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            defaults={
                "in_app_enabled": True,
                "email_enabled": True,
                "push_enabled": False,
            },
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
        pref_before = NotificationPreference.objects.get(
            user=self.user, notification_type=NotificationType.ITEM_REQUESTED.value
        )
        response = self._toggle(NotificationType.ITEM_REQUESTED, "EMAIL", False)
        self.assertEqual(response.status_code, 403)
        pref_after = NotificationPreference.objects.get(
            user=self.user, notification_type=NotificationType.ITEM_REQUESTED.value
        )
        self.assertEqual(pref_before.email_enabled, pref_after.email_enabled)

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
            NotificationPreference.objects.update_or_create(
                user=self.user,
                notification_type=ntype.value,
                defaults={
                    "in_app_enabled": True,
                    "email_enabled": True,
                    "push_enabled": False,
                },
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
        for user in (self.lender, self.borrower):
            NotificationPreference.objects.update_or_create(
                user=user,
                notification_type=NotificationType.ITEM_DISPUTED.value,
                defaults={
                    "in_app_enabled": True,
                    "email_enabled": True,
                    "push_enabled": False,
                },
            )

    def _create_transaction(
        self,
        status: TransactionStatus,
        dispute_raised_by: BorrowdUser | None = None,
    ) -> Transaction:
        with self.captureOnCommitCallbacks(execute=True):
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

        notifications: Notification = Notification.objects.filter(
            recipient=self.borrower,
            verb=NotificationType.ITEM_RETURN_REQUESTED.value,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Return requested")
        self.assertEqual(email.to, [self.borrower.email])
        self.assertIn("Test Drill", email.body)
        self.assertIn("requested", email.body)
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
        self.assertIn("Hi Lena", email.body)
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
        self.assertIn("Hi Bo", email.body)
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


class NotificationTypeTests(TestCase):
    def test_values_are_stable_database_keys(self) -> None:
        for notification_type in NotificationType:
            self.assertEqual(notification_type.value, notification_type.name)

    def test_every_type_has_a_message_template(self) -> None:
        for notification_type in NotificationType:
            self.assertTrue(notification_type.message_template)


class NewUserPreferenceInitTests(TestCase):
    """Creating a new user auto-populates NotificationPreference rows via init_new_user_preferences."""

    def _make_user(self) -> BorrowdUser:
        return BorrowdUser.objects.create_user(
            username="fresh", email="fresh@example.com", password="password"
        )

    def test_creates_rows_for_all_notification_types(self) -> None:
        """Every NotificationType value gets a preference row on signup."""
        user = self._make_user()
        pref_types = set(
            NotificationPreference.objects.filter(user=user).values_list(
                "notification_type", flat=True
            )
        )
        self.assertEqual(pref_types, set(NotificationType.values))

    def test_mandatory_types_are_enabled_by_default(self) -> None:
        """Mandatory types start with in_app and email enabled."""
        user = self._make_user()
        for ntype in NotificationType.mandatory_types():
            pref = NotificationPreference.objects.get(
                user=user, notification_type=ntype.value
            )
            self.assertTrue(pref.in_app_enabled, f"{ntype} in_app should be enabled")
            self.assertTrue(pref.email_enabled, f"{ntype} email should be enabled")

    def test_optional_types_are_disabled_by_default(self) -> None:
        """Optional types start with in_app and email Enabled."""
        user = self._make_user()
        mandatory = NotificationType.mandatory_types()
        for ntype in NotificationType:
            if ntype in mandatory:
                continue
            pref = NotificationPreference.objects.get(
                user=user, notification_type=ntype.value
            )
            self.assertTrue(pref.in_app_enabled, f"{ntype} in_app should be Enabled")
            self.assertTrue(pref.email_enabled, f"{ntype} email should be Enabled")

    def test_push_disabled_for_all_types(self) -> None:
        """Push is off for every type at signup."""
        user = self._make_user()
        self.assertFalse(
            NotificationPreference.objects.filter(user=user, push_enabled=True).exists()
        )


class BulkToggleCreatesRowsTests(TestCase):
    """bulk_toggle_preferences creates preference rows when they don't already exist."""

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user", email="user@example.com", password="password"
        )
        self.client.force_login(self.user)

    def test_bulk_enable_creates_rows_for_deleted_types(self) -> None:
        """Bulk-enabling a category creates rows for types that had been deleted."""
        optional_lending = [
            NotificationType.ITEM_REQUEST_ACCEPTED.value,
            NotificationType.ITEM_REQUEST_DENIED.value,
        ]
        NotificationPreference.objects.filter(
            user=self.user, notification_type__in=optional_lending
        ).delete()

        response = self.client.post(
            "/settings/notifications/bulk-toggle/",
            {"scope": "lending", "channel": "EMAIL", "enabled": "true"},
        )
        self.assertEqual(response.status_code, 204)

        for ntype_value in optional_lending:
            pref = NotificationPreference.objects.get(
                user=self.user, notification_type=ntype_value
            )
            self.assertTrue(
                pref.email_enabled, f"{ntype_value} email should be enabled"
            )


class NotificationInboxViewTests(TestCase):
    """Tests for the notification inbox view and unread count."""

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user", email="user@example.com", password="password"
        )
        self.client.force_login(self.user)

    def _make_notification(self, *, with_app_channel: bool) -> Notification:
        from notifications.signals import notify

        notify.send(
            self.user,
            recipient=[self.user],
            verb=NotificationType.ITEM_REQUESTED.value,
            description="test",
        )
        n = Notification.objects.filter(recipient=self.user).latest("timestamp")
        if with_app_channel:
            n.data = {
                "context": {},
                "icon": None,
                "channels": {"APP": {"status": "SUCCESS", "error": None}},
            }
            n.unread = True
        else:
            n.data = {
                "context": {},
                "icon": None,
                "channels": {"EMAIL": {"status": "SUCCESS", "error": None}},
            }
            n.unread = True
        n.save()
        NotificationMetadata.objects.update_or_create(
            notification=n,
            defaults={"visible_in_app": with_app_channel},
        )
        return n

    def test_unread_count_only_includes_app_channel_notifications(self) -> None:
        """Notifications without APP channel don't inflate the unread badge count."""
        self._make_notification(with_app_channel=False)
        response = self.client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unread_count"], 0)

    def test_unread_count_includes_app_channel_notifications(self) -> None:
        """Notifications with APP channel are counted in the unread badge."""
        self._make_notification(with_app_channel=True)
        response = self.client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unread_count"], 1)

    def test_inbox_excludes_non_app_channel_notifications(self) -> None:
        """Notifications routed only to EMAIL don't appear in the inbox list."""
        self._make_notification(with_app_channel=False)
        response = self.client.get("/notifications/")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_inbox_includes_app_channel_notifications(self) -> None:
        """Notifications routed to APP appear in the inbox list."""
        self._make_notification(with_app_channel=True)
        response = self.client.get("/notifications/")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_recent_notification_uses_relative_timestamp(self) -> None:
        """Notifications less than seven days old retain relative timestamps."""
        notification = self._make_notification(with_app_channel=True)
        Notification.objects.filter(pk=notification.pk).update(
            timestamp=timezone.now() - timedelta(days=6)
        )

        response = self.client.get("/notifications/")

        displayed = response.context["page_obj"].object_list[0]
        self.assertFalse(displayed.show_absolute_timestamp)

    def test_old_notification_uses_absolute_timestamp(self) -> None:
        """Notifications switch to an absolute date once seven days old."""
        notification = self._make_notification(with_app_channel=True)
        timestamp = timezone.now() - timedelta(days=8)
        Notification.objects.filter(pk=notification.pk).update(timestamp=timestamp)

        response = self.client.get("/notifications/")

        displayed = response.context["page_obj"].object_list[0]
        self.assertTrue(displayed.show_absolute_timestamp)
        local_timestamp = timezone.localtime(timestamp)
        expected_date = (
            f"{local_timestamp:%b} {local_timestamp.day}, {local_timestamp.year}"
        )
        self.assertContains(response, expected_date)

    def test_mark_notification_read_rejects_hidden_notification(self) -> None:
        """A notification outside the inbox cannot be changed via its read endpoint."""
        notification = self._make_notification(with_app_channel=False)

        response = self.client.post(f"/notifications/{notification.pk}/read/")

        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_only_updates_visible_notifications(self) -> None:
        """Mark-all leaves non-app notification state untouched."""
        visible = self._make_notification(with_app_channel=True)
        hidden = self._make_notification(with_app_channel=False)

        response = self.client.post("/notifications/read-all/")

        self.assertEqual(response.status_code, 302)
        visible.refresh_from_db()
        hidden.refresh_from_db()
        self.assertFalse(visible.unread)
        self.assertTrue(hidden.unread)


class NotificationDeleteTests(TestCase):
    """Tests for remove_app_notification and remove_all_app_notifications."""

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="user", email="user@example.com", password="password"
        )
        self.client.force_login(self.user)

    def _make_app_notification(self) -> Notification:
        from notifications.signals import notify

        notify.send(
            self.user,
            recipient=[self.user],
            verb=NotificationType.ITEM_REQUESTED.value,
            description="test",
        )
        n = Notification.objects.filter(recipient=self.user).latest("timestamp")
        n.data = {
            "context": {},
            "icon": None,
            "channels": {"APP": {"status": "SUCCESS", "error": None}},
        }
        n.unread = True
        n.save()
        NotificationMetadata.objects.update_or_create(
            notification=n,
            defaults={"visible_in_app": True},
        )
        return n

    def test_remove_notification_hides_app_metadata(self) -> None:
        """Deleting a notification hides it without changing dispatch data."""
        n = self._make_app_notification()
        response = self.client.post(f"/notifications/{n.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        n.refresh_from_db()
        n.borrowd_metadata.refresh_from_db()
        self.assertFalse(n.borrowd_metadata.visible_in_app)
        self.assertIn("APP", (n.data or {}).get("channels", {}))
        self.assertFalse(n.unread)

    def test_remove_notification_disappears_from_inbox(self) -> None:
        """After deletion, the notification no longer appears in the inbox list."""
        n = self._make_app_notification()
        self.client.post(f"/notifications/{n.pk}/delete/")
        response = self.client.get("/notifications/")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_remove_all_notifications_clears_inbox(self) -> None:
        """Delete-all removes every APP notification from the inbox."""
        self._make_app_notification()
        self._make_app_notification()
        response = self.client.post("/notifications/delete-all/")
        self.assertEqual(response.status_code, 302)
        inbox_response = self.client.get("/notifications/")
        self.assertEqual(inbox_response.context["page_obj"].paginator.count, 0)

    def test_remove_notification_from_other_user_returns_404(self) -> None:
        """Cannot delete another user's notification."""
        other = BorrowdUser.objects.create_user(
            username="other", email="other@example.com", password="password"
        )
        n = self._make_app_notification()
        self.client.force_login(other)
        response = self.client.post(f"/notifications/{n.pk}/delete/")
        self.assertEqual(response.status_code, 404)

    def test_remove_hidden_notification_returns_404(self) -> None:
        """A notification already hidden from the inbox cannot be removed again."""
        notification = self._make_app_notification()
        NotificationMetadata.objects.filter(notification=notification).update(
            visible_in_app=False
        )

        response = self.client.post(f"/notifications/{notification.pk}/delete/")

        self.assertEqual(response.status_code, 404)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SummaryDigestTests(TestCase):
    """Tests for NotificationService.send_pending_digests() and the management command."""

    def setUp(self) -> None:
        mail.outbox = []
        self.sender = BorrowdUser.objects.create_user(
            username="sender",
            email="sender@example.com",
            password="password",
            first_name="Alice",
        )
        self.recipient = BorrowdUser.objects.create_user(
            username="recipient",
            email="recipient@example.com",
            password="password",
            first_name="Bob",
        )

    def _make_pending_digest_notification(
        self,
        recipient: BorrowdUser | None = None,
        scheduled_for_delta: timedelta = timedelta(minutes=-5),
        status: str = "PENDING",
    ) -> Notification:
        """Insert a notification row carrying a summary_digest entry."""
        if recipient is None:
            recipient = self.recipient
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(self.sender)
        n = Notification.objects.create(
            actor_content_type=ct,
            actor_object_id=str(self.sender.pk),
            recipient=recipient,
            verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
            description="Item request accepted",
        )
        Notification.objects.filter(pk=n.pk).update(
            data={
                "summary_digest": {
                    "recipient_id": recipient.pk,
                    "scheduled_for": (timezone.now() + scheduled_for_delta).isoformat(),
                    "status": status,
                }
            }
        )
        n.refresh_from_db()
        return n

    def test_returns_zero_with_no_pending_digests(self) -> None:
        """Returns 0 and sends no email when there are no pending digests."""
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_sends_email_for_due_pending_digest(self) -> None:
        """A pending digest past its scheduled_for time is emailed to the recipient."""
        self._make_pending_digest_notification()
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.recipient.email])

    def test_marks_notification_success_after_send(self) -> None:
        """After a successful send the summary_digest.status on the row is SUCCESS."""
        n = self._make_pending_digest_notification()
        NotificationService.send_pending_digests()
        n.refresh_from_db()
        self.assertEqual(n.data["summary_digest"]["status"], "SUCCESS")

    def test_email_addresses_recipient_by_first_name(self) -> None:
        """The digest email body includes the recipient's first name."""
        self._make_pending_digest_notification()
        NotificationService.send_pending_digests()
        self.assertIn("Bob", mail.outbox[0].body)

    def test_skips_digest_not_yet_due(self) -> None:
        """A pending digest whose scheduled_for is still in the future is not sent."""
        self._make_pending_digest_notification(scheduled_for_delta=timedelta(hours=1))
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_already_succeeded_digest(self) -> None:
        """A digest already marked SUCCESS is not re-sent."""
        self._make_pending_digest_notification(status="SUCCESS")
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_batches_multiple_notifications_per_recipient_into_one_email(self) -> None:
        """Multiple due digests for the same recipient are sent as a single email."""
        for _ in range(3):
            self._make_pending_digest_notification()
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_sends_separate_email_per_recipient(self) -> None:
        """Each recipient with due digests gets their own email."""
        other = BorrowdUser.objects.create_user(
            username="other",
            email="other@example.com",
            password="p",
            first_name="Carol",
        )
        self._make_pending_digest_notification(recipient=self.recipient)
        self._make_pending_digest_notification(recipient=other)
        sent = NotificationService.send_pending_digests()
        self.assertEqual(sent, 2)
        self.assertEqual(len(mail.outbox), 2)
        sent_to = {m.to[0] for m in mail.outbox}
        self.assertEqual(sent_to, {self.recipient.email, other.email})

    def test_marks_notification_error_when_send_fails(self) -> None:
        """When send_mail raises, the row's summary_digest.status is set to ERROR."""
        n = self._make_pending_digest_notification()
        with patch(
            "borrowd_notifications.services.send_mail",
            side_effect=Exception("SMTP down"),
        ):
            NotificationService.send_pending_digests()
        n.refresh_from_db()
        self.assertEqual(n.data["summary_digest"]["status"], "ERROR")

    def test_failure_for_one_recipient_does_not_block_others(self) -> None:
        """A send failure for one recipient does not prevent digests for others."""
        other = BorrowdUser.objects.create_user(
            username="other2",
            email="other2@example.com",
            password="p",
            first_name="Dave",
        )
        n1 = self._make_pending_digest_notification(recipient=self.recipient)
        n2 = self._make_pending_digest_notification(recipient=other)

        call_count = 0

        def fail_first(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("SMTP down")

        with patch("borrowd_notifications.services.send_mail", side_effect=fail_first):
            NotificationService.send_pending_digests()

        n1.refresh_from_db()
        n2.refresh_from_db()
        statuses = {
            n1.data["summary_digest"]["status"],
            n2.data["summary_digest"]["status"],
        }
        self.assertIn("ERROR", statuses)
        self.assertIn("SUCCESS", statuses)

    def test_notification_description_used_as_fallback_when_context_unavailable(
        self,
    ) -> None:
        """Falls back to notification.description when the template context can't be built."""
        self._make_pending_digest_notification()
        NotificationService.send_pending_digests()
        # No target set on the notification so context is empty; description is the fallback.
        self.assertIn("Item request accepted", mail.outbox[0].body)

    def test_management_command_outputs_sent_count(self) -> None:
        """The management command prints the number of digests sent."""
        from io import StringIO

        from django.core.management import call_command

        self._make_pending_digest_notification()
        out = StringIO()
        call_command("send_summary_digests", stdout=out)
        self.assertIn("1", out.getvalue())
