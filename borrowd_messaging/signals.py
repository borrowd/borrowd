from typing import Any

from django.conf import settings
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from borrowd_items.models import Item, Transaction, TransactionStatus
from borrowd_permissions.models import ChatThreadOLP

from .models import ArchiveReason, ChatThread
from .services import MessagingService

# Keyed by int so a raw status value looks up without coercion.
_TERMINAL_ARCHIVE_REASONS: dict[int, ArchiveReason] = {
    TransactionStatus.RETURNED: ArchiveReason.RETURNED,
    TransactionStatus.REJECTED: ArchiveReason.REJECTED,
    TransactionStatus.CANCELLED: ArchiveReason.CANCELLED,
    TransactionStatus.RESOLVED: ArchiveReason.RESOLVED,
    TransactionStatus.OWNERSHIP_TRANSFERRED: ArchiveReason.OWNERSHIP_TRANSFERRED,
}

# Statuses at which the item is unavailable to others. I.E., pre-request threads should be closed.
_COMMITTED_STATUSES = frozenset(
    {
        TransactionStatus.ACCEPTED,
        TransactionStatus.OWNERSHIP_TRANSFERRED,
    }
)


@receiver(post_save, sender=ChatThread)
def assign_chat_thread_permissions(
    sender: type[ChatThread], instance: ChatThread, created: bool, **kwargs: Any
) -> None:
    """
    Grant both parties view access when a thread is created.
    """
    if created:
        assign_perm(ChatThreadOLP.VIEW, instance.lender, instance)
        assign_perm(ChatThreadOLP.VIEW, instance.borrower, instance)


@receiver(post_save, sender=Item)
def archive_threads_for_soft_deleted_item(
    sender: type[Item], instance: Item, **kwargs: Any
) -> None:
    """Archive open conversations after an Item is soft-deleted."""
    if instance.deleted_at is not None:
        MessagingService.archive_open_threads_for_item(
            instance, ArchiveReason.ITEM_DELETED
        )


@receiver(pre_delete, sender=Item)
def archive_threads_for_hard_deleted_item(
    sender: type[Item], instance: Item, **kwargs: Any
) -> None:
    """Archive open conversations before an Item is hard-deleted."""
    MessagingService.archive_open_threads_for_item(instance, ArchiveReason.ITEM_DELETED)


@receiver(post_save, sender=Transaction)
def sync_chat_thread_with_transaction(
    sender: type[Transaction], instance: Transaction, created: bool, **kwargs: Any
) -> None:
    """
    Keep a transaction's thread in step with the transaction itself:
    give a new one its thread,
    close everyone else's conversation once the item is spoken for,
    and archive or annotate the thread as the status moves on.
    """
    if created:
        if settings.MESSAGING_ENABLED:
            MessagingService.attach_thread_to(instance)
        else:
            MessagingService.attach_existing_prerequest_thread_to(instance)
        return

    if instance.status == getattr(instance, "_previous_status", None):
        return

    if instance.status in _COMMITTED_STATUSES:
        MessagingService.archive_prerequest_threads_for_item(
            instance.item, ArchiveReason.ITEM_UNAVAILABLE
        )

    thread = ChatThread.objects.filter(transaction=instance).first()
    if thread is None:
        return

    if instance.status == TransactionStatus.DISPUTED:
        MessagingService.post_dispute_notice(thread)
        return

    reason = _TERMINAL_ARCHIVE_REASONS.get(instance.status)
    if reason is not None:
        MessagingService.archive_thread(thread, reason)
