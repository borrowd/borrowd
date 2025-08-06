from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from borrowd_groups.models import Membership
from borrowd_items.models import Transaction, TransactionStatus

from .services import NotificationService


@receiver(pre_save, sender=Transaction)
def capture_transaction_previous_status(
    sender: Transaction, instance: Transaction, **kwargs: str
) -> None:
    """Capture the previous status before it changes."""
    if instance.pk:  # Only for existing instances
        try:
            old_instance = Transaction.objects.get(pk=instance.pk)
            instance._previous_status = old_instance.status  # type: ignore[attr-defined]
        except Transaction.DoesNotExist:
            pass


@receiver(post_save, sender=Transaction)
def send_transaction_notifications(
    sender: Transaction, instance: Transaction, created: bool, **kwargs: str
) -> None:
    """Send notifications when transaction status changes."""

    # Send notification to item owner when item is requested
    if created and instance.status == TransactionStatus.REQUESTED:
        NotificationService.send_item_requested_notification(instance)
        return

    # Handle status change notifications for existing transactions
    if not created:
        # Get the previous status from the instance's _state
        # This is a simple approach - in production you might want to use django-model-utils
        previous_status = getattr(instance, "_previous_status", None)

        # If we don't have the previous status, we can't determine what changed
        if previous_status is None:
            return

        # Handle different status transitions
        if previous_status == TransactionStatus.REQUESTED:
            if instance.status == TransactionStatus.ACCEPTED:
                # Request was accepted - notify the requester
                NotificationService.send_item_request_accepted_notification(instance)
            elif instance.status == TransactionStatus.REJECTED:
                # Request was denied - notify the requester
                NotificationService.send_item_request_denied_notification(instance)

        elif previous_status in [
            TransactionStatus.COLLECTED,
            TransactionStatus.COLLECTION_ASSERTED,
        ]:
            if instance.status == TransactionStatus.RETURN_ASSERTED:
                # Item return was initiated - notify the owner
                NotificationService.send_item_returned_notification(instance)

        elif previous_status == TransactionStatus.RETURN_ASSERTED:
            if instance.status == TransactionStatus.RETURNED:
                # Item return was confirmed - notify the owner
                NotificationService.send_item_returned_notification(instance)


@receiver(post_save, sender=Membership)
def send_group_member_joined_notifications(
    sender: Membership, instance: Membership, created: bool, **kwargs: str
) -> None:
    """Send notifications to existing group members when a new member joins."""

    if created:
        # Only send notifications if the membership is active
        if instance.status == "ACTIVE":
            NotificationService.send_group_member_joined_notification(instance)
