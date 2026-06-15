from enum import Enum
from typing import Any, Dict

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from notifications.models import Notification

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import (
    AvailabilitySubscription,
    Transaction,
    TransactionStatus,
)


class NotificationType(Enum):
    ITEM_REQUESTED = "Item requested"
    ITEM_REQUEST_ACCEPTED = "Item request accepted"
    ITEM_REQUEST_DENIED = "Item request denied"
    ITEM_NOTIFY_WHEN_AVAILABLE = (
        "Item notify when available"  # When the item becomes available
    )
    ITEM_SUBSCRIPTION = (
        "Item subscription"  # When a user subscribes to notifications for an item
    )
    ITEM_RETURNED = "Item returned"
    ITEM_RETURN_REQUESTED = "Item return requested"
    ITEM_DISPUTED = "Item disputed"
    GROUP_MEMBER_JOINED = "Change to group membership"
    GROUP_NEEDS_MODERATOR = "Group needs moderator"  # When moderator leaves group
    REQUEST_CANCELLED_BORROWER_LEFT = "Request cancelled - borrower left"  # When borrower closes account with an open request
    REQUEST_CANCELLED_OWNER_LEFT = "Request cancelled - owner left"  # When owner closes account with an open request
    LOAN_ENDED_OWNER_LEFT = (
        "Loan ended - owner left"  # When owner closes account with an active loan
    )

    @property
    def template_name(self) -> str:
        return self.name.lower()


class NotificationService:
    """Service for sending notifications."""

    @staticmethod
    def send_email_notification(
        notification: Notification,
    ) -> None:
        """Send an email notification."""
        template_name = NotificationType(notification.verb).template_name
        context = NotificationService._get_template_context_for(notification)
        html_message = render_to_string(f"notifications/{template_name}.html", context)
        text_message = render_to_string(f"notifications/{template_name}.txt", context)

        send_mail(
            subject=notification.description,
            message=text_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient.email],
            fail_silently=False,
        )

    @staticmethod
    def _get_template_context_for(notification: Notification) -> Dict[str, Any]:
        """Extract context from the notification's action_object."""
        # attr-defined ignores: ForeignKey[X] annotations hide related-model attrs from mypy
        # TODO: adopt two-arg ForeignKey[X, X] annotations repo-wide and drop these ignores
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

            if notification.verb == NotificationType.ITEM_SUBSCRIPTION.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),
                        "item_name": subscription.item.name,
                        "item_url": settings.BASE_URL
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
            elif notification.verb == NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value:
                context.update(
                    {
                        "subscriber_name": subscription.user.profile.full_name(),
                        "item_name": subscription.item.name,
                        "item_url": settings.BASE_URL
                        + reverse("item-detail", args=[subscription.item.pk]),
                    }
                )
        return context
