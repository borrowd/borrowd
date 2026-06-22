from dataclasses import dataclass
from typing import Any, Dict

from django.conf import settings
from django.db import models
from django.db.models import (
    CASCADE,
    ForeignKey,
    Model,
    TextChoices,
)
from django.urls import reverse

# from .base.models import AbstractNotification
from notifications.models import Notification

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser


class NotificationType(models.TextChoices):
    """Notification types emitted by the application.

    Enum values are persisted as database keys. Renaming a value requires a data
    migration for notifications and notification preferences.
    """

    # Lending lifecycle
    ITEM_REQUESTED = "ITEM_REQUESTED"
    ITEM_REQUEST_ACCEPTED = "ITEM_REQUEST_ACCEPTED"
    ITEM_REQUEST_DENIED = "ITEM_REQUEST_DENIED"
    COLLECTION_ASSERTED = "COLLECTION_ASSERTED"
    COLLECTION_CONFIRMED = "COLLECTION_CONFIRMED"
    RETURN_ASSERTED = "RETURN_ASSERTED"
    RETURN_CONFIRMED = "RETURN_CONFIRMED"

    # Item availability
    ITEM_NOTIFY_WHEN_AVAILABLE = "ITEM_NOTIFY_WHEN_AVAILABLE"
    ITEM_SUBSCRIPTION = "ITEM_SUBSCRIPTION"
    ITEM_RETURN_REQUESTED = "ITEM_RETURN_REQUESTED"
    ITEM_DISPUTED = "ITEM_DISPUTED"

    # Group & membership
    GROUP_MEMBER_JOINED = "GROUP_MEMBER_JOINED"
    GROUP_NEEDS_MODERATOR = "GROUP_NEEDS_MODERATOR"
    MEMBERSHIP_PENDING = "MEMBERSHIP_PENDING"
    MEMBERSHIP_APPROVED = "MEMBERSHIP_APPROVED"

    # Community wishlist
    COMMUNITY_REQUEST_POSTED = "COMMUNITY_REQUEST_POSTED"
    COMMUNITY_REQUEST_FULFILLED = "COMMUNITY_REQUEST_FULFILLED"

    REQUEST_CANCELLED_BORROWER_LEFT = "REQUEST_CANCELLED_BORROWER_LEFT"
    REQUEST_CANCELLED_OWNER_LEFT = "REQUEST_CANCELLED_OWNER_LEFT"
    LOAN_ENDED_OWNER_LEFT = "LOAN_ENDED_OWNER_LEFT"

    @classmethod
    def mandatory_types(cls) -> "frozenset[NotificationType]":
        return frozenset(
            {
                cls.ITEM_REQUESTED,
                cls.COLLECTION_ASSERTED,
                cls.RETURN_ASSERTED,
                cls.MEMBERSHIP_PENDING,
                cls.ITEM_RETURN_REQUESTED,
            }
        )

    def __str__(self) -> str:
        return self.name.lower()

    @property
    def message_template(self) -> str:
        return _MESSAGE_TEMPLATES[self]

    # TODO simplify the logic to make it cleaner.
    @staticmethod
    def _get_template_context_for(notification: Notification) -> Dict[str, Any]:
        """Extract context from the notification's action_object."""
        context = {}
        if notification.verb in (
            NotificationType.REQUEST_CANCELLED_BORROWER_LEFT.value,
            NotificationType.REQUEST_CANCELLED_OWNER_LEFT.value,
            NotificationType.LOAN_ENDED_OWNER_LEFT.value,
        ) and isinstance(notification.target, Transaction):
            return {
                "recipient_name": notification.recipient.first_name,
                "item_name": notification.target.item.name,
                "actor_name": notification.actor.first_name,
            }
        if isinstance(notification.target, Transaction):
            transaction: Transaction = notification.target
            match transaction.status:
                case TransactionStatus.REQUESTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.first_name,
                            "respond_url": settings.BASE_URL
                            + reverse("item-detail", args=[transaction.item.pk]),
                        }
                    )
                case TransactionStatus.ACCEPTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.first_name,
                            "item_owner_email": transaction.party1.email,
                        }
                    )
                case TransactionStatus.REJECTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.first_name,
                        }
                    )
                case (
                    TransactionStatus.COLLECTION_ASSERTED
                    | TransactionStatus.RETURN_ASSERTED
                ):
                    context.update(
                        {
                            "requester_name": notification.actor.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": notification.recipient.first_name,
                        }
                    )
                case TransactionStatus.COLLECTED:
                    context.update(
                        {
                            "requester_name": notification.recipient.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": notification.actor.first_name,
                        }
                    )
                case TransactionStatus.RETURNED:
                    context.update(
                        {
                            "requester_name": notification.recipient.first_name,
                            "item_name": transaction.item.name,
                            "item_owner_name": notification.actor.first_name,
                        }
                    )
                case TransactionStatus.RETURN_REQUESTED:
                    context.update(
                        {
                            "borrower_name": transaction.party2.first_name,
                            "owner_name": transaction.party1.first_name,
                            "item_name": transaction.item.name,
                            "inventory_url": settings.BASE_URL
                            + reverse("profile-inventory"),
                        }
                    )
                case TransactionStatus.DISPUTED:
                    context.update(
                        {
                            "recipient_name": notification.recipient.first_name,
                            "item_name": transaction.item.name,
                            "dispute_raiser_name": notification.actor.first_name,
                        }
                    )
        elif isinstance(notification.target, BorrowdGroup):
            if notification.verb == NotificationType.GROUP_NEEDS_MODERATOR.value:
                context.update(
                    {
                        "group_member_name": notification.recipient.first_name,
                        "group_name": notification.target.name,
                        "actor_name": notification.actor.first_name,
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
                        "group_member_name": notification.recipient.first_name,
                        "new_member_name": membership.user.first_name,
                        "group_name": membership.group.name,
                    }
                )
        elif isinstance(notification.target, AvailabilitySubscription):
            subscription: AvailabilitySubscription = notification.target
            base_url = settings.BASE_URL.rstrip("/")
            if notification.verb == NotificationType.ITEM_SUBSCRIPTION.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.first_name,
                        "item_name": subscription.item.name,
                        "item_url": base_url
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
            elif notification.verb == NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.first_name,
                        "item_name": subscription.item.name,
                        "owner_name": subscription.item.owner.first_name,
                        "item_url": base_url
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
        return context


_MESSAGE_TEMPLATES: dict[NotificationType, str] = {
    NotificationType.ITEM_REQUESTED: "{requester_name} wants to borrow your {item_name}",
    NotificationType.ITEM_REQUEST_ACCEPTED: "{item_owner_name} accepted your request for {item_name}",
    NotificationType.ITEM_REQUEST_DENIED: "{item_owner_name} declined your request for {item_name}",
    NotificationType.COLLECTION_ASSERTED: "{requester_name} says they have collected {item_name}",
    NotificationType.COLLECTION_CONFIRMED: "{item_owner_name} confirmed collection of {item_name}",
    NotificationType.RETURN_ASSERTED: "{requester_name} says they have returned {item_name}",
    NotificationType.RETURN_CONFIRMED: "{item_owner_name} confirmed the return of {item_name}",
    NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE: "{owner_name} has {item_name} available to borrow",
    NotificationType.ITEM_SUBSCRIPTION: "{subscriber_name} subscribed to be notified when {item_name} becomes available",
    NotificationType.ITEM_RETURN_REQUESTED: "{owner_name} requested the return of {item_name}",
    NotificationType.ITEM_DISPUTED: "{dispute_raiser_name} raised a dispute over {item_name}",
    NotificationType.GROUP_MEMBER_JOINED: "{new_member_name} joined {group_name}",
    NotificationType.GROUP_NEEDS_MODERATOR: "{actor_name} left {group_name} — the group needs a moderator",
    NotificationType.MEMBERSHIP_PENDING: "{new_member_name} has requested to join {group_name}",
    NotificationType.MEMBERSHIP_APPROVED: "{group_name} approved your membership",
    NotificationType.COMMUNITY_REQUEST_POSTED: "A new community request was posted in {group_name}",
    NotificationType.COMMUNITY_REQUEST_FULFILLED: "A community request in {group_name} was fulfilled",
    NotificationType.REQUEST_CANCELLED_BORROWER_LEFT: "{actor_name}'s borrow request for {item_name} was cancelled",
    NotificationType.REQUEST_CANCELLED_OWNER_LEFT: "{actor_name} left — your request for {item_name} was cancelled",
    NotificationType.LOAN_ENDED_OWNER_LEFT: "{actor_name} left — your loan of {item_name} has ended",
}


class ChannelType(TextChoices):
    """Channel type, and uses labels as field name in the Preferences table"""

    APP = "APP", "in_app_enabled"
    EMAIL = "EMAIL", "email_enabled"
    PUSH = "PUSH", "push_enabled"


class NotificationPreference(Model):
    """
    To add a new channel:
        1. Add a value to ChannelType above — label must match the field name below (used as setattr key in views.py).
        2. Add a BooleanField here for the new channel (e.g. sms_enabled).
        3. Create and apply a migration.
        4. Add a NotificationStrategy subclass in channels.py and wire it into NotificationService._get_strategy_for() in services.py.
        5. Add the channel column to the preferences UI in templates/notifications/preferences.html.
        6. For channels that require external credentials (like PUSH), guard the send() call with a settings check.
    """

    user: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        null=False,
        blank=False,
        on_delete=CASCADE,
        related_name="notifications_preferences",
        help_text="The user who owns these preferences",
    )
    notification_type: models.CharField[str, str] = models.CharField(
        max_length=100, choices=NotificationType.choices
    )
    in_app_enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    email_enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    push_enabled: models.BooleanField[bool, bool] = models.BooleanField(default=False)

    @staticmethod
    def init_new_user_preferences(user: BorrowdUser) -> None:
        """When a new user is created, the preferences must be initialised."""

        for notification_type in NotificationType.values:
            NotificationPreference.objects.update_or_create(
                user=user,
                notification_type=notification_type,
                defaults={
                    "in_app_enabled": True,
                    "email_enabled": True,
                    "push_enabled": False,
                },
            )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "notification_type"],
                name="unique_notification_preference",
            )
        ]


class NotificationMetadata(Model):
    """Borrow'd-specific state for a third-party notification."""

    notification: models.OneToOneField[Notification] = models.OneToOneField(
        Notification,
        on_delete=CASCADE,
        related_name="borrowd_metadata",
    )
    visible_in_app: models.BooleanField[bool, bool] = models.BooleanField(
        default=False,
        db_index=True,
    )


class NotificationState(TextChoices):
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    ERROR = "ERROR"


@dataclass
class ChannelResult:
    status: NotificationState
    error: str | None = None


@dataclass
class NotificationData:
    context: dict[str, Any]
    icon: str | None
    channels: dict[ChannelType, ChannelResult]

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        icon: str | None = None,
        channels: dict[ChannelType, ChannelResult] | None = None,
    ) -> None:
        if data is not None:
            context = dict(data.get("context", {}))
            icon = data.get("icon")
            channels = {
                ChannelType(channel): (
                    result
                    if isinstance(result, ChannelResult)
                    else ChannelResult(
                        status=NotificationState(result["status"]),
                        error=result.get("error"),
                    )
                )
                for channel, result in data.get("channels", {}).items()
            }

        self.context = context or {}
        self.icon = icon
        self.channels = channels or {}

    @property
    def status(self) -> NotificationState:
        statuses = {r.status for r in self.channels.values()}
        if NotificationState.ERROR in statuses:
            return NotificationState.ERROR
        if NotificationState.PENDING in statuses:
            return NotificationState.PENDING
        return NotificationState.SUCCESS

    def _error(self, channel: ChannelType, error: str) -> None:
        self.channels[channel] = ChannelResult(
            status=NotificationState.ERROR,
            error=error,
        )

    def _success(self, channel: ChannelType) -> None:
        self.channels[channel] = ChannelResult(status=NotificationState.SUCCESS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context,
            "icon": self.icon,
            "channels": {
                channel.value: {"status": result.status.value, "error": result.error}
                for channel, result in self.channels.items()
            },
        }

    @classmethod
    def create(
        cls, context: dict[str, Any], channels: set[ChannelType]
    ) -> "NotificationData":
        return cls(
            context=context,
            icon=None,
            channels={
                ch: ChannelResult(status=NotificationState.PENDING) for ch in channels
            },
        )
