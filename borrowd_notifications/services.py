from enum import Enum
from typing import Any, Dict

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from notifications.models import Notification

from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Transaction, TransactionStatus


class NotificationType(Enum):
    ITEM_REQUESTED = "Item requested"
    ITEM_REQUEST_ACCEPTED = "Item request accepted"
    ITEM_REQUEST_DENIED = "Item request denied"
    ITEM_RETURNED = "Item returned"
    GROUP_MEMBER_JOINED = "Change to group membership"

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
            recipient_list=[notification.recipient],
            fail_silently=False,
        )

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
            membership: Membership = notification.action_object
            # existing_members = membership.group.membership_set.exclude(user=membership.user)  # type: ignore[attr-defined]
            context.update(
                {
                    "group_member_name": notification.recipient.profile.full_name(),
                    "new_member_name": membership.user.profile.full_name(),  # type: ignore[attr-defined]
                    "group_name": membership.group.name,  # type: ignore[attr-defined]
                }
            )
        return context
