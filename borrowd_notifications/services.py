from typing import Any, Dict, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from borrowd_groups.models import Membership
from borrowd_items.models import Transaction
from borrowd_users.models import BorrowdUser

from .models import (
    Notification,
    NotificationStatus,
)


class NotificationService:
    """Service for sending multi-channel notifications."""

    @staticmethod
    def _create_notification(
        notification_type: str,
        recipient: BorrowdUser,
        content_object: Any,
        channels: Optional[list[str]] = None,
    ) -> Notification:
        """Create a notification with the given parameters."""
        if channels is None:
            channels = ["EMAIL"]

        return Notification.objects.create(
            notification_type=notification_type,
            recipient=recipient,
            channels=channels,
            content_object=content_object,
        )

    @staticmethod
    def _send_email_notification(
        notification: Notification,
        subject: str,
        template_name: str,
        context: Dict[str, Any],
        recipient_email: str,
    ) -> None:
        """Send an email notification."""
        html_message = render_to_string(f"notifications/{template_name}.html", context)
        text_message = render_to_string(f"notifications/{template_name}.txt", context)

        send_mail(
            subject=subject,
            message=text_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=False,
        )

    @staticmethod
    def _send_through_channels(
        notification: Notification,
        channels: list[str],
        email_subject: str,
        email_template: str,
        email_context: Dict[str, Any],
        recipient_email: str,
    ) -> None:
        """Send notification through all specified channels."""
        for channel in channels:
            if channel == "EMAIL":
                NotificationService._send_email_notification(
                    notification,
                    email_subject,
                    email_template,
                    email_context,
                    recipient_email,
                )
            elif channel == "SMS":
                # TODO: Implement SMS sending
                pass
            elif channel == "PUSH":
                # TODO: Implement push notification
                pass
            elif channel == "IN_APP":
                # TODO: Implement in-app notification
                pass

    @staticmethod
    def _update_notification_status(
        notification: Notification, success: bool = True, error_message: str = ""
    ) -> None:
        """Update notification status based on success/failure."""
        if success:
            notification.status = NotificationStatus.SENT
            notification.sent_at = timezone.now()  # type: ignore[assignment]
        else:
            notification.status = NotificationStatus.FAILED
            notification.error_message = error_message
        notification.save()

    @staticmethod
    def send_item_requested_notification(
        transaction: Transaction, channels: Optional[list[str]] = None
    ) -> Notification:
        """Send notification to item owner when someone requests to borrow their item."""
        item_owner: BorrowdUser = transaction.item.owner  # type: ignore[attr-defined]
        requester: BorrowdUser = transaction.party2  # type: ignore[assignment]

        notification = NotificationService._create_notification(
            "ITEM_REQUESTED",
            item_owner,
            transaction,
            channels,
        )

        try:
            # Get requester name
            requester_name = requester.profile.full_name()
            item_name = transaction.item.name  # type: ignore[attr-defined]

            # Build email context
            base_url = (
                "https://app.borrowd.org"
                if not settings.DEBUG
                else "http://localhost:8000"
            )
            context = {
                "requester_name": requester_name,
                "item_name": item_name,
                "item_owner_name": item_owner.profile.full_name(),
                "respond_url": base_url
                + reverse("item-detail", args=[transaction.item.pk]),  # type: ignore[attr-defined]
            }

            NotificationService._send_through_channels(
                notification,
                notification.channels,
                f"Someone's hoping to borrow your {item_name}",
                "item_requested",
                context,
                item_owner.email,
            )

            NotificationService._update_notification_status(notification, success=True)

        except Exception as e:
            NotificationService._update_notification_status(
                notification, success=False, error_message=str(e)
            )

        return notification

    @staticmethod
    def send_item_request_accepted_notification(
        transaction: Transaction, channels: Optional[list[str]] = None
    ) -> Notification:
        """Send notification to requester when their request is accepted."""
        # Type assertions to help mypy
        requester: BorrowdUser = transaction.party2  # type: ignore[assignment]
        item_owner: BorrowdUser = transaction.item.owner  # type: ignore[attr-defined]

        notification = NotificationService._create_notification(
            "ITEM_REQUEST_ACCEPTED",
            requester,
            transaction,
            channels,
        )

        try:
            # Build email context
            context = {
                "requester_name": requester.profile.full_name(),
                "item_name": transaction.item.name,  # type: ignore[attr-defined]
                "item_owner_name": item_owner.profile.full_name(),
                "item_owner_email": item_owner.email,
            }

            NotificationService._send_through_channels(
                notification,
                notification.channels,
                f"Your request to borrow {transaction.item.name} was approved",  # type: ignore[attr-defined]
                "item_request_accepted",
                context,
                requester.email,
            )

            NotificationService._update_notification_status(notification, success=True)

        except Exception as e:
            NotificationService._update_notification_status(
                notification, success=False, error_message=str(e)
            )

        return notification

    @staticmethod
    def send_item_request_denied_notification(
        transaction: Transaction, channels: Optional[list[str]] = None
    ) -> Notification:
        """Send notification to requester when their request is denied."""
        requester: BorrowdUser = transaction.party2  # type: ignore[assignment]

        notification = NotificationService._create_notification(
            "ITEM_REQUEST_DENIED",
            requester,
            transaction,
            channels,
        )

        try:
            # Build email context
            context = {
                "requester_name": requester.profile.full_name(),
                "item_name": transaction.item.name,  # type: ignore[attr-defined]
            }

            NotificationService._send_through_channels(
                notification,
                notification.channels,
                "The item you requested is not available",
                "item_request_denied",
                context,
                requester.email,
            )

            NotificationService._update_notification_status(notification, success=True)

        except Exception as e:
            NotificationService._update_notification_status(
                notification, success=False, error_message=str(e)
            )

        return notification

    @staticmethod
    def send_item_returned_notification(
        transaction: Transaction, channels: Optional[list[str]] = None
    ) -> Notification:
        """Send notification to item owner when item is returned."""
        item_owner: BorrowdUser = transaction.item.owner  # type: ignore[attr-defined]
        requester: BorrowdUser = transaction.party2  # type: ignore[assignment]

        notification = NotificationService._create_notification(
            "ITEM_RETURNED",
            item_owner,
            transaction,
            channels,
        )

        try:
            # Build email context
            context = {
                "item_owner_name": item_owner.profile.full_name(),
                "requester_name": requester.profile.full_name(),
                "item_name": transaction.item.name,  # type: ignore[attr-defined]
            }

            NotificationService._send_through_channels(
                notification,
                notification.channels,
                "Borrow'd item returned",
                "item_returned",
                context,
                item_owner.email,
            )

            NotificationService._update_notification_status(notification, success=True)

        except Exception as e:
            NotificationService._update_notification_status(
                notification, success=False, error_message=str(e)
            )

        return notification

    @staticmethod
    def send_group_member_joined_notification(
        membership: Membership, channels: Optional[list[str]] = None
    ) -> list[Notification]:
        """Send notifications to existing group members when a new member joins."""
        notifications = []

        # Get all existing members (excluding the new member)
        existing_members = membership.group.membership_set.exclude(user=membership.user)  # type: ignore[attr-defined]

        for existing_membership in existing_members:
            notification = NotificationService._create_notification(
                "GROUP_MEMBER_JOINED",
                existing_membership.user,
                membership,
                channels,
            )

            try:
                # Build email context
                context = {
                    "group_member_name": existing_membership.user.profile.full_name(),
                    "new_member_name": membership.user.profile.full_name(),  # type: ignore[attr-defined]
                    "group_name": membership.group.name,  # type: ignore[attr-defined]
                }

                NotificationService._send_through_channels(
                    notification,
                    notification.channels,
                    f"A new member just joined your {membership.group.name} group",  # type: ignore[attr-defined]
                    "group_member_joined",
                    context,
                    existing_membership.user.email,
                )

                NotificationService._update_notification_status(
                    notification, success=True
                )

            except Exception as e:
                NotificationService._update_notification_status(
                    notification, success=False, error_message=str(e)
                )

            notifications.append(notification)

        return notifications
