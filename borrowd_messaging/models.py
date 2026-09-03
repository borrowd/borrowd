from datetime import datetime

from django.db.models import (
    DO_NOTHING,
    PROTECT,
    SET_NULL,
    BooleanField,
    CharField,
    CheckConstraint,
    DateTimeField,
    F,
    ForeignKey,
    Index,
    IntegerField,
    Model,
    OneToOneField,
    PositiveBigIntegerField,
    Q,
    TextChoices,
    UniqueConstraint,
)
from django.utils import timezone

from borrowd_items.models import ListingType
from borrowd_messaging.exceptions import NotThreadParticipant
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.models import BorrowdUser


class ArchiveReason(TextChoices):
    RETURNED = "returned"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    ITEM_UNAVAILABLE = "item_unavailable"
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
    conversation_group = ForeignKey(
        to="borrowd_groups.BorrowdGroup",
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="The group this conversation was filed under, if any.",
    )
    conversation_group_source_id = PositiveBigIntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="The selected group's ID at conversation creation.",
    )
    conversation_group_name = CharField(
        max_length=50,
        null=True,
        blank=True,
        default=None,
        help_text="The selected group's name at conversation creation.",
    )
    listing_type = IntegerField(
        choices=ListingType,
        null=True,
        blank=True,
        default=None,
        help_text="The Item's listing type at conversation creation.",
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
            # Rows leave this partial index once they gain a transaction or are archived
            # See: https://docs.djangoproject.com/en/5.2/ref/models/constraints/#django.db.models.UniqueConstraint.condition
            UniqueConstraint(
                fields=["borrower", "item"],
                condition=Q(archived_at__isnull=True, transaction__isnull=True),
                name="one_active_prerequest_thread_per_borrower_item",
            ),
            CheckConstraint(
                condition=~Q(lender=F("borrower")),
                name="chat_thread_lender_is_not_borrower",
            ),
            CheckConstraint(
                condition=(
                    Q(
                        conversation_group__isnull=True,
                        conversation_group_source_id__isnull=True,
                        conversation_group_name__isnull=True,
                    )
                    | Q(
                        conversation_group_source_id__isnull=False,
                        conversation_group_name__isnull=False,
                    )
                ),
                name="chat_thread_group_context_is_consistent",
            ),
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
        now = timezone.now()
        setattr(self, field, now)
        ChatThread.objects.filter(pk=self.pk).update(**{field: now})


MESSAGE_BODY_MAX_LENGTH = 2000


class Message(Model):
    """
    A single message in a ChatThread.
    Uneditable and undeletable, so there are no update or soft-delete fields;
    `sender` serves as `created_by`.
    """

    thread = ForeignKey(
        to=ChatThread,
        on_delete=PROTECT,
        related_name="messages",
        help_text="The thread this message belongs to.",
    )
    # System messages should be sent by system user; borrowd_users.system.get_system_user()
    sender = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="Who wrote the message. The system user for system messages.",
    )
    is_system = BooleanField(
        default=False,
        help_text="True for messages the app posts itself, e.g. archival notices.",
    )
    body = CharField(
        max_length=MESSAGE_BODY_MAX_LENGTH,
        help_text="The message text. Plain text only.",
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="When the message was sent.",
    )

    class Meta:
        indexes = [
            # For ordering within a thread and cursor pagination
            Index(fields=["thread", "id"], name="msg_thread_cursor_idx"),
        ]
        constraints = [
            CheckConstraint(
                condition=~Q(body=""),
                name="message_body_not_empty",
            )
        ]

    def __str__(self) -> str:
        return f"Message #{self.pk} in ChatThread #{self.thread_id}"
