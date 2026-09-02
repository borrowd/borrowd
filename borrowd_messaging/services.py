from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import QuerySet
from django.db.transaction import atomic
from django.utils import timezone

from borrowd_groups.models import BorrowdGroup, MembershipStatus
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
    def conversation_group_selection(
        raw_group_id: str | None,
    ) -> BorrowdGroup | None:
        """Resolve an optional submitted group ID to a Group."""
        if raw_group_id is None or raw_group_id == "":
            return None

        try:
            group_id = int(raw_group_id)
        except ValueError as exc:
            raise InvalidConversationGroup(
                "The selected group is not available for this conversation."
            ) from exc

        selected_group = BorrowdGroup.objects.filter(pk=group_id).first()
        if selected_group is None:
            raise InvalidConversationGroup(
                "The selected group is not available for this conversation."
            )
        return selected_group

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

    @classmethod
    def _transaction_conversation_context_values(
        cls,
        transaction: Transaction,
    ) -> dict[str, object]:
        """
        Infer context for a fresh transaction thread only while the Item still
        belongs to the transaction's original lender.
        """
        item = transaction.item
        if item.owner_id != transaction.party1_id:
            return {}

        conversation_group = cls.resolve_conversation_group(
            transaction.party2,
            item,
            require_selection=False,
        )
        return cls._conversation_context_values(item, conversation_group)

    @staticmethod
    def eligible_conversation_groups(
        borrower: BorrowdUser, item: Item
    ) -> QuerySet[BorrowdGroup]:
        """
        Return active groups where both participants are active members and
        the Item is currently shared.
        """
        groups = item.groups_allowed_to_view().filter(
            deleted_at__isnull=True,
            membership__user=borrower,
            membership__status=MembershipStatus.ACTIVE,
        )

        return groups.order_by("name", "pk")

    @staticmethod
    def request_group_choices_for_items(
        borrower: BorrowdUser,
        items: list[Item],
    ) -> dict[int, tuple[BorrowdGroup, ...]]:
        """
        Return ambiguous Group choices for direct requests in one batch.

        Items with an active pre-request thread already have conversation
        context. Zero or one eligible Group can also be resolved without a
        choice, so neither case is included in the result.
        """
        items_by_id = {item.pk: item for item in items}
        if not items_by_id:
            return {}

        existing_thread_item_ids = set(
            ChatThread.objects.filter(
                borrower=borrower,
                item_id__in=items_by_id,
                archived_at__isnull=True,
                transaction__isnull=True,
            ).values_list("item_id", flat=True)
        )
        items_needing_context = {
            item_id: item
            for item_id, item in items_by_id.items()
            if item_id not in existing_thread_item_ids
        }
        if not items_needing_context:
            return {}

        borrower_groups = list(
            BorrowdGroup.objects.filter(
                membership__user=borrower,
                membership__status=MembershipStatus.ACTIVE,
                deleted_at__isnull=True,
                perms_group__isnull=False,
            ).order_by("name", "pk")
        )
        if len(borrower_groups) < 2:
            return {}

        group_ids = [group.pk for group in borrower_groups]
        owner_group_pairs = set(
            Membership.objects.filter(
                user_id__in={item.owner_id for item in items_needing_context.values()},
                group_id__in=group_ids,
                status=MembershipStatus.ACTIVE,
            ).values_list("user_id", "group_id")
        )

        explicitly_shared_item_ids = [
            item.pk
            for item in items_needing_context.values()
            if not item.share_with_all_groups
        ]
        explicit_item_group_pairs = set(
            BorrowdGroup.objects.filter(
                shared_items__pk__in=explicitly_shared_item_ids,
                pk__in=group_ids,
            ).values_list("shared_items__pk", "pk")
        )

        choices: dict[int, tuple[BorrowdGroup, ...]] = {}
        for item_id, item in items_needing_context.items():
            eligible_groups = tuple(
                group
                for group in borrower_groups
                if (item.owner_id, group.pk) in owner_group_pairs
                and (
                    item.share_with_all_groups
                    or (item_id, group.pk) in explicit_item_group_pairs
                )
            )
            if len(eligible_groups) > 1:
                choices[item_id] = eligible_groups

        return choices

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

    @staticmethod
    def _validate_thread_participants(borrower: BorrowdUser, item: Item) -> None:
        """Validate the participants and Item shared by thread entry paths."""
        if not settings.MESSAGING_ENABLED:
            raise MessagingDisabled("Messaging is not enabled.")
        if borrower.pk == item.owner_id:
            raise PermissionDenied("Owners cannot open a chat about their own item.")
        if not borrower.has_perm(ItemOLP.VIEW, item):
            raise PermissionDenied("Cannot open a chat about an unviewable item.")
        if item.deleted_at is not None or item.status != ItemStatus.AVAILABLE:
            raise PreRequestChatUnavailable("This item is not available.")

    @classmethod
    def _create_prerequest_thread(
        cls,
        borrower: BorrowdUser,
        item: Item,
        conversation_group: BorrowdGroup | None,
    ) -> ChatThread:
        """Create a pre-request thread, or return the concurrent winner."""
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
            thread = cls._active_prerequest_thread(borrower, item)
            if thread is None:
                raise
            return thread

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
        cls._validate_thread_participants(borrower, item)
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

        return cls._create_prerequest_thread(borrower, item, conversation_group)

    @classmethod
    def prepare_thread_for_request(
        cls,
        borrower: BorrowdUser,
        item: Item,
        selected_group: BorrowdGroup | None = None,
    ) -> ChatThread:
        """
        Create or reuse the thread that an immediate Item request will claim.

        Direct requests are independent of the lender's pre-request-chat
        preference because they start the normal Transaction lifecycle.
        """
        cls._validate_thread_participants(borrower, item)

        existing = cls._active_prerequest_thread(borrower, item)
        if existing is not None:
            return existing

        conversation_group = cls.resolve_conversation_group(
            borrower,
            item,
            selected_group=selected_group,
        )
        return cls._create_prerequest_thread(borrower, item, conversation_group)

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
            **cls._transaction_conversation_context_values(transaction),
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
