from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.transaction import atomic

from borrowd_items.models import Item, ItemStatus
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .exceptions import MessagingDisabled, PreRequestChatUnavailable
from .models import ChatThread


class MessagingService:
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
        cls, borrower: BorrowdUser, item: Item
    ) -> ChatThread:
        """
        Return the borrower's open pre-request thread for this item, creating
        one if they have none.
        """
        if not settings.MESSAGING_ENABLED:
            raise MessagingDisabled("Messaging is not enabled.")
        if borrower.pk == item.owner_id:
            raise PermissionDenied("Owners cannot open a chat about their own item.")
        if not borrower.has_perm(ItemOLP.VIEW, item):
            raise PermissionDenied("Cannot open a chat about an unviewable item.")
        if item.status != ItemStatus.AVAILABLE:
            raise PreRequestChatUnavailable("This item is not available.")
        if not item.owner.profile.allow_pre_request_chat:
            raise PreRequestChatUnavailable(
                "This user has turned off messages about their items."
            )

        existing = cls._active_prerequest_thread(borrower, item)
        if existing is not None:
            return existing

        try:
            with atomic():
                return ChatThread.objects.create(
                    item=item,
                    lender=item.owner,
                    borrower=borrower,
                    created_by=borrower,
                    updated_by=borrower,
                )
        except IntegrityError:
            # Race condition catch.
            thread = cls._active_prerequest_thread(borrower, item)
            if thread is None:
                raise
            return thread
