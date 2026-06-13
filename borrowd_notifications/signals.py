"""
This module contains signals for handling creating notifications and emailing notifications.

Signal handlers for created app models (e.g. Transaction or Membership) will trigger a notify.send()
call which will create a Notification object for each user in the recipient list. A separate signal handler
send_notification() will catch Notification objects post-save, send emails based on Notification attributes,
and fill in the reserved "emailed" field.

To add a new Notification:
    - add/update a signal handler for the object triggering the notification and call notify.send()
    - add a corresponding NotificationType and context in NotificationType._get_template_context_for
    - add text and html templates in templates/notifications

django-notifications repo: https://github.com/django-notifications/django-notifications
"""

from typing import Any, cast

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from notifications.models import Notification
from notifications.signals import notify

from borrowd_groups.models import Membership, MembershipStatus
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    Transaction,
    TransactionStatus,
)

from .models import NotificationType
from .services import NotificationService


def _notify_subscribers_if_available(item: Item) -> None:
    """
    Check if the item is borrowable and notify subscribers.
    """
    item.refresh_from_db()  # Ensure we have the latest data

    if item.is_borrowable():
        subscriptions = AvailabilitySubscription.get_active_subscriptions_for_item(item)
        for subscription in subscriptions:
            notify.send(
                item.owner,
                recipient=[subscription.user],
                verb=NotificationType.ITEM_NOTIFY_WHEN_AVAILABLE.value,
                action_object=item,
                target=subscription,
                description=f"{item.name} is now available",
            )

            AvailabilitySubscription.objects.filter(
                pk=subscription.pk,
                status=AvailabilitySubscriptionStatus.ACTIVE,
                notified_at__isnull=True,
            ).update(
                notified_at=timezone.now(),
                status=AvailabilitySubscriptionStatus.NOTIFIED,
            )


@receiver(post_save, sender=Notification)
def send_notification(
    sender: type[Notification], instance: Notification, created: bool, **kwargs: Any
) -> None:
    """
    Delegates to the service layer to handle notification preferences and channel dispatch.
    """

    # Not sure what impact public has, but defaulting to False to be safe
    instance.public = False

    if not created:
        return

    transaction.on_commit(lambda: NotificationService.send_notification(instance))


@receiver(post_save, sender=Transaction)
def send_transaction_notifications(
    sender: type[Transaction], instance: Transaction, created: bool, **kwargs: Any
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
        case TransactionStatus.COLLECTION_ASSERTED:
            notify.send(
                instance.party2,
                recipient=[instance.party1],
                verb=NotificationType.COLLECTION_ASSERTED.value,
                action_object=instance.item,
                target=instance,
                description=f"{instance.party2.first_name} says they've collected {instance.item.name}. Please confirm.",  # type: ignore[attr-defined]
            )
        case TransactionStatus.COLLECTED:
            notify.send(
                instance.party1,
                recipient=[instance.party2],
                verb=NotificationType.COLLECTION_CONFIRMED.value,
                action_object=instance.item,
                target=instance,
                description=f"Your collection of {instance.item.name} has been confirmed!",  # type: ignore[attr-defined]
            )
        case TransactionStatus.RETURN_ASSERTED:
            notify.send(
                instance.party2,
                recipient=[instance.party1],
                verb=NotificationType.RETURN_ASSERTED.value,
                action_object=instance.item,
                target=instance,
                description=f"{instance.party2.first_name} says they've returned {instance.item.name}. Please confirm.",  # type: ignore[attr-defined]
            )
        case TransactionStatus.RETURNED:
            notify.send(
                instance.party1,
                recipient=[instance.party2],
                verb=NotificationType.RETURN_CONFIRMED.value,
                action_object=instance.item,
                target=instance,
                description=f"{instance.item.name} return confirmed. Thanks for borrowing!",  # type: ignore[attr-defined]
            )


@receiver(pre_save, sender=Membership)
def capture_membership_previous_status(
    sender: type[Membership], instance: Membership, **kwargs: Any
) -> None:
    """Store the pre-save status on the instance so post_save can detect transitions."""
    if instance.pk:
        try:
            instance._previous_status = Membership.objects.values_list(  # type: ignore[attr-defined]
                "status", flat=True
            ).get(pk=instance.pk)
        except Membership.DoesNotExist:
            instance._previous_status = None  # type: ignore[attr-defined]
    else:
        instance._previous_status = None  # type: ignore[attr-defined]


@receiver(post_save, sender=Membership)
def send_membership_notifications(
    sender: type[Membership], instance: Membership, created: bool, **kwargs: Any
) -> None:
    """Send notifications for membership lifecycle events."""
    if created:
        if instance.status == MembershipStatus.PENDING:
            moderators = [
                m.user
                for m in Membership.objects.filter(
                    group=instance.group,
                    is_moderator=True,
                    status=MembershipStatus.ACTIVE,
                ).select_related("user")
            ]
            if moderators:
                notify.send(
                    instance.user,
                    recipient=moderators,
                    verb=NotificationType.MEMBERSHIP_PENDING.value,
                    action_object=instance,
                    target=instance.group,
                    description=f"{instance.user.first_name} wants to join {instance.group.name}. Review their request.",  # type: ignore[attr-defined]
                )
        elif instance.status == MembershipStatus.ACTIVE:
            notify.send(
                instance.user,
                recipient=instance.group.users.exclude(id=instance.user.id),  # type: ignore[attr-defined]
                verb=NotificationType.GROUP_MEMBER_JOINED.value,
                action_object=instance,
                target=instance.group,
                description=f"{instance.user.first_name} just joined {instance.group.name}",  # type: ignore[attr-defined]
            )
    else:
        previous_status = getattr(instance, "_previous_status", None)
        if (
            instance.status == MembershipStatus.ACTIVE
            and previous_status == MembershipStatus.PENDING
        ):
            notify.send(
                instance.group,
                recipient=[instance.user],
                verb=NotificationType.MEMBERSHIP_APPROVED.value,
                action_object=instance,
                target=instance.group,
                description=f"You've been approved to join {instance.group.name}!",  # type: ignore[attr-defined]
            )
            notify.send(
                instance.user,
                recipient=instance.group.users.exclude(id=instance.user.id),  # type: ignore[attr-defined]
                verb=NotificationType.GROUP_MEMBER_JOINED.value,
                action_object=instance,
                target=instance.group,
                description=f"{instance.user.first_name} just joined {instance.group.name}",  # type: ignore[attr-defined]
            )


@receiver(post_save, sender=Transaction)
def send_item_available_notification(
    sender: type[Transaction],
    instance: Transaction,
    created: bool,
    **kwargs: Any,
) -> None:
    """
    Send notifications when an item subscribed to becomes available.
    """

    item = cast(Item | None, instance.item)
    if (
        instance.status
        in [
            TransactionStatus.REJECTED,
            TransactionStatus.RETURNED,
            TransactionStatus.CANCELLED,
        ]
        and item is not None
    ):
        transaction.on_commit(lambda: _notify_subscribers_if_available(item))


@receiver(post_save, sender=AvailabilitySubscription)
def send_item_available_notification_on_subscription(
    sender: type[AvailabilitySubscription],
    instance: AvailabilitySubscription,
    created: bool,
    **kwargs: Any,
) -> None:
    """
    Send notifications when an availability subscription is created for an item that is already available.
    """

    item = cast(Item | None, instance.item)
    if (
        created
        and instance.status == AvailabilitySubscriptionStatus.ACTIVE
        and item is not None
        and not item.is_borrowable()
    ):
        notify.send(
            instance.item,
            recipient=[instance.user],
            verb=NotificationType.ITEM_SUBSCRIPTION.value,
            action_object=item,
            target=instance,
            description=f"You'll be notified when {item.name} becomes available",
        )
