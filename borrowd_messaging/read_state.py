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
from django_stubs_ext import WithAnnotations

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
    """Acknowledge rendered messages, returning whether the stored cursor advanced.

    Zero means no messages have been rendered. The caller's thread instance is
    not refreshed; acknowledgments from other tabs may have advanced it already.
    """
    if not settings.MESSAGING_ENABLED:
        raise MessagingDisabled("Messaging is not enabled.")

    if viewer.pk == thread.lender_id:
        field = "lender_last_read_message_id"
    elif viewer.pk == thread.borrower_id:
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
            thread_id=thread.pk, pk=through_message_id
        ).exists()
    ):
        raise InvalidReadCursor(
            "Read cursor must identify a message in this conversation."
        )

    # Compare in the UPDATE so concurrent or delayed acknowledgments cannot
    # overwrite a newer cursor, even when the caller holds an older instance.
    return bool(
        ChatThread.objects.filter(pk=thread.pk)
        .filter(
            Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__lt": through_message_id})
        )
        .update(**{field: through_message_id})
    )


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
