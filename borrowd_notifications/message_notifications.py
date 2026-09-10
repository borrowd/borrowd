"""Create, refresh, and clear notifications for conversation messages."""

from typing import cast

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from notifications.models import Notification
from notifications.signals import notify

from borrowd_messaging.models import ChatThread, Message
from borrowd_users.models import BorrowdUser

from .models import ConversationNudge, ConversationNudgeStatus, NotificationType


def _message_recipient(thread: ChatThread, sender_id: int) -> BorrowdUser:
    """Return the participant who did not send the message."""
    if sender_id == thread.lender_id:
        return thread.borrower
    if sender_id == thread.borrower_id:
        return thread.lender
    raise ValueError(f"Message sender is not a participant of ChatThread {thread.pk}.")


def _notification_subject(message: Message, thread: ChatThread) -> str:
    """Return the email subject for a new-message notification."""
    item_name = thread.item.name if thread.item is not None else "an item"
    return f"{message.sender.first_name} sent you a message about {item_name}"


def _notifications_for(nudge: ConversationNudge) -> QuerySet[Notification]:
    """Return notifications created for one nudge cycle."""
    nudge_type = ContentType.objects.get_for_model(ConversationNudge)
    return cast(
        "QuerySet[Notification]",
        Notification.objects.filter(
            recipient_id=nudge.recipient_id,
            verb=NotificationType.NEW_MESSAGE.value,
            target_content_type=nudge_type,
            target_object_id=str(nudge.pk),
        ),
    )


def _clear_nudge(nudge: ConversationNudge) -> None:
    """End a nudge cycle and mark its notifications as read."""
    nudge.status = ConversationNudgeStatus.CLEARED
    nudge.cleared_at = timezone.now()
    nudge.save(update_fields=["status", "cleared_at"])
    _notifications_for(nudge).filter(unread=True).update(unread=False)


def _refresh_active_nudge(
    nudge: ConversationNudge,
    message: Message,
    subject: str,
) -> bool:
    """Move an unread notification forward, returning whether one existed."""
    refreshed = (
        _notifications_for(nudge)
        .filter(unread=True)
        .update(
            description=subject,
            timestamp=message.created_at,
        )
    )
    if not refreshed:
        return False

    nudge.latest_message = message
    nudge.save(update_fields=["latest_message"])
    return True


def create_or_refresh_message_notification(message: Message) -> None:
    """Create one notification cycle, or move its active nudge to this message."""
    if message.is_system or not settings.MESSAGING_ENABLED:
        return

    with transaction.atomic():
        # The thread is a stable lock even when no active nudge exists yet:
        # https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
        thread = (
            ChatThread.objects.select_for_update(of=("self",))
            .select_related("borrower", "lender", "item")
            .get(pk=message.thread_id)
        )
        recipient = _message_recipient(thread, message.sender_id)
        subject = _notification_subject(message, thread)
        active_nudge = (
            ConversationNudge.objects.select_for_update()
            .filter(
                recipient=recipient,
                thread=thread,
                status=ConversationNudgeStatus.ACTIVE,
            )
            .first()
        )

        if active_nudge is not None:
            if active_nudge.latest_message_id >= message.pk:
                return
            if _refresh_active_nudge(active_nudge, message, subject):
                return
            _clear_nudge(active_nudge)

        nudge = ConversationNudge.objects.create(
            recipient=recipient,
            thread=thread,
            latest_message=message,
        )
        # The thread supplies the link; the nudge owns the lifecycle state.
        notify.send(
            message.sender,
            recipient=[recipient],
            verb=NotificationType.NEW_MESSAGE.value,
            action_object=thread,
            target=nudge,
            description=subject,
            timestamp=message.created_at,
        )


def clear_message_notification_through(
    thread: ChatThread,
    reader: BorrowdUser,
    *,
    through_message_id: int,
) -> bool:
    """Clear the active nudge when the reader has seen its latest message."""
    with transaction.atomic():
        locked_thread = ChatThread.objects.select_for_update().get(pk=thread.pk)
        nudge = (
            ConversationNudge.objects.select_for_update()
            .filter(
                recipient=reader,
                thread=locked_thread,
                status=ConversationNudgeStatus.ACTIVE,
            )
            .first()
        )
        if nudge is None or nudge.latest_message_id > through_message_id:
            return False

        _clear_nudge(nudge)
        return True
