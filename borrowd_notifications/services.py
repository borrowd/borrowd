from typing import Type

from django.db.models import Q
from notifications.models import Notification

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
