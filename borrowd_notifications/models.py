from dataclasses import dataclass
from typing import Any, Dict

# from .base.models import AbstractNotification
import notifications
from django.conf import settings
from django.db import models
from django.db.models import (
    CASCADE,
    ForeignKey,
    Model,
    TextChoices,
)
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    Transaction,
    TransactionStatus,
)
from borrowd_users.models import BorrowdUser


class NotificationType(models.TextChoices):
    # Lending lifecycle
    ITEM_REQUESTED = (
        "Item requested",
        "{requester_name} wants to borrow your {item_name}",
    )
    ITEM_REQUEST_ACCEPTED = (
        "Item request accepted",
        "Your request for {item_name} was accepted by {item_owner_name}",
    )
    ITEM_REQUEST_DENIED = (
        "Item request denied",
        "Your request for {item_name} was declined",
    )
    COLLECTION_ASSERTED = (
        "Collection asserted",
        "{requester_name} says they have collected {item_name}",
    )
    COLLECTION_CONFIRMED = (
        "Collection confirmed",
        "Collection of {item_name} has been confirmed",
    )
    RETURN_ASSERTED = (
        "Return asserted",
        "{requester_name} says they have returned {item_name}",
    )
    RETURN_CONFIRMED = "Return confirmed", "Return of {item_name} has been confirmed"

    # Item availability
    ITEM_NOTIFY_WHEN_AVAILABLE = (
        "Item notify when available",
        "{item_name} is now available to borrow",
    )
    ITEM_SUBSCRIPTION = (
        "Item subscription",
        "{subscriber_name} wants to be notified when {item_name} is available",
    )
    ITEM_RETURN_REQUESTED = (
        "Item return requested",
        "The owner of {item_name} has requested to get it back. Please coordinate with them the return of this item.",
    )
    ITEM_DISPUTED = ("Item disputed", "This item has escalated to a dispute!")

    # Group & membership
    GROUP_MEMBER_JOINED = (
        "A member joined a group you're part of",
        "{new_member_name} joined {group_name}",
    )
    GROUP_NEEDS_MODERATOR = "Group needs moderator", "{group_name} needs a moderator"
    MEMBERSHIP_PENDING = (
        "Membership pending",
        "{new_member_name} has requested to join {group_name}",
    )
    MEMBERSHIP_APPROVED = (
        "Membership approved",
        "Your membership to {group_name} was approved",
    )

    # Community wishlist
    COMMUNITY_REQUEST_POSTED = (
        "Community request posted",
        "A new community request was posted in {group_name}",
    )
    COMMUNITY_REQUEST_FULFILLED = (
        "Community request fulfilled",
        "A community request in {group_name} was fulfilled",
    )

    REQUEST_CANCELLED_BORROWER_LEFT = (
        "Request cancelled - borrower left",
        "Your borrow request for {item_name} was cancelled",
    )
    REQUEST_CANCELLED_OWNER_LEFT = (
        "Request cancelled - owner left",
        "Your request for {item_name} was cancelled because the owner left",
    )
    LOAN_ENDED_OWNER_LEFT = (
        "Loan ended - owner left",
        "Your loan of {item_name} has ended because the owner left",
    )

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
        return str(self.label)

    # TODO simplify the logic to make it cleaner.
    @staticmethod
    def _get_template_context_for(notification: notifications) -> Dict[str, Any]:
        """Extract context from the notification's action_object."""
        context = {}
        if notification.verb in (
            NotificationType.REQUEST_CANCELLED_BORROWER_LEFT.value,
            NotificationType.REQUEST_CANCELLED_OWNER_LEFT.value,
            NotificationType.LOAN_ENDED_OWNER_LEFT.value,
        ) and isinstance(notification.target, Transaction):
            return {
                "recipient_name": notification.recipient.profile.full_name(),
                "item_name": notification.target.item.name,
            }
        if isinstance(notification.target, Transaction):
            transaction: Transaction = notification.target
            match transaction.status:
                case TransactionStatus.REQUESTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.profile.full_name(),
                            "respond_url": settings.BASE_URL
                            + reverse("item-detail", args=[transaction.item.pk]),
                        }
                    )
                case TransactionStatus.ACCEPTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.profile.full_name(),
                            "item_owner_email": transaction.party1.email,
                        }
                    )
                case TransactionStatus.REJECTED:
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                        }
                    )
                case (
                    TransactionStatus.COLLECTION_ASSERTED
                    | TransactionStatus.COLLECTED
                    | TransactionStatus.RETURN_ASSERTED
                ):
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                            "item_owner_name": transaction.party1.profile.full_name(),
                        }
                    )
                case TransactionStatus.RETURNED:
                    context.update(
                        {
                            "item_owner_name": transaction.party1.profile.full_name(),
                            "requester_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                        }
                    )
                case TransactionStatus.RETURN_REQUESTED:
                    context.update(
                        {
                            "borrower_name": transaction.party2.profile.full_name(),
                            "item_name": transaction.item.name,
                            "inventory_url": settings.BASE_URL
                            + reverse("profile-inventory"),
                        }
                    )
                case TransactionStatus.DISPUTED:
                    context.update(
                        {
                            "recipient_name": notification.recipient.profile.full_name(),
                            "item_name": transaction.item.name,
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
                        "new_member_name": membership.user.profile.full_name(),
                        "group_name": membership.group.name,
                    }
                )
        elif isinstance(notification.target, AvailabilitySubscription):
            subscription: AvailabilitySubscription = notification.target
            base_url = settings.BASE_URL.rstrip("/")
            if notification.verb == NotificationType.ITEM_SUBSCRIPTION.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),
                        "item_name": subscription.item.name,
                        "item_url": base_url
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
            elif notification.verb == NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),
                        "item_name": subscription.item.name,
                        "item_url": base_url
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
        return context


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
            mandatory = (
                True
                if notification_type in NotificationType.mandatory_types()
                else False
            )

            NotificationPreference.objects.create(
                user=user,
                notification_type=notification_type,
                in_app_enabled=mandatory | False,
                email_enabled=mandatory | False,
                push_enabled=False,
            )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "notification_type"],
                name="unique_notification_preference",
            )
        ]


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
