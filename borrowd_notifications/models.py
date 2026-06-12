from dataclasses import dataclass
from typing import Any

from django.db import models
from django.db.models import (
    CASCADE,
    ForeignKey,
    IntegerChoices,
    IntegerField,
    Model,
    TextChoices,
)

from borrowd_users.models import BorrowdUser


class NotificationType(IntegerChoices):
    ITEM_REQUESTED = 10, "Item requested"
    ITEM_REQUEST_ACCEPTED = 15, "Item request accepted"
    ITEM_REQUEST_DENIED = 20, "Item request denied"
    ITEM_NOTIFY_WHEN_AVAILABLE = (
        25,
        "Item notify when available",
    )  # When the item becomes available
    ITEM_SUBSCRIPTION = (
        30,
        "Item subscription",
    )  # When a user subscribes to notifications for an item

    ITEM_RETURNED = 35, "Item returned"
    GROUP_MEMBER_JOINED = 40, "Change to group membership"
    GROUP_NEEDS_MODERATOR = 45, "Group needs moderator"  # When moderator leaves group

    # TODO implement the context build here instead of inside the service to keep the logic in one place.

    def __str__(self) -> str:
        return self.name.lower()


class ChannelType(TextChoices):
    APP = "APP", "In-App Notification"
    PUSH = "PUSH", "Push Notification"
    EMAIL = "EMAIL", "Email"


class NotificationPreference(Model):
    user: ForeignKey["BorrowdUser"] = ForeignKey(
        to="BorrowdUser",
        on_delete=CASCADE,
        related_name="notifications_preferences",
        help_text="The user who owns thoses preferences",
    )
    notification_type: IntegerField[NotificationType, int] = IntegerField(
        choices=NotificationType
    )
    channel: models.CharField[ChannelType, str] = models.CharField(
        max_length=20, choices=ChannelType.choices, default=ChannelType.APP, blank=False
    )


class NotificationState(TextChoices):
    SUCCES = "SUCCES"
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
        return NotificationState.SUCCES

    def _error(self, channel: ChannelType, error: str) -> None:
        self.channels[channel] = ChannelResult(
            status=NotificationState.ERROR,
            error=error,
        )

    def _success(self, channel: ChannelType) -> None:
        self.channels[channel] = ChannelResult(status=NotificationState.SUCCES)

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
