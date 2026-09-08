from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from django.db.models import DateTimeField, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from borrowd_items.models import Item, TransactionStatus
from borrowd_users.models import BorrowdUser

from .exceptions import NotThreadParticipant
from .models import ArchiveReason, ChatThread, Message
from .read_state import threads_with_unread_state

ConversationStatusKind = Literal["active", "archived", "disputed", "prerequest"]

_ARCHIVE_STATUS_LABELS: dict[str, str] = {
    ArchiveReason.RETURNED: "Returned",
    ArchiveReason.REJECTED: "Declined",
    ArchiveReason.CANCELLED: "Cancelled",
    ArchiveReason.RESOLVED: "Resolved",
    ArchiveReason.OWNERSHIP_TRANSFERRED: "Ownership transferred",
    ArchiveReason.ITEM_UNAVAILABLE: "Unavailable",
    ArchiveReason.ITEM_DELETED: "Item deleted",
    ArchiveReason.CLOSED: "Closed",
}


@dataclass(frozen=True)
class ConversationSummary:
    """The data shared by Item conversation cards and history rows."""

    thread_id: int
    other_participant: BorrowdUser
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    last_message_preview: str | None
    status_label: str
    status_kind: ConversationStatusKind


@dataclass(frozen=True)
class HubConversationSummary:
    """A conversation summary plus the Item context and unread state the hub shows.

    A null item_name means the Item is gone; the template supplies the copy.
    """

    conversation: ConversationSummary
    item_name: str | None
    item_thumbnail_url: str | None
    has_unread_messages: bool


def threads_for_item(
    item: Item,
    viewer: BorrowdUser,
) -> QuerySet[ChatThread]:
    """Return this Item's threads that the viewer participates in.

    Each row includes the related data and latest-message values needed by
    build_conversation_summaries.
    """
    return _with_summary_data(
        ChatThread.objects.filter(item=item).filter(
            Q(lender=viewer) | Q(borrower=viewer)
        )
    )


def participant_conversation_threads(viewer: BorrowdUser) -> QuerySet[ChatThread]:
    """Return all this participant's threads with summary and unread data loaded.

    Photos are prefetched, so paginate before evaluating this to keep the
    prefetch to one page of Items.
    """
    return (
        _with_summary_data(threads_with_unread_state(viewer))
        .select_related("item")
        .prefetch_related("item__photos")
    )


def build_hub_conversation_summaries(
    threads: Iterable[ChatThread],
    viewer: BorrowdUser,
) -> list[HubConversationSummary]:
    """Pair each conversation summary with its Item context and unread state."""
    loaded = list(threads)
    summaries = build_conversation_summaries(loaded, viewer)
    cards: list[HubConversationSummary] = []
    for thread, summary in zip(loaded, summaries, strict=True):
        item = thread.item if _is_available(thread.item) else None
        cards.append(
            HubConversationSummary(
                conversation=summary,
                item_name=item.name if item is not None else None,
                item_thumbnail_url=_thumbnail_url(item),
                has_unread_messages=cast(bool, getattr(thread, "has_unread_messages")),
            )
        )
    return cards


def _is_available(item: Item | None) -> bool:
    """A hard-deleted Item leaves no link; a soft-deleted one is still linked."""
    return item is not None and item.deleted_at is None


def _thumbnail_url(item: Item | None) -> str | None:
    """Read the prefetched first photo. A missing file must not break the page."""
    if item is None:
        return None
    photo = next(iter(item.photos.all()), None)
    if photo is None:
        return None
    try:
        return cast(str, photo.thumbnail.url)
    except FileNotFoundError:
        return None


def _with_summary_data(threads: QuerySet[ChatThread]) -> QuerySet[ChatThread]:
    """Add message previews and sort conversations by their latest message time.

    Use the highest-ID message for the preview.
    For conversations without messages, use their creation time.
    Break equal activity times using the conversation ID, highest first.
    """
    # Preview: highest message ID.
    latest_message = Message.objects.filter(thread_id=OuterRef("pk")).order_by("-pk")
    # Activity date: latest message timestamp.
    latest_activity = latest_message.order_by("-created_at", "-pk")

    return (
        threads.select_related(
            "lender__profile",
            "borrower__profile",
            "transaction",
        )
        .annotate(
            summary_last_message_at=Subquery(
                latest_activity.values("created_at")[:1],
                output_field=DateTimeField(),
            ),
            summary_last_message_preview=Subquery(latest_message.values("body")[:1]),
        )
        .annotate(
            summary_last_activity_at=Coalesce(
                "summary_last_message_at",
                "created_at",
            )
        )
        .order_by("-summary_last_activity_at", "-pk")
    )


def build_conversation_summaries(
    threads: Iterable[ChatThread],
    viewer: BorrowdUser,
) -> list[ConversationSummary]:
    """Turn loaded threads into display-ready conversation summaries."""
    summaries: list[ConversationSummary] = []
    for thread in threads:
        if viewer.pk == thread.lender_id:
            other_participant = thread.borrower
        elif viewer.pk == thread.borrower_id:
            other_participant = thread.lender
        else:
            raise NotThreadParticipant(
                f"User {viewer.pk} is not a participant of ChatThread {thread.pk}."
            )

        status_label, status_kind = _conversation_status(thread)
        summaries.append(
            ConversationSummary(
                thread_id=thread.pk,
                other_participant=other_participant,
                started_at=thread.created_at,
                ended_at=thread.archived_at,
                last_activity_at=cast(
                    datetime,
                    getattr(thread, "summary_last_activity_at"),
                ),
                last_message_preview=cast(
                    str | None,
                    getattr(thread, "summary_last_message_preview"),
                ),
                status_label=status_label,
                status_kind=status_kind,
            )
        )
    return summaries


def _conversation_status(
    thread: ChatThread,
) -> tuple[str, ConversationStatusKind]:
    if thread.is_archived:
        reason = thread.archive_reason
        return (
            _ARCHIVE_STATUS_LABELS.get(reason, "Archived")
            if reason is not None
            else "Archived",
            "archived",
        )
    if thread.transaction_id is None:
        return "Pre-request", "prerequest"
    transaction = thread.transaction
    if transaction is not None and transaction.status == TransactionStatus.DISPUTED:
        return "Disputed", "disputed"
    return "Active", "active"
