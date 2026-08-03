from datetime import datetime

from django.db.models import (
    DO_NOTHING,
    PROTECT,
    SET_NULL,
    CharField,
    DateTimeField,
    ForeignKey,
    Model,
    OneToOneField,
    Q,
    TextChoices,
    UniqueConstraint,
)
from django.utils import timezone

from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.models import BorrowdUser


class ArchiveReason(TextChoices):
    RETURNED = "returned"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    ITEM_DELETED = "item_deleted"
    CLOSED = "closed"


class ChatThread(Model):
    transaction = OneToOneField(
        to="borrowd_items.Transaction",
        null=True,
        blank=True,
        default=None,
        on_delete=PROTECT,
        related_name="chat_thread",
        help_text=(
            "The Transaction this thread belongs to. NULL while the thread"
            " is in the pre-request phase."
        ),
    )
    item = ForeignKey(
        to="borrowd_items.Item",
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="chat_threads",
        help_text="The Item under discussion. NULL after the item is hard-deleted.",
    )
    lender = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The item's owner at thread creation.",
    )
    borrower = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The user who opened (or requested via) this thread.",
    )
    archived_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the thread becomes read-only. NULL means active.",
    )
    archive_reason = CharField(
        max_length=32,
        choices=ArchiveReason.choices,
        null=True,
        blank=True,
        default=None,
        help_text="Why the thread was archived. NULL for active threads.",
    )
    lender_last_read_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="When the lender last opened the thread. NULL means never.",
    )
    borrower_last_read_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="When the borrower last opened the thread. NULL means never.",
    )
    created_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the thread.",
        on_delete=DO_NOTHING,
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the thread was created.",
    )
    updated_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the thread.",
        on_delete=DO_NOTHING,
    )
    updated_at = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the thread was last updated.",
    )

    class Meta:
        constraints = [
            # Rows leave this partial index once they gain a transaction or
            # archive, so a pair can hold many historical threads.
            UniqueConstraint(
                fields=["borrower", "item"],
                condition=Q(archived_at__isnull=True, transaction__isnull=True),
                name="one_active_prerequest_thread_per_borrower_item",
            )
        ]
        permissions = [
            (ChatThreadOLP.VIEW, "Can view this chat thread"),
        ]

    def __str__(self) -> str:
        return f"ChatThread #{self.pk}"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def _last_read_field_for(self, user: BorrowdUser) -> str:
        if user.pk == self.lender_id:
            return "lender_last_read_at"
        if user.pk == self.borrower_id:
            return "borrower_last_read_at"
        raise NotThreadParticipant(
            f"User {user.pk} is not a participant of ChatThread {self.pk}."
        )

    def last_read_at_for(self, user: BorrowdUser) -> datetime | None:
        value: datetime | None = getattr(self, self._last_read_field_for(user))
        return value

    def mark_read(self, user: BorrowdUser) -> None:
        field = self._last_read_field_for(user)
        setattr(self, field, timezone.now())
        self.save(update_fields=[field, "updated_at"])
