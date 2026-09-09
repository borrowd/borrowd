from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from django.db.models import DateTimeField, OuterRef, QuerySet, Subquery
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
    """Viewer-specific data used to display one conversation."""

    thread_id: int
    other_participant: BorrowdUser
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    last_message_preview: str | None
    status_label: str
    status_kind: ConversationStatusKind
    has_unread_messages: bool


@dataclass(frozen=True)
class HubConversationCard:
    """A conversation summary plus the Item displayed with it in the hub."""

    summary: ConversationSummary
    item_name: str | None
    item_thumbnail_url: str | None
    item_removed: bool


def threads_for_item(
    item: Item,
    viewer: BorrowdUser,
) -> QuerySet[ChatThread]:
    """Return this Item's threads that the viewer participates in.

    Each row includes the related data and latest-message values needed by
    build_conversation_summaries.
    """
    return _prepare_threads_for_summaries(
        threads_with_unread_state(viewer).filter(item=item)
    )


def threads_for_hub(viewer: BorrowdUser) -> QuerySet[ChatThread]:
    """Return all threads the viewer participates in for the Messages hub.

    Each row includes summary data, its Item, and Item photos. Paginate before
    evaluating the queryset so photos are fetched for only one page of Items.
    """
    return (
        _prepare_threads_for_summaries(threads_with_unread_state(viewer))
        .select_related("item")
        .prefetch_related("item__photos")
    )


def build_hub_cards(
    threads: Iterable[ChatThread],
    viewer: BorrowdUser,
) -> list[HubConversationCard]:
    """Pair each conversation summary with the Item context shown beside it."""
    loaded = list(threads)
    summaries = build_conversation_summaries(loaded, viewer)
    cards: list[HubConversationCard] = []
    for thread, summary in zip(loaded, summaries, strict=True):
        item = thread.item
        cards.append(
            HubConversationCard(
                summary=summary,
                item_name=item.name if item is not None else None,
                item_thumbnail_url=item_thumbnail_url(item),
                item_removed=is_removed(thread),
            )
        )
    return cards


def listed_item(thread: ChatThread) -> Item | None:
    """The conversation's Item while it is still listed.

    Only a listed Item has a page to link to; a removed one 404s.
    """
    item = thread.item
    return item if item is not None and item.deleted_at is None else None


def is_removed(thread: ChatThread) -> bool:
    """Whether the Item is soft-deleted but still readable.

    Items are soft-deleted, so a removed Item keeps its name and photo. Only a
    hard delete leaves nothing, and that clears the link instead.
    """
    return thread.item is not None and thread.item.deleted_at is not None


def item_thumbnail_url(item: Item | None) -> str | None:
    """Read the Item's first photo. A missing file must not break the page.

    Callers listing many Items should prefetch photos; one Item costs one query
    either way.
    """
    if item is None:
        return None
    photo = next(iter(item.photos.all()), None)
    if photo is None:
        return None
    try:
        return cast(str, photo.thumbnail.url)
    except FileNotFoundError:
        return None


def _prepare_threads_for_summaries(
    threads: QuerySet[ChatThread],
) -> QuerySet[ChatThread]:
    """Add preview and activity data, then order newest activity first."""
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

        status_label, status_kind = conversation_status(thread)
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
                has_unread_messages=cast(
                    bool,
                    getattr(thread, "has_unread_messages"),
                ),
            )
        )
    return summaries


def conversation_status(
    thread: ChatThread,
) -> tuple[str, ConversationStatusKind]:
    """Where this conversation stands, as a label and a kind for styling."""
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
