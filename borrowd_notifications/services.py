from typing import Any, Dict, Type

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from notifications.models import Notification

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    Transaction,
    TransactionStatus,
)
from borrowd_notifications.channels import (
    AppNotificationStrategy,
    EmailNotificationStrategy,
    NotificationPayload,
    NotificationStrategy,
    PUSHNotificationStrategy,
)
from borrowd_notifications.models import (
    ChannelType,
    NotificationPreference,
    NotificationType,
)
from borrowd_users.models import BorrowdUser


class NotificationService:
    """Service for sending notifications."""

    _strategies: dict[ChannelType, Type[NotificationStrategy]] = {
        ChannelType.APP: AppNotificationStrategy,
        ChannelType.EMAIL: EmailNotificationStrategy,
        ChannelType.PUSH: PUSHNotificationStrategy,
    }

    @classmethod
    def get_strategy(cls, channel: ChannelType) -> NotificationStrategy:
        try:
            strategy = cls._strategies[channel]
        except KeyError:
            raise Exception(f"Unknown notification strategy {channel}")

        return strategy()

    @staticmethod
    def _get_user_preferences(
        user: BorrowdUser, notification_type: NotificationType
    ) -> set[ChannelType]:
        """Return the user preferences for a specific notification type."""

        preferences = NotificationPreference.objects.filter(
            Q(user=user) & Q(notification_type=notification_type)
        )

        result = set()

        for pref in preferences:
            result.add(ChannelType(pref.channel))

        return result

    @classmethod
    def send_notification(
        cls,
        notification: Notification,
    ) -> None:
        """Send the notification through the right channel"""

        notification_preferences = NotificationService._get_user_preferences(
            notification.recipient, notification.verb
        )
        notification_payload = NotificationPayload.from_notification(
            notification, channels=notification_preferences
        )

        for channel in notification_preferences:
            strategy = cls.get_strategy(channel)
            strategy.send(notification_payload)

        notification.data = notification_payload.data
        notification.save()

    @staticmethod
    def _get_template_context_for(notification: Notification) -> Dict[str, Any]:
        """Extract context from the notification's action_object."""
        context = {}
        if isinstance(notification.target, Transaction):
            transaction: Transaction = notification.target
            match transaction.status:
                case TransactionStatus.REQUESTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),  # type: ignore[attr-defined]
                            "item_name": transaction.item.name,  # type: ignore[attr-defined]
                            "item_owner_name": transaction.party1.profile.full_name(),  # type: ignore[attr-defined]
                            "respond_url": settings.BASE_URL
                            + reverse("item-detail", args=[transaction.item.pk]),  # type: ignore[attr-defined]
                        }
                    )
                case TransactionStatus.ACCEPTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),  # type: ignore[attr-defined]
                            "item_name": transaction.item.name,  # type: ignore[attr-defined]
                            "item_owner_name": transaction.party1.profile.full_name(),  # type: ignore[attr-defined]
                            "item_owner_email": transaction.party1.email,  # type: ignore[attr-defined]
                        }
                    )
                case TransactionStatus.REJECTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),  # type: ignore[attr-defined]
                            "item_name": transaction.item.name,  # type: ignore[attr-defined]
                        }
                    )
                case TransactionStatus.RETURNED:
                    context.update(
                        {
                            "item_owner_name": transaction.party1.profile.full_name(),  # type: ignore[attr-defined]
                            "requester_name": transaction.party2.profile.full_name(),  # type: ignore[attr-defined]
                            "item_name": transaction.item.name,  # type: ignore[attr-defined]
                        }
                    )
        elif isinstance(notification.target, BorrowdGroup):
            if notification.verb == NotificationType.GROUP_NEEDS_MODERATOR.value:
                context.update(
                    {
                        "group_member_name": notification.recipient.profile.full_name(),
                        "group_name": notification.target.name,
                        "group_url": settings.BASE_URL
                        + reverse(
                            "borrowd_groups:group-detail", args=[notification.target.pk]
                        ),
                    }
                )
            else:
                membership: Membership = notification.action_object
                context.update(
                    {
                        "group_member_name": notification.recipient.profile.full_name(),
                        "new_member_name": membership.user.profile.full_name(),  # type: ignore[attr-defined]
                        "group_name": membership.group.name,  # type: ignore[attr-defined]
                    }
                )
        elif isinstance(notification.target, AvailabilitySubscription):
            subscription: AvailabilitySubscription = notification.target

            if notification.verb == NotificationType.ITEM_SUBSCRIPTION.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),  # type: ignore[attr-defined]
                        "item_name": subscription.item.name,  # type: ignore[attr-defined]
                        "item_url": settings.BASE_URL
                        + reverse("item-detail", args=[subscription.item.pk]),  # type: ignore[attr-defined]
                    }
                )
            elif notification.verb == NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),  # type: ignore[attr-defined]
                        "item_name": subscription.item.name,  # type: ignore[attr-defined]
                        "item_url": settings.BASE_URL
                        + reverse("item-detail", args=[subscription.item.pk]),  # type: ignore[attr-defined]
                    }
                )
        return context
