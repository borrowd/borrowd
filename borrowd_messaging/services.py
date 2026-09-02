from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import QuerySet
from django.db.transaction import atomic
from django.utils import timezone

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item, ItemStatus, Transaction
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user

from .exceptions import (
    ConversationGroupSelectionRequired,
    InvalidConversationGroup,
    InvalidMessageBody,
    MessagingDisabled,
    NotThreadParticipant,
    PreRequestChatUnavailable,
    ThreadNotWritable,
)
from .models import MESSAGE_BODY_MAX_LENGTH, ArchiveReason, ChatThread, Message

ARCHIVE_MESSAGES: dict[ArchiveReason, str] = {
    ArchiveReason.RETURNED: "This item has been returned. Chat is now archived.",
    ArchiveReason.REJECTED: "This request was declined. Chat is now archived.",
    ArchiveReason.CANCELLED: "This request was cancelled. Chat is now archived.",
    ArchiveReason.RESOLVED: "This transaction has been resolved. Chat is now archived.",
    ArchiveReason.OWNERSHIP_TRANSFERRED: (
        "This item has been given away. Chat is now archived."
    ),
    # item has been lent/given away to another person
    ArchiveReason.ITEM_UNAVAILABLE: (
        "This item is no longer available. Chat is now archived."
    ),
    ArchiveReason.ITEM_DELETED: (
        "This item is no longer available. Chat is now archived."
    ),
    # manually closed. I.E., one of the parties decided to end the pre-request chat
    ArchiveReason.CLOSED: "This conversation was closed.",
}

_DISPUTE_NOTICE = (
    "A dispute has been raised on this transaction. Please keep the"
    " conversation respectful; this chat history is retained."
)


class MessagingService:
    @staticmethod
    def _conversation_context_values(
        item: Item,
        conversation_group: BorrowdGroup | None,
    ) -> dict[str, object]:
        """Return the historical context written when a thread is created."""
        return {
            "conversation_group": conversation_group,
            "conversation_group_source_id": (
                conversation_group.pk if conversation_group is not None else None
            ),
            "conversation_group_name": (
                conversation_group.name if conversation_group is not None else None
            ),
            "listing_type": item.listing_type,
        }

    @staticmethod
    def eligible_conversation_groups(
        borrower: BorrowdUser, item: Item
    ) -> QuerySet[BorrowdGroup]:
        """
        Return active groups where both participants are active members and
        the Item is currently shared.
        """
        owner_group_ids = Membership.objects.filter(
            user_id=item.owner_id,
            status=MembershipStatus.ACTIVE,
        ).values_list("group_id", flat=True)
        borrower_group_ids = Membership.objects.filter(
            user=borrower,
            status=MembershipStatus.ACTIVE,
        ).values_list("group_id", flat=True)
        groups = BorrowdGroup.objects.filter(
            pk__in=owner_group_ids,
            deleted_at__isnull=True,
            perms_group__isnull=False,
        ).filter(pk__in=borrower_group_ids)

        if not item.share_with_all_groups:
            groups = groups.filter(
                pk__in=item.shared_with_groups.values_list("pk", flat=True)
            )

        return groups.order_by("name", "pk")

    @classmethod
    def resolve_conversation_group(
        cls,
        borrower: BorrowdUser,
        item: Item,
        selected_group: BorrowdGroup | None = None,
        *,
        require_selection: bool = True,
    ) -> BorrowdGroup | None:
        """
        Validate an explicit group or infer the only eligible group.

        Callers that cannot ask the user to disambiguate may leave multiple
        eligible groups unfiled by passing ``require_selection=False``.
        """
        eligible_groups = cls.eligible_conversation_groups(borrower, item)

        if selected_group is not None:
            resolved_group = eligible_groups.filter(pk=selected_group.pk).first()
            if resolved_group is None:
                raise InvalidConversationGroup(
                    "The selected group is not available for this conversation."
                )
            return resolved_group

        candidates = list(eligible_groups[:2])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1 and require_selection:
            raise ConversationGroupSelectionRequired(
                "Choose a group for this conversation."
            )
        return None

    @staticmethod
    def _active_prerequest_thread(
        borrower: BorrowdUser, item: Item
    ) -> ChatThread | None:
        return ChatThread.objects.filter(
            borrower=borrower,
            item=item,
            archived_at__isnull=True,
            transaction__isnull=True,
        ).first()

    @classmethod
    def get_or_create_prerequest_thread(
        cls,
        borrower: BorrowdUser,
        item: Item,
        selected_group: BorrowdGroup | None = None,
    ) -> ChatThread:
        """
        Return the borrower's open pre-request thread for this item,
        creating one if they have none. Multiple eligible groups require an
        explicit selection for a new conversation.
        """
        if not settings.MESSAGING_ENABLED:
            raise MessagingDisabled("Messaging is not enabled.")
        if borrower.pk == item.owner_id:
            raise PermissionDenied("Owners cannot open a chat about their own item.")
        if not borrower.has_perm(ItemOLP.VIEW, item):
            raise PermissionDenied("Cannot open a chat about an unviewable item.")
        if item.deleted_at is not None or item.status != ItemStatus.AVAILABLE:
            raise PreRequestChatUnavailable("This item is not available.")
        if not item.owner.profile.allow_pre_request_chat:
            raise PreRequestChatUnavailable(
                "This user has turned off messages about their items."
            )

        existing = cls._active_prerequest_thread(borrower, item)
        if existing is not None:
            return existing

        conversation_group = cls.resolve_conversation_group(
            borrower,
            item,
            selected_group=selected_group,
        )

        try:
            with atomic():
                return ChatThread.objects.create(
                    item=item,
                    lender=item.owner,
                    borrower=borrower,
                    created_by=borrower,
                    updated_by=borrower,
                    **cls._conversation_context_values(item, conversation_group),
                )
        except IntegrityError:
            # Race condition catch.
            thread = cls._active_prerequest_thread(borrower, item)
            if thread is None:
                raise
            return thread

    @classmethod
    def send_message(
        cls, thread: ChatThread, sender: BorrowdUser, body: str
    ) -> Message:
        """
        Write one message to a thread.
        """
        if not settings.MESSAGING_ENABLED:
            raise MessagingDisabled("Messaging is not enabled.")
        if sender.pk not in (thread.lender_id, thread.borrower_id):
            raise NotThreadParticipant(
                f"User {sender.pk} is not a participant of ChatThread {thread.pk}."
            )
        with atomic():
            # the thread may have been archived since the caller loaded it.
            current = ChatThread.objects.select_for_update().get(pk=thread.pk)
            if current.is_archived:
                raise ThreadNotWritable(f"ChatThread {thread.pk} is archived.")

            body = body.strip()
            if not body:
                raise InvalidMessageBody("Message body cannot be empty.")
            if len(body) > MESSAGE_BODY_MAX_LENGTH:
                raise InvalidMessageBody(
                    f"Message body cannot exceed {MESSAGE_BODY_MAX_LENGTH} characters."
                )

            message = Message.objects.create(thread=current, sender=sender, body=body)

        cls._dispatch(message)
        return message

    @classmethod
    def attach_thread_to(cls, transaction: Transaction) -> ChatThread:
        """
        Give a new Transaction its thread:
        the open pre-request conversation if there is one,
        otherwise a fresh thread.
        """
        thread = cls.attach_existing_prerequest_thread_to(transaction)
        if thread is not None:
            return thread

        return ChatThread.objects.create(
            transaction=transaction,
            item=transaction.item,
            lender=transaction.party1,
            borrower=transaction.party2,
            created_by=transaction.party2,
            updated_by=transaction.party2,
        )

    @classmethod
    def attach_existing_prerequest_thread_to(
        cls, transaction: Transaction
    ) -> ChatThread | None:
        """
        Give a Transaction its existing pre-request thread, if one exists.

        Unlike attach_thread_to, this method never creates a thread.
        """
        existing = ChatThread.objects.filter(transaction=transaction).first()
        if existing is not None:
            return existing

        thread = cls._active_prerequest_thread(transaction.party2, transaction.item)
        if thread is not None:
            # Conditional so two concurrent requests can't claim the same
            # thread. The caller decides whether a failed claim creates one.
            claimed = ChatThread.objects.filter(
                pk=thread.pk, transaction__isnull=True
            ).update(
                transaction=transaction,
                updated_by=transaction.party2,
                updated_at=timezone.now(),
            )
            if claimed:
                thread.refresh_from_db()
                return thread

        return None

    @classmethod
    def post_system_message(
        cls, thread: ChatThread, body: str, sender: BorrowdUser | None = None
    ) -> Message:
        """
        Write a message from the system user. Sender should probably be system user
        """
        message = Message.objects.create(
            thread=thread,
            sender=sender or get_system_user(),
            is_system=True,
            body=body,
        )
        cls._dispatch(message)
        return message

    @classmethod
    def post_dispute_notice(cls, thread: ChatThread) -> Message:
        """
        Nudge both parties toward civility. The thread stays writable so they
        can still work the dispute out between themselves.
        """
        existing = thread.messages.filter(is_system=True, body=_DISPUTE_NOTICE).first()
        if existing is not None:
            return existing
        return cls.post_system_message(thread, _DISPUTE_NOTICE)

    @classmethod
    def archive_thread(
        cls,
        thread: ChatThread,
        reason: ArchiveReason,
        actor: BorrowdUser | None = None,
        message: str | None = None,
    ) -> None:
        """
        Lock a thread to read-only and explain why. `message` overrides the default copy.
        """
        if thread.is_archived:
            return

        system_user = get_system_user()
        actor = actor or system_user
        now = timezone.now()

        with atomic():
            archived = ChatThread.objects.filter(
                pk=thread.pk, archived_at__isnull=True
            ).update(
                archived_at=now,
                archive_reason=reason,
                updated_by=actor,
                updated_at=now,
            )
            if not archived:
                return

            thread.archived_at = now
            thread.archive_reason = reason
            thread.updated_by = actor
            thread.updated_at = now
            cls.post_system_message(
                thread, message or ARCHIVE_MESSAGES[reason], sender=system_user
            )

    @classmethod
    def archive_prerequest_threads_for_item(
        cls, item: Item, reason: ArchiveReason
    ) -> None:
        """
        Archive every open pre-request chat for an item when it stops being on offer to everyone else:
        it enters a transaction, gets given away, or is deleted.
        """
        threads = ChatThread.objects.filter(
            item=item,
            archived_at__isnull=True,
            transaction__isnull=True,
        )
        for thread in threads:
            cls.archive_thread(thread, reason)

    @classmethod
    def archive_open_threads_for_item(cls, item: Item, reason: ArchiveReason) -> None:
        """Archive every open conversation associated with an Item."""
        threads = ChatThread.objects.filter(
            item=item,
            archived_at__isnull=True,
        )
        for thread in threads:
            cls.archive_thread(thread, reason)

    @classmethod
    def close_prerequest_thread(
        cls, thread: ChatThread, closed_by: BorrowdUser
    ) -> None:
        """
        End a pre-request chat that never became a request. Either party may do this.
        """
        with atomic():
            # the thread may have gained a transaction or been archived since the caller loaded it.
            current = ChatThread.objects.select_for_update().get(pk=thread.pk)
            if closed_by.pk not in (current.lender_id, current.borrower_id):
                raise NotThreadParticipant(
                    f"User {closed_by.pk} is not a participant of ChatThread {thread.pk}."
                )
            if current.transaction_id is not None:
                raise PermissionDenied("Only pre-request conversations can be closed.")
            if current.is_archived:
                raise ThreadNotWritable(f"ChatThread {thread.pk} is already archived.")

            cls.archive_thread(current, ArchiveReason.CLOSED, actor=closed_by)

    @staticmethod
    def _dispatch(message: Message) -> None:
        """
        TODO: this eventually will be where WS would come in.
        A no-op currently.
        """
        return
