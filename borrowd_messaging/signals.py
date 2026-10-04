from typing import Any

from django.conf import settings
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from borrowd_items.models import (
    Item,
    LifecycleEvent,
    TransactionStatus,
    transition_recorded,
)
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
    sender: type[Item],
    instance: Item,
    update_fields: frozenset[str] | None,
    **kwargs: Any,
) -> None:
    """Archive open conversations after an Item is soft-deleted."""
    if update_fields is not None and "deleted_at" not in update_fields:
        return

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


@receiver(transition_recorded)
def sync_chat_thread_with_transaction(
    sender: type[LifecycleEvent], event: LifecycleEvent, **kwargs: Any
) -> None:
    """
    Keep a transaction's thread in step with the transaction itself:
    give a new one its thread,
    close everyone else's conversation once the item is spoken for,
    and archive or annotate the thread as the status moves on.
    Runs inside the change's database transaction, so it commits or rolls
    back with it.
    """
    transaction = event.transaction
    if event.source_status is None:
        if settings.MESSAGING_ENABLED:
            MessagingService.attach_thread_to(transaction)
        else:
            MessagingService.attach_existing_prerequest_thread_to(transaction)
        return

    if event.target_status in _COMMITTED_STATUSES:
        MessagingService.archive_prerequest_threads_for_item(
            transaction.item, ArchiveReason.ITEM_UNAVAILABLE
        )

    thread = ChatThread.objects.filter(transaction=transaction).first()
    if thread is None:
        return

    if event.target_status == TransactionStatus.DISPUTED:
        MessagingService.post_dispute_notice(thread)
        return

    reason = _TERMINAL_ARCHIVE_REASONS.get(event.target_status)
    if reason is not None:
        MessagingService.archive_thread(thread, reason)
