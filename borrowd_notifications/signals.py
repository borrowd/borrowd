"""
This module contains signals for handling creating notifications and emailing notifications.

Signal handlers for created app models (e.g. Transaction or Membership) will trigger a notify.send()
call which will create a Notification object for each user in the recipient list. A separate signal handler
send_notification_email() will catch Notification objects pre-save, send emails based on Notification attributes,
and fill in the reserved "emailed" field.

To add a new Notification:
    - add/update a signal handler for the object triggering the notification and call notify.send()
    - in NotificationService, add a corresponding NotificationType and context in _get_template_context_for
    - add text and html templates in templates/notifications

django-notifications repo: https://github.com/django-notifications/django-notifications
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from notifications.models import Notification
from notifications.signals import notify

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_items.models import Transaction, TransactionStatus

from .services import NotificationService, NotificationType


@receiver(pre_save, sender=Notification)
def send_notification_email(
    sender: Notification, instance: Notification, **kwargs: str
) -> None:
    """Send email notification."""

    # Not sure what impact public has, but defaulting to False to be safe
    instance.public = False

    try:
        user = instance.recipient
        if user.email:
            NotificationService.send_email_notification(instance)
            instance.emailed = True
    except Exception as e:
        instance.emailed = False
        instance.data = {
            "error": str(e),
        }


@receiver(post_save, sender=Transaction)
def send_transaction_notifications(
    sender: Transaction, instance: Transaction, created: bool, **kwargs: str
) -> None:
    """Send notifications when transaction status changes."""

    match instance.status:
        case TransactionStatus.REQUESTED:
            notify.send(
                instance.party2,
                recipient=[instance.party1],
                verb=NotificationType.ITEM_REQUESTED.value,
                action_object=instance.item,
                target=instance,
                description=f"Someone's hoping to borrow your {instance.item.name}",  # type: ignore[attr-defined]
            )
        case TransactionStatus.ACCEPTED:
            notify.send(
                instance.party1,
                recipient=[instance.party2],
                verb=NotificationType.ITEM_REQUEST_ACCEPTED.value,
                action_object=instance.item,
                target=instance,
                description=f"Your request to borrow {instance.item.name} was approved",  # type: ignore[attr-defined]
            )
        case TransactionStatus.REJECTED:
            notify.send(
                instance.party1,
                recipient=[instance.party2],
                verb=NotificationType.ITEM_REQUEST_DENIED.value,
                action_object=instance.item,
                target=instance,
                description="The item you requested is not available",
            )
        case TransactionStatus.RETURNED:
            notify.send(
                instance.party2,
                recipient=[instance.party1],
                verb=NotificationType.ITEM_RETURNED.value,
                action_object=instance.item,
                target=instance,
                description="Borrow'd item returned",
            )


@receiver(post_save, sender=Membership)
def send_group_member_joined_notifications(
    sender: Membership, instance: Membership, created: bool, **kwargs: str
) -> None:
    """Send notifications to existing group members when a new member joins."""

    # TODO once membership approval is implemented, check status change e.g. Pending -> Active memberships
    if created and (
        instance.status == MembershipStatus.ACTIVE
        or instance.status == MembershipStatus.PENDING
    ):
        notify.send(
            instance.user,
            recipient=instance.group.users.exclude(id=instance.id),  # type: ignore[attr-defined]
            verb=NotificationType.GROUP_MEMBER_JOINED.value,
            action_object=instance,
            target=instance.group,
            description=f"A new member just joined your {instance.group.name} group",  # type: ignore[attr-defined]
        )
