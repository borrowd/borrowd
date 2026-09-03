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
    other_party: BorrowdUser
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    last_message_preview: str | None
    status_label: str
    status_kind: ConversationStatusKind


def item_conversation_threads(
    item: Item,
    viewer: BorrowdUser,
) -> QuerySet[ChatThread]:
    """Return this participant's Item threads with their card data loaded."""
    latest_message = Message.objects.filter(thread_id=OuterRef("pk")).order_by("-pk")

    return (
        ChatThread.objects.filter(item=item)
        .filter(Q(lender=viewer) | Q(borrower=viewer))
        .select_related(
            "lender__profile",
            "borrower__profile",
            "transaction",
        )
        .annotate(
            summary_last_message_at=Subquery(
                latest_message.values("created_at")[:1],
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
            other_party = thread.borrower
        elif viewer.pk == thread.borrower_id:
            other_party = thread.lender
        else:
            raise NotThreadParticipant(
                f"User {viewer.pk} is not a participant of ChatThread {thread.pk}."
            )

        status_label, status_kind = _conversation_status(thread)
        summaries.append(
            ConversationSummary(
                thread_id=thread.pk,
                other_party=other_party,
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
