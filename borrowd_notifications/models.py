from typing import Never

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    CASCADE,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerChoices,
    IntegerField,
    JSONField,
    Model,
    TextChoices,
    TextField,
)
from django.urls import reverse

from borrowd_users.models import BorrowdUser


class NotificationType(TextChoices):
    """Types of notifications that can be sent."""

    ITEM_REQUESTED = "ITEM_REQUESTED", "Item Requested"
    ITEM_REQUEST_ACCEPTED = "ITEM_REQUEST_ACCEPTED", "Item Request Accepted"
    ITEM_REQUEST_DENIED = "ITEM_REQUEST_DENIED", "Item Request Denied"
    ITEM_RETURNED = "ITEM_RETURNED", "Item Returned"
    GROUP_MEMBER_JOINED = "GROUP_MEMBER_JOINED", "Group Member Joined"


class NotificationStatus(IntegerChoices):
    """Status of a notification."""

    PENDING = 10, "Pending"
    SENT = 20, "Sent"
    FAILED = 30, "Failed"


class NotificationChannel(TextChoices):
    """Channels through which notifications can be sent."""

    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"
    PUSH = "PUSH", "Push Notification"
    IN_APP = "IN_APP", "In-App Notification"


class Notification(Model):
    """Generic notification model that can reference any object and support multiple channels."""

    notification_type: CharField[NotificationType, str] = CharField(
        max_length=50,
        choices=NotificationType.choices,
        help_text="The type of notification being sent.",
    )

    recipient: ForeignKey[BorrowdUser] = ForeignKey(
        BorrowdUser,
        on_delete=CASCADE,
        help_text="The user receiving the notification.",
    )

    channels: JSONField = JSONField(
        default=list,
        help_text="List of channels through which this notification should be sent.",
    )

    status: IntegerField[NotificationStatus, int] = IntegerField(
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        help_text="The current status of the notification.",
    )

    # Generic foreign key to any related object
    content_type: ForeignKey[ContentType] = ForeignKey(
        ContentType,
        on_delete=CASCADE,
        null=True,
        blank=True,
        help_text="The content type of the related object.",
    )

    object_id: IntegerField[Never, int] = IntegerField(
        null=True,
        blank=True,
        help_text="The ID of the related object.",
    )

    content_object: GenericForeignKey = GenericForeignKey(
        "content_type",
        "object_id",
    )

    # Additional context for the notification
    context_data: TextField[str, str] = TextField(
        blank=True,
        help_text="JSON data with additional context for the notification.",
    )

    error_message: TextField[str, str] = TextField(
        blank=True,
        help_text="Error message if the notification failed to send.",
    )

    is_read: BooleanField[bool, bool] = BooleanField(
        default=False,
        help_text="Whether this notification has been read by the recipient.",
    )

    created_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="When this notification was created.",
    )

    sent_at: DateTimeField[Never, Never] = DateTimeField(
        null=True,
        blank=True,
        help_text="When this notification was sent.",
    )

    def __str__(self) -> str:
        related_obj = f" ({self.content_object})" if self.content_object else ""
        channels_str = ", ".join(self.channels) if self.channels else "no channels"
        return f"{self.notification_type} to {self.recipient} via {channels_str}{related_obj}"

    def get_absolute_url(self) -> str:
        return reverse(
            "admin:borrowd_notifications_notification_change", args=[self.pk]
        )

    def add_channel(self, channel: str) -> None:
        """Add a channel to the notification if it's not already present."""
        if channel not in self.channels:
            self.channels.append(channel)
            self.save(update_fields=["channels"])

    def remove_channel(self, channel: str) -> None:
        """Remove a channel from the notification."""
        if channel in self.channels:
            self.channels.remove(channel)
            self.save(update_fields=["channels"])

    def has_channel(self, channel: str) -> bool:
        """Check if the notification has a specific channel."""
        return channel in self.channels

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
