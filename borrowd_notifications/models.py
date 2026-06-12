from dataclasses import dataclass
from typing import Any, Dict

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
    ITEM_REQUESTED = "Item requested"
    ITEM_REQUEST_ACCEPTED = "Item request accepted"
    ITEM_REQUEST_DENIED = "Item request denied"
    COLLECTION_ASSERTED = "Collection asserted"
    COLLECTION_CONFIRMED = "Collection confirmed"
    RETURN_ASSERTED = "Return asserted"
    RETURN_CONFIRMED = "Return confirmed"
    ITEM_RETURNED = "Item returned"

    # Item availability
    ITEM_NOTIFY_WHEN_AVAILABLE = "Item notify when available"
    ITEM_SUBSCRIPTION = "Item subscription"

    # Group & membership
    GROUP_MEMBER_JOINED = "Change to group membership"
    GROUP_NEEDS_MODERATOR = "Group needs moderator"
    MEMBERSHIP_PENDING = "Membership pending"
    MEMBERSHIP_APPROVED = "Membership approved"

    # Community wishlist
    COMMUNITY_REQUEST_POSTED = "Community request posted"
    COMMUNITY_REQUEST_FULFILLED = "Community request fulfilled"

    REQUEST_CANCELLED_BORROWER_LEFT = "Request cancelled - borrower left"  # When borrower closes account with an open request
    REQUEST_CANCELLED_OWNER_LEFT = "Request cancelled - owner left"  # When owner closes account with an open request
    LOAN_ENDED_OWNER_LEFT = (
        "Loan ended - owner left"  # When owner closes account with an active loan
    )

    @classmethod
    def mandatory_types(cls) -> "frozenset[NotificationType]":
        return frozenset(
            {
                cls.ITEM_REQUESTED,
                cls.COLLECTION_ASSERTED,
                cls.RETURN_ASSERTED,
                cls.MEMBERSHIP_PENDING,
            }
        )

    def __str__(self) -> str:
        return self.name.lower()

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
                "item_name": notification.target.item.name,  # type: ignore[attr-defined]
            }
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
                case (
                    TransactionStatus.COLLECTION_ASSERTED
                    | TransactionStatus.COLLECTED
                    | TransactionStatus.RETURN_ASSERTED
                ):
                    context.update(
                        {
                            "requester_name": transaction.party2.profile.full_name(),  # type: ignore[attr-defined]
                            "item_name": transaction.item.name,  # type: ignore[attr-defined]
                            "item_owner_name": transaction.party1.profile.full_name(),  # type: ignore[attr-defined]
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


class ChannelType(TextChoices):
    APP = "APP", "In-App Notification"
    PUSH = "PUSH", "Push Notification"
    EMAIL = "EMAIL", "Email"


class NotificationPreference(Model):
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
