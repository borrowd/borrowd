from __future__ import annotations

from typing import TypedDict

from django.conf import settings
from django.db.models import (
    BigIntegerField,
    Case,
    Exists,
    F,
    OuterRef,
    Q,
    QuerySet,
    When,
)
from django.db.models.functions import Coalesce
from django.db.transaction import atomic
from django_stubs_ext import WithAnnotations

from borrowd_notifications.message_notifications import (
    clear_message_notification_through,
)
from borrowd_users.models import BorrowdUser

from .exceptions import InvalidReadCursor, MessagingDisabled, NotThreadParticipant
from .models import ChatThread, Message


class ThreadReadState(TypedDict):
    has_unread_messages: bool


def mark_thread_read(
    thread: ChatThread,
    viewer: BorrowdUser,
    *,
    through_message_id: int,
) -> bool:
    """Update/Save the newest message the viewer has seen.

    `through_message_id` must belong to this conversation.
    Passing `through_message_id=0` means no messages were shown yet,
    so this function makes no change and returns False.
    Otherwise, it returns True only when the saved cursor moves forward.
    When the cursor moves forward, covered notification state is cleared in the same transaction.
    The passed `thread` object is not refreshed.
    """
    if not settings.MESSAGING_ENABLED:
        raise MessagingDisabled("Messaging is not enabled.")

    with atomic():
        # Sending and reading lock the same conversation, so they finish one at a time:
        # https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
        locked_thread = ChatThread.objects.select_for_update().get(pk=thread.pk)

        if viewer.pk == locked_thread.lender_id:
            field = "lender_last_read_message_id"
        elif viewer.pk == locked_thread.borrower_id:
            field = "borrower_last_read_message_id"
        else:
            raise NotThreadParticipant(
                f"User {viewer.pk} is not a participant of ChatThread {thread.pk}."
            )

        if through_message_id == 0:
            return False
        if (
            through_message_id < 0
            or not Message.objects.filter(
                thread_id=locked_thread.pk, pk=through_message_id
            ).exists()
        ):
            raise InvalidReadCursor(
                "Read cursor must identify a message in this conversation."
            )

        # Compare in the UPDATE so concurrent or delayed acknowledgments cannot
        # overwrite a newer cursor, even when the caller holds an older instance.
        advanced = bool(
            ChatThread.objects.filter(pk=locked_thread.pk)
            .filter(
                Q(**{f"{field}__isnull": True})
                | Q(**{f"{field}__lt": through_message_id})
            )
            .update(**{field: through_message_id})
        )
        if advanced:
            clear_message_notification_through(
                locked_thread,
                viewer,
                through_message_id=through_message_id,
            )
        return advanced


def threads_with_unread_state(
    viewer: BorrowdUser,
) -> QuerySet[WithAnnotations[ChatThread, ThreadReadState]]:
    """Return the participant's threads annotated with has_unread_messages."""
    threads = ChatThread.objects.filter(Q(lender=viewer) | Q(borrower=viewer)).alias(
        viewer_read_cursor=Coalesce(
            Case(
                When(lender=viewer, then=F("lender_last_read_message_id")),
                default=F("borrower_last_read_message_id"),
            ),
            0,
            output_field=BigIntegerField(),
        ),
        other_participant_id=Case(
            When(lender=viewer, then=F("borrower_id")),
            default=F("lender_id"),
        ),
    )
    unread_messages = Message.objects.filter(
        Q(is_system=True) | Q(sender_id=OuterRef("other_participant_id")),
        thread_id=OuterRef("pk"),
        pk__gt=OuterRef("viewer_read_cursor"),
    )
    return threads.annotate(has_unread_messages=Exists(unread_messages))


def unread_threads_for(viewer: BorrowdUser) -> QuerySet[ChatThread]:
    """Return threads with unacknowledged incoming messages or system notices."""
    return threads_with_unread_state(viewer).filter(has_unread_messages=True)
