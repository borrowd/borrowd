import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    SET_NULL,
    BooleanField,
    CharField,
    DateTimeField,
    F,
    ForeignKey,
    Index,
    IntegerChoices,
    IntegerField,
    ManyToManyField,
    Model,
    PositiveBigIntegerField,
    PositiveSmallIntegerField,
    Q,
    QuerySet,
    TextField,
    UniqueConstraint,
    UUIDField,
)
from django.dispatch import Signal
from django.urls import reverse
from django.utils import timezone
from imagekit.models import ImageSpecField, ProcessedImageField
from imagekit.processors import ResizeToFill, ResizeToFit

from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .exceptions import (
    AccountInactive,
    InvalidItemAction,
    ItemAlreadyRequested,
    TransactionLenderMismatch,
)
from .flow import available_actions, execute_transition
from .processors import AutoOrientProcessor

# Defined in statuses.py; re-exported for importers of this module.
from .statuses import (
    BORROWER_TRANSACTION_STATUSES as BORROWER_TRANSACTION_STATUSES,
)
from .statuses import (
    DUAL_CONFIRMATION_TRANSACTION_STATUSES as DUAL_CONFIRMATION_TRANSACTION_STATUSES,
)
from .statuses import (
    GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES as GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES,
)
from .statuses import ITEM_STATUS_FOR_TRANSACTION as ITEM_STATUS_FOR_TRANSACTION
from .statuses import OPEN_TRANSACTION_STATUSES as OPEN_TRANSACTION_STATUSES
from .statuses import (
    PRE_COLLECTION_TRANSACTION_STATUSES as PRE_COLLECTION_TRANSACTION_STATUSES,
)
from .statuses import REQUEST_TRANSACTION_STATUSES as REQUEST_TRANSACTION_STATUSES
from .statuses import TERMINAL_TRANSACTION_STATUSES as TERMINAL_TRANSACTION_STATUSES
from .statuses import ItemAction as ItemAction
from .statuses import ItemStatus as ItemStatus
from .statuses import ResolutionReason as ResolutionReason
from .statuses import TransactionStatus as TransactionStatus
from .statuses import sync_item_status as sync_item_status

if TYPE_CHECKING:
    from borrowd_groups.models import BorrowdGroup

logger = logging.getLogger("borrowd.items")


class ActiveItemQuerySet(QuerySet["Item"]):
    def active(self) -> "ActiveItemQuerySet":
        return self.filter(deleted_at__isnull=True)

    def deleted(self) -> "ActiveItemQuerySet":
        return self.filter(deleted_at__isnull=False)


class ActiveItemManager(models.Manager["Item"]):
    def get_queryset(self) -> ActiveItemQuerySet:
        return ActiveItemQuerySet(self.model, using=self._db).active()


@dataclass
class ItemActionContext:
    """
    Container for item actions and related context information.
    Combines action buttons with status text, eliminating the need for
    separate frontend logic and multiple DB calls.
    """

    actions: tuple[ItemAction, ...]
    status_text: str
    # Non-interactive text to show in place of action buttons
    waiting_text: str | None = None


@dataclass
class PrecomputedItemState:
    """
    Item card state computed once by a caller that's about to ask for both
    action context and banner info for the same item, so neither has to
    re-derive it independently.
    """

    current_borrower: BorrowdUser | None
    requesting_user: BorrowdUser | None
    current_transaction: Optional["Transaction"]
    has_active_subscription: bool = False

    @classmethod
    def from_transaction(
        cls,
        transaction: Optional["Transaction"],
        *,
        has_active_subscription: bool = False,
    ) -> "PrecomputedItemState":
        """Derive the state from the item's open transaction without querying."""
        current_borrower = None
        requesting_user = None
        if transaction is not None:
            if transaction.status in REQUEST_TRANSACTION_STATUSES:
                requesting_user = transaction.party2
            elif transaction.status in BORROWER_TRANSACTION_STATUSES:
                current_borrower = transaction.party2
        return cls(
            current_borrower=current_borrower,
            requesting_user=requesting_user,
            current_transaction=transaction,
            has_active_subscription=has_active_subscription,
        )

    def current_transaction_for_user(
        self, user: BorrowdUser
    ) -> Optional["Transaction"]:
        """
        Returns the current Transaction if the given user is a party to it,
        mirroring Item.get_current_transaction_for_user().
        """
        transaction = self.current_transaction
        if transaction is not None and user.id in (
            transaction.party1_id,
            transaction.party2_id,
        ):
            return transaction
        return None


class ItemCategory(Model):
    name = CharField(max_length=50, null=False, blank=False)
    description = CharField(max_length=100, null=True, blank=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Item Category"
        verbose_name_plural = "Item Categories"


class ListingType(IntegerChoices):
    """
    How an Item is offered to the community: for borrowing (the
    default) or as a giveaway a group member can request to keep.
    """

    LEND = 10, "Lend"
    GIVEAWAY = 20, "Give away"


class Item(Model):
    name = CharField(max_length=50, null=False, blank=False)
    description = CharField(max_length=500, null=False, blank=False)
    # If user is deleted, delete their Items
    owner = ForeignKey(BorrowdUser, on_delete=CASCADE)

    categories = ManyToManyField(
        ItemCategory,
        related_name="items",
        blank=False,
        help_text="Categories this item belongs to. At least one required.",
    )
    share_with_all_groups = BooleanField(
        default=True,
        help_text="When True, item is visible to all current AND future groups",
    )
    shared_with_groups = ManyToManyField(
        "borrowd_groups.BorrowdGroup",
        blank=True,
        help_text="The groups in which the item is shared.",
        related_name="shared_items",
    )
    status = IntegerField(
        choices=ItemStatus.choices,
        default=ItemStatus.AVAILABLE,
        help_text="The current status of the Item.",
    )
    listing_type = IntegerField(
        choices=ListingType,
        default=ListingType.LEND,
        help_text=(
            "Whether this Item is offered for borrowing or as a"
            " giveaway a group member can request to keep."
        ),
    )
    created_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the item.",
        on_delete=DO_NOTHING,
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the item was created.",
    )
    updated_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the item.",
        on_delete=DO_NOTHING,
    )
    updated_at = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the item was last updated.",
    )
    deleted_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )
    revision = PositiveBigIntegerField(
        default=0,
        db_default=0,
        editable=False,
        help_text=(
            "Advances on every change to the item or its transactions, so a "
            "client can tell that what it showed is out of date."
        ),
    )
    objects = ActiveItemManager()
    all_objects = models.Manager()

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        advancing = not self._state.adding
        if advancing:
            # Incremented by the database, so two writers can't land on one value.
            self.revision = F("revision") + 1
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "revision"}
        super().save(*args, **kwargs)
        if advancing:
            self.refresh_from_db(fields=["revision"])

    def get_absolute_url(self) -> str:
        return reverse("item-detail", args=[self.pk])

    def clean(self) -> None:
        """Validate that Item has at least one category assigned."""
        super().clean()
        # M2M validation only works for saved instances
        if self.pk and not self.categories.exists():
            raise ValidationError({"categories": "At least one category is required."})

    @classmethod
    def lock_for_update(
        cls, pk: int, *, select_related: tuple[str, ...] = ()
    ) -> "Item":
        """Lock this item's row, deleted or not, and return it fresh."""
        # of=("self",): lock the item only, not the rows select_related joins in.
        # https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
        queryset = cls.all_objects.select_for_update(of=("self",))
        if select_related:
            queryset = queryset.select_related(*select_related)
        return queryset.get(pk=pk)

    def soft_delete(self, deleted_by: BorrowdUser) -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save()

    def get_action_context_for(
        self,
        user: BorrowdUser,
        precomputed: PrecomputedItemState | None = None,
    ) -> ItemActionContext:
        """
        Returns ItemActionContext containing ItemActions [e.g. REQUEST_ITEM, ACCEPT_REQUEST]
        and status information [e.g. "You are currently borrowing this item."] for the given user.

        `precomputed`, if given, skips re-deriving current_borrower/
        requesting_user for callers that already computed them (e.g. to
        also build banner info for the same item without asking twice).
        """

        if precomputed is None:
            precomputed = self.precompute_state_for(user)
        current_borrower = precomputed.current_borrower
        requesting_user = precomputed.requesting_user
        current_tx = precomputed.current_transaction_for_user(user)
        actions = self.get_actions_for(user, precomputed=precomputed)

        # Generate status text based on user role and current actions/status
        status_text = self._get_status_text_for_user(
            user=user,
            actions=actions,
            current_borrower=current_borrower,
            requesting_user=requesting_user,
            current_tx=current_tx,
            precomputed=precomputed,
        )

        # The borrower who asserted return of a requested item must wait for
        # the lender to confirm the item has been returned.
        waiting_text = None
        if (
            current_tx is not None
            and current_tx.status == TransactionStatus.RETURN_ASSERTED
            and current_tx.return_requested_at is not None
            and current_tx.updated_by_id == user.id
        ):
            waiting_text = "Waiting on confirmation from lender..."

        return ItemActionContext(
            actions=actions, status_text=status_text, waiting_text=waiting_text
        )

    def precompute_state_for(self, user: BorrowdUser) -> PrecomputedItemState:
        """Read the item's open transaction once and derive the user's state."""
        current_tx = self.get_current_transaction()
        needs_subscription_state = self.owner_id != user.id and (
            current_tx is not None or self.status != ItemStatus.AVAILABLE
        )
        has_active_subscription = (
            AvailabilitySubscription.objects.filter(
                item=self,
                user=user,
                status=AvailabilitySubscriptionStatus.ACTIVE,
            ).exists()
            if needs_subscription_state
            else False
        )
        return PrecomputedItemState.from_transaction(
            current_tx, has_active_subscription=has_active_subscription
        )

    def _get_status_text_for_user(
        self,
        user: BorrowdUser,
        actions: tuple[ItemAction, ...],
        current_borrower: BorrowdUser | None,
        requesting_user: BorrowdUser | None,
        current_tx: Optional["Transaction"] = None,
        precomputed: PrecomputedItemState | None = None,
    ) -> str:
        """Generate context-appropriate status text for the user."""
        # Determine user role
        is_owner = self.owner_id == user.id
        is_borrower = current_borrower and current_borrower == user

        # Get display names (with privacy considerations)
        requester_name = (
            requesting_user.profile.full_name() if requesting_user else "Someone"
        )
        borrower_name = (
            current_borrower.profile.full_name() if current_borrower else "Borrower"
        )

        if is_owner:
            return self._get_owner_status_text(
                actions, requester_name, borrower_name, current_tx
            )
        elif is_borrower:
            return self._get_borrower_status_text(actions, current_tx)
        else:
            return self._get_other_user_status_text(actions, user, precomputed)

    def _get_owner_status_text(
        self,
        actions: tuple[ItemAction, ...],
        requester_name: str,
        borrower_name: str,
        current_tx: Optional["Transaction"] = None,
    ) -> str:
        """Generate status text for item owners."""
        tx_status = current_tx.status if current_tx else None

        if tx_status == TransactionStatus.DISPUTED:
            return f"This item is being disputed. Use 'resolve dispute' once you've settled it with {borrower_name}."
        elif tx_status == TransactionStatus.GIVEAWAY_OFFERED:
            return f"Giveaway offered to {borrower_name} - awaiting acceptance."
        elif tx_status == TransactionStatus.RETURN_REQUESTED:
            return f"You requested this item back from {borrower_name}. Confirm once you receive it."
        elif tx_status == TransactionStatus.GIVEAWAY_REQUESTED:
            return f"{requester_name} wants your giveaway!"
        elif ItemAction.ACCEPT_REQUEST in actions:
            return f"{requester_name} has requested to borrow this item!"
        elif (
            ItemAction.MARK_COLLECTED in actions
            and ItemAction.CANCEL_REQUEST in actions
        ):
            return f"You've accepted {borrower_name}'s borrow request, please mark the item as Collected when you've given it to them."
        elif ItemAction.CONFIRM_COLLECTED in actions:
            return (
                f"{borrower_name} marked item as collected, confirm you have lent it."
            )
        elif ItemAction.MARK_RETURNED in actions:
            return f"You are currently lending this item to {borrower_name}. Mark it as returned when you have received it back."
        elif ItemAction.CONFIRM_RETURNED in actions:
            return f"{borrower_name} marked item as returned, confirm you have received it back."
        elif self.status == ItemStatus.RESERVED:
            return f"You've marked this item as lent, waiting for {borrower_name} to confirm collected."
        elif self.status == ItemStatus.BORROWED:
            return f"Waiting for {borrower_name} to confirm returned."
        elif self.listing_type == ListingType.GIVEAWAY:
            return "This is your item, listed as a giveaway."
        else:
            return "This is your item and it is available for borrowing."

    # Permit borrower to see owner name in status text
    def _get_borrower_status_text(
        self,
        actions: tuple[ItemAction, ...],
        current_tx: Optional["Transaction"] = None,
    ) -> str:
        owner_name = self.owner.profile.full_name()
        """Generate status text for current borrowers."""
        tx_status = current_tx.status if current_tx else None

        if tx_status == TransactionStatus.DISPUTED:
            return "This item is being disputed. Please coordinate with the owner to make it right."
        elif tx_status == TransactionStatus.GIVEAWAY_OFFERED:
            return f"{owner_name} is offering you this item! Accept the gift to make it yours."
        elif tx_status == TransactionStatus.RETURN_REQUESTED:
            return f"{owner_name} has requested this item back. Please coordinate its return."
        elif ItemAction.CANCEL_REQUEST in actions:
            return f"{owner_name} accepted request, mark Collected when you have received the item."
        elif ItemAction.CONFIRM_COLLECTED in actions:
            return (
                f"{owner_name} marked item as collected, confirm you have received it."
            )
        elif ItemAction.MARK_RETURNED in actions:
            return f"You are currently borrowing this item. Mark it as returned when you have returned it to {owner_name}."
        elif ItemAction.CONFIRM_RETURNED in actions:
            return (
                f"{owner_name} marked item as returned, confirm you have given it back."
            )
        elif len(actions) == 0 and self.status == ItemStatus.RESERVED:
            return "You're currently borrowing this item!"
        elif len(actions) == 0 and self.status == ItemStatus.BORROWED:
            return f"Waiting {owner_name} confirmation of returned item."
        else:
            return "Not available for borrowing"

    def _get_other_user_status_text(
        self,
        actions: tuple[ItemAction, ...],
        user: BorrowdUser,
        precomputed: PrecomputedItemState | None = None,
    ) -> str:
        """Generate status text for users who are neither owner nor borrower."""
        if len(actions) == 1 and ItemAction.CANCEL_REQUEST in actions:
            # Intentionally obscuring owner name here for privacy to reject
            if self.listing_type == ListingType.GIVEAWAY:
                return "Gift requested, waiting on owner response..."
            return "Requested to borrow, waiting on owner response..."
        elif ItemAction.REQUEST_ITEM in actions:
            return "Available to request!"
        elif ItemAction.REQUEST_GIVEAWAY in actions:
            return "Free to keep!"
        elif (
            precomputed is not None
            and precomputed.has_active_subscription
            or (
                precomputed is None
                and AvailabilitySubscription.get_active_subscription_for_user_and_item(
                    user=user, item=self
                )
                is not None
            )
        ):
            return "You've requested to be notified when this item is available again."
        elif precomputed is not None and precomputed.requesting_user is not None:
            return "Item is reserved"
        elif precomputed is None and self.get_requesting_user() is not None:
            # There's a pending request from another user
            return "Item is reserved"
        else:
            return "Not available for borrowing"

    def get_actions_for(
        self,
        user: BorrowdUser,
        precomputed: PrecomputedItemState | None = None,
    ) -> tuple[ItemAction, ...]:
        """
        Returns a tuple of ItemAction objects representing the
        current valid actions that the given User may perform on this
        Item.

        The actions are determined by:
        - The status of the Item itself
        - The status of the current open Transaction involving this
          Item and the given User, if any.
        """
        if precomputed is not None:
            current_tx = precomputed.current_transaction_for_user(user)
            current_borrower = precomputed.current_borrower
            requesting_user = precomputed.requesting_user
            has_active_subscription = precomputed.has_active_subscription
        else:
            current_tx = self.get_current_transaction_for_user(user)
            current_borrower = self.get_current_borrower()
            requesting_user = self.get_requesting_user()
            has_active_subscription = None

        # IF there are no current Txns involving this user...
        if current_tx is None:
            #   AND the item status Available,
            #   AND the user is not the owner,
            #   AND there's no pending request from another user
            if (
                self.status == ItemStatus.AVAILABLE
                and self.owner_id != user.id
                and requesting_user is None
            ):
                # THEN
                #   the User can Request the Item,
                #   or ask to keep it if it's a giveaway listing.
                if self.listing_type == ListingType.GIVEAWAY:
                    return (ItemAction.REQUEST_GIVEAWAY,)
                return (ItemAction.REQUEST_ITEM,)
            is_borrowable = (
                self.status == ItemStatus.AVAILABLE
                and current_borrower is None
                and (requesting_user is None or requesting_user == user)
            )
            if not is_borrowable and self.owner_id != user.id:
                if has_active_subscription is None:
                    has_active_subscription = AvailabilitySubscription.objects.filter(
                        user=user,
                        item=self,
                        status=AvailabilitySubscriptionStatus.ACTIVE,
                    ).exists()
            if (
                not is_borrowable
                and not has_active_subscription
                and self.owner_id != user.id
            ):
                # If the item is currently BORROWED or RESERVED by another user,
                # allow requesting notification for when it becomes available again
                return (ItemAction.NOTIFY_WHEN_AVAILABLE,)
            if (
                not is_borrowable
                and has_active_subscription
                and self.owner_id != user.id
            ):
                # If the item is currently BORROWED or RESERVED by another user,
                # but the current user has an active subscription, allow cancelling the subscription
                return (ItemAction.CANCEL_NOTIFICATION_REQUEST,)

            # At this point, either:
            # - the user is the owner of the item (and thus can't request to borrow it), or
            # - the item is not borrowable and no notify/cancel-notify action applies.
            # NOTE Later we may want to allow new Requests on Items
            # even when they're currently Borrowed; that will
            # imply date-based borrowing bookings, which we're
            # not tackling yet.
            return tuple()

        return available_actions(current_tx, user, now=timezone.now())

    def get_requesting_user(self) -> BorrowdUser | None:
        """
        Returns the User with an open borrow or giveaway request on
        this Item, if any.
        """
        try:
            transaction = Transaction.objects.get(
                Q(item=self) & Q(status__in=REQUEST_TRANSACTION_STATUSES)
            )
            # party2 is the requestor
            return transaction.party2
        except Transaction.DoesNotExist:
            return None

    def get_current_borrower(self) -> BorrowdUser | None:
        """
        Returns the User who is currently borrowing this Item, if any.
        """
        # Look for an active transaction where the item is borrowed or reserved
        try:
            transaction = Transaction.objects.get(
                Q(item=self) & Q(status__in=BORROWER_TRANSACTION_STATUSES)
            )
            # party2 is the borrower
            return transaction.party2
        except Transaction.DoesNotExist:
            return None

    def get_current_transaction(self) -> Optional["Transaction"]:
        """
        Returns the transaction involving this item regardless of the user
        """
        return (
            Transaction.objects.select_related(
                "party1",
                "party1__profile",
                "party2",
                "party2__profile",
            )
            .filter(Q(item=self) & Q(status__in=OPEN_TRANSACTION_STATUSES))
            .first()
        )

    def get_current_transaction_for_user(
        self, user: BorrowdUser
    ) -> Optional["Transaction"]:
        """
        Returns the current Transaction involving this Item and the
        given User, if any.
        """
        try:
            return Transaction.objects.get(
                Q(item=self)
                & (Q(party1=user) | Q(party2=user))
                & Q(status__in=OPEN_TRANSACTION_STATUSES)
            )
        except Transaction.DoesNotExist:
            return None

    def is_borrowable(self, user: BorrowdUser | None = None) -> bool:
        if self.status != ItemStatus.AVAILABLE:
            return False

        active_borrow = self.get_current_borrower()
        if active_borrow:
            return False

        active_request = self.get_requesting_user()

        if active_request and active_request != user:
            return False

        return True

    @classmethod
    def lock_for_action(cls, user: BorrowdUser, pk: int) -> "Item":
        """Lock the acting account, then the item, and return the item fresh."""
        if not BorrowdUser.lock_account(user.pk).is_active:
            raise AccountInactive("This account is no longer active.")
        return cls.lock_for_update(pk, select_related=("owner",))

    def process_action(self, user: BorrowdUser, action: ItemAction) -> None:
        """
        Process the given action for this Item and User.
        """
        with transaction.atomic():
            item = Item.lock_for_action(user, self.pk)
            item._process_action_locked(user, action)
            self.refresh_from_db()

    def _process_action_locked(
        self,
        user: BorrowdUser,
        action: ItemAction,
        *,
        command_key: UUID | None = None,
    ) -> Optional["Transaction"]:
        """Apply the action and return the transaction it opened or moved."""
        # A deleted item stays reachable only to close out a stranded loan.
        if self.deleted_at is not None and action != ItemAction.RESOLVE_TRANSACTION:
            raise InvalidItemAction("This item is no longer available.")

        state = self.precompute_state_for(user)
        current_tx = state.current_transaction_for_user(user)
        if current_tx is not None and current_tx.party1_id != self.owner_id:
            logger.error(
                "Open transaction %s has lender %s but item %s is owned by %s.",
                current_tx.pk,
                current_tx.party1_id,
                self.pk,
                self.owner_id,
            )
            raise TransactionLenderMismatch(
                f"Transaction {current_tx.pk} and Item {self.pk} disagree on the lender."
            )

        # Check for specific case: trying to request an item that already has a pending request
        if (
            action in (ItemAction.REQUEST_ITEM, ItemAction.REQUEST_GIVEAWAY)
            and state.requesting_user is not None
        ):
            raise ItemAlreadyRequested(
                f"Item '{self}' already has a pending request from another user."
            )

        valid_actions = self.get_actions_for(user=user, precomputed=state)
        if action not in valid_actions:
            raise InvalidItemAction(
                f"User '{user}' cannot perform action '{action}' on"
                f"Item '{self}' at this time."
            )

        if action == ItemAction.REQUEST_ITEM:
            return self._open_request(
                user, TransactionStatus.REQUESTED, action, command_key
            )

        if action == ItemAction.REQUEST_GIVEAWAY:
            return self._open_request(
                user, TransactionStatus.GIVEAWAY_REQUESTED, action, command_key
            )

        if (
            action == ItemAction.NOTIFY_WHEN_AVAILABLE
            and not self.is_borrowable(user=user)
            and AvailabilitySubscription.get_active_subscription_for_user_and_item(
                user=user, item=self
            )
            is None
        ):
            AvailabilitySubscription.objects.create(
                user=user,
                item=self,
                status=AvailabilitySubscriptionStatus.ACTIVE,
            )
            self.advance_revision()
            return None

        if (
            action == ItemAction.CANCEL_NOTIFICATION_REQUEST
            and not self.is_borrowable(user=user)
            and AvailabilitySubscription.get_active_subscription_for_user_and_item(
                user=user, item=self
            )
            is not None
        ):
            subscription = (
                AvailabilitySubscription.get_active_subscription_for_user_and_item(
                    user=user, item=self
                )
            )
            if subscription:
                subscription.cancel_subscription()
            self.advance_revision()
            return None

        if current_tx is None:
            # This should have been caught earlier, but check again
            # partly to keep mypy happy.
            raise ValueError("No existing Transaction")

        source = TransactionStatus(current_tx.status)
        applied = execute_transition(self, current_tx, user, action, now=timezone.now())
        LifecycleEvent.record(
            current_tx,
            source=source,
            target=applied.target,
            actor=user,
            action=action,
            command_key=command_key,
        )
        return current_tx

    def advance_revision(self) -> None:
        """Count a change that wrote no item or transaction row, like a subscription."""
        Item.all_objects.filter(pk=self.pk).update(revision=F("revision") + 1)
        self.refresh_from_db(fields=["revision"])

    def _open_request(
        self,
        user: BorrowdUser,
        status: TransactionStatus,
        action: ItemAction,
        command_key: UUID | None,
    ) -> "Transaction":
        try:
            # A savepoint, so losing to the one-open-transaction constraint
            # leaves the enclosing transaction usable for the check below.
            with transaction.atomic():
                created_tx = Transaction.objects.create(
                    item=self,
                    # By convention "party1" is the owner/lender/giver.
                    party1=self.owner,
                    party2=user,
                    created_by=user,
                    updated_by=user,
                    status=status,
                )
        except IntegrityError:
            if not Transaction.objects.filter(
                item=self, status__in=OPEN_TRANSACTION_STATUSES
            ).exists():
                raise
            raise ItemAlreadyRequested(
                f"Item '{self}' already has an open transaction."
            ) from None
        sync_item_status(self, created_tx)
        LifecycleEvent.record(
            created_tx,
            source=None,
            target=status,
            actor=user,
            action=action,
            command_key=command_key,
        )
        return created_tx

    def groups_allowed_to_view(self) -> "QuerySet[BorrowdGroup]":
        """
        The owner's active groups that may see this item.

        When share_with_all_groups is True, all active groups qualify.
        When False, only groups explicitly listed in shared_with_groups qualify.
        """
        from borrowd_groups.models import BorrowdGroup, MembershipStatus

        owner_active_groups = BorrowdGroup.objects.filter(
            membership__user_id=self.owner_id,
            membership__status=MembershipStatus.ACTIVE,
        ).exclude(perms_group=None)

        if self.share_with_all_groups:
            return owner_active_groups
        return owner_active_groups.filter(
            pk__in=self.shared_with_groups.values_list("pk", flat=True)
        )

    def recompute_group_visibility(self) -> None:
        """
        Re-derive this item's group-level VIEW permissions for the current owner.

        revokes VIEW perms for the item from every group that currently can has the perm,
        then grants VIEW perms to the owner's allowed groups.
        """
        from django.contrib.auth.models import Group
        from guardian.shortcuts import assign_perm, get_groups_with_perms, remove_perm

        # guardian mis-types get_groups_with_perms as `Group | dict`; for the
        # default attach_perms=False it returns a QuerySet[Group].
        groups_that_can_view_item = cast("QuerySet[Group]", get_groups_with_perms(self))
        # Pass the queryset straight through rather than looping: remove_perm
        # dispatches a single bulk DELETE for a group queryset, vs. one DELETE
        # round-trip per currently-permitted group in a Python loop.
        remove_perm(ItemOLP.VIEW, groups_that_can_view_item, self)

        allowed_groups = Group.objects.filter(
            pk__in=self.groups_allowed_to_view().values_list("perms_group", flat=True)
        )
        assign_perm(ItemOLP.VIEW, allowed_groups, self)

    def _transfer_ownership(self, new_owner: BorrowdUser, by: BorrowdUser) -> None:
        """
        Permanently hand this Item to new_owner.

        Reassigns ownership in place: the same Item record (and its photos,
        description, categories) shows up in the new owner's inventory and leaves the old owner's.
        """
        from guardian.shortcuts import assign_perm, remove_perm

        old_owner = self.owner

        # Reassign and save. The post_save signal recomputes group VIEW for the new owner
        # see signals.py
        self.owner = new_owner
        self.status = ItemStatus.AVAILABLE
        # The recipient owns it as a regular item; they can relist it themselves.
        self.listing_type = ListingType.LEND
        self.updated_by = by
        self.save()

        # Group VIEW is handled by the signal. Personal perms are granted only on create
        # so hand the old owner's personal perms to the new owner.
        for perm in [ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE]:
            remove_perm(perm, old_owner, self)
            assign_perm(perm, new_owner, self)

        # Outstanding "notify me when available" subs are moot now.
        for subscription in AvailabilitySubscription.get_active_subscriptions_for_item(
            self
        ):
            subscription.cancel_subscription()

    class Meta:
        # Permissions using the naming conventon `*_this_*` are used
        # for object-/record-level permissions: whereas the permission
        # `view_item` would allow a user to view "any" Item, the
        # permission `ItemOLP.VIEW` allows viewing a specific Item.
        permissions = [
            (
                ItemOLP.VIEW,
                "Can view this item",
            ),
            (
                ItemOLP.EDIT,
                "Can edit this item",
            ),
            (
                ItemOLP.DELETE,
                "Can delete this item",
            ),
            (
                "borrow_this_item",
                "Can borrow this item",
            ),
        ]


class ItemPhoto(Model):
    # Not including owner as permissions/ownership should be inherited from Item
    # Alt text could be a good additional field to support via user input
    # Height/Width might also need to be stored by parsing image metadata on save
    item = ForeignKey(Item, on_delete=CASCADE, related_name="photos")
    item_id: int  # hint for mypy
    image = ProcessedImageField(
        upload_to="items/",
        processors=[AutoOrientProcessor(), ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
    )
    thumbnail = ImageSpecField(
        source="image",
        processors=[ResizeToFill(200, 200)],
        format="JPEG",
        options={"quality": 75},
    )
    created_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the item photo.",
        on_delete=DO_NOTHING,
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the item photo was created.",
    )
    updated_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the item photo.",
        on_delete=DO_NOTHING,
    )
    updated_at = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the item photo was last updated.",
    )
    deleted_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )

    class Meta:
        ordering = ["pk"]

    def __str__(self) -> str:
        # error: "_ST" has no attribute "name"  [attr-defined]
        return f"Photo of {self.item.name}"


class Transaction(Model):
    item = ForeignKey(
        to="Item",
        on_delete=PROTECT,
        related_name="transactions",
        help_text="The Item which is the subject of the Transaction.",
    )
    party1 = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The first party in the Transaction: 'lender', 'giver', 'owner', etc.",
    )
    party2 = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The second party in the Transaction: 'borrower', 'receiver', etc.",
    )
    status = IntegerField(
        choices=TransactionStatus.choices,
        default=TransactionStatus.REQUESTED,
        help_text="The current status of the Transaction.",
    )
    _previous_status: int | None = None
    resolution_reason = CharField(
        max_length=32,
        choices=ResolutionReason.choices,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Why the Transaction was force-resolved outside the normal "
            "dual-confirmation flow. NULL for normally-completed Transactions."
        ),
    )
    return_requested_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "When the lender requested the return of the item. Wait window "
            "starts from this time. NULL means no return request was made."
        ),
    )
    disputed_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text=("When the Transaction entered DISPUTED. NULL means never disputed."),
    )
    dispute_raised_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who raised the dispute. NULL means never disputed.",
    )
    created_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The user who created the transaction.",
        on_delete=DO_NOTHING,
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="The date and time at which the transaction was created.",
    )
    updated_by = ForeignKey(
        BorrowdUser,
        related_name="+",  # No reverse relation needed
        null=False,
        blank=False,
        help_text="The last user who updated the transaction.",
        on_delete=PROTECT,
    )
    updated_at = DateTimeField(
        auto_now=True,
        help_text="The date and time at which the transaction was last updated.",
    )
    deleted_at = DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text="Set when the record is soft-deleted. NULL means active.",
    )
    deleted_by = ForeignKey(
        BorrowdUser,
        null=True,
        blank=True,
        default=None,
        on_delete=SET_NULL,
        related_name="+",
        help_text="Who performed the soft-delete. NULL means active or unknown.",
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)
        # A transaction is part of its item's state, as far as clients can tell.
        Item.all_objects.filter(pk=self.item_id).update(revision=F("revision") + 1)

    def counter_party(self, user: BorrowdUser) -> BorrowdUser:
        if user == self.party1:
            return self.party2

        if user == self.party2:
            return self.party1

        raise ValueError("User is not a party to this transaction.")

    def dispute_wait_has_elapsed(self, now: datetime | None = None) -> bool:
        """
        Whether the lender has waited long enough since requesting a return
        to be allowed to raise a dispute. Wait time is (RETURN_DISPUTE_WAIT_DAYS)

        Pass `now` to decide against a time captured by the caller.
        """

        if self.return_requested_at is None:
            return False
        wait = timedelta(days=settings.RETURN_DISPUTE_WAIT_DAYS)
        return (now or timezone.now()) - self.return_requested_at >= wait

    def force_resolve(
        self, *, resolved_by: BorrowdUser, reason: ResolutionReason
    ) -> None:
        """
        Close this Transaction forcibly.

        For cases the standard flow can't finish: a party closed their account,
        a moderator stepped in, the counterparty went unresponsive, etc. The
        transaction is always set to RESOLVED with the given reason. The item is
        freed back to AVAILABLE if it's still active; a soft-deleted item (e.g. a
        departed owner's) is left as-is.

        Raises InvalidItemAction if the transaction is already closed, rather
        than writing a new outcome over the one it has.
        """

        with transaction.atomic():
            item = Item.lock_for_update(self.item_id)
            # Decide on the row as it is under the lock, not the caller's copy.
            self.refresh_from_db()
            if self.status in TERMINAL_TRANSACTION_STATUSES:
                raise InvalidItemAction(f"Transaction {self.pk} is already closed.")
            source = TransactionStatus(self.status)
            self.status = TransactionStatus.RESOLVED
            self.resolution_reason = reason
            self.updated_by = resolved_by
            sync_item_status(item, self)
            self.save()
            LifecycleEvent.record(
                self,
                source=source,
                target=TransactionStatus.RESOLVED,
                actor=resolved_by,
            )

    @staticmethod
    def get_requested_status_transactions_for_user(
        user: BorrowdUser,
    ) -> QuerySet["Transaction"]:
        """
        Returns Transactions awaiting the owner's decision involving the given
        User: borrow requests (REQUESTED) and giveaway requests (GIVEAWAY_REQUESTED).
        I.E., the borrower has asked, but the lender hasn't accepted or rejected yet.

        See get_active_borrows_for_user and get_active_lends_for_user for
        other transaction states that require user confirmation (pick ups/returns).
        """

        return Transaction.objects.filter(
            Q(party1=user) | Q(party2=user),
            status__in=REQUEST_TRANSACTION_STATUSES,
        )

    @staticmethod
    def get_active_borrows_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """Return the user's open borrows past the request stage, including ACCEPTED."""
        return Transaction.objects.filter(
            party2=user,
            status__in=BORROWER_TRANSACTION_STATUSES,
        )

    @staticmethod
    def get_active_lends_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """Return the user's open lends past the request stage, including ACCEPTED."""
        return Transaction.objects.filter(
            party1=user,
            status__in=BORROWER_TRANSACTION_STATUSES,
        )

    @staticmethod
    def get_successful_borrows(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Return the transactions in witch the user was a borrowers
        and the item was successfuly RETURNED.
        """

        return Transaction.objects.filter(
            Q(party2=user) & Q(status=TransactionStatus.RETURNED)
        )

    @staticmethod
    def get_successful_lends(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Return the transactions in witch the user was a lender
        and the item was successfuly RETURNED or has been Given away.
        """

        return Transaction.objects.filter(
            Q(party1=user)
            & Q(
                status__in=[
                    TransactionStatus.RETURNED,
                ]
            )
        )

    @staticmethod
    def get_items_given_away(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Return the transactions in witch the user was a lender
        and the item was Given away.
        """

        return Transaction.objects.filter(
            Q(party1=user)
            & Q(
                status__in=[
                    TransactionStatus.OWNERSHIP_TRANSFERRED,
                ]
            )
        )

    @staticmethod
    def get_pending_return_requests(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns the transactions where the user is a borrower and the return has been requested.
        We also include transactions where the Return is asserted but not yet confirmed.
        """

        return Transaction.objects.filter(
            Q(party2=user)
            & Q(
                status__in=[
                    TransactionStatus.RETURN_REQUESTED,
                    TransactionStatus.RETURN_ASSERTED,
                ]
            )
        )

    @staticmethod
    def get_past_disputes(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns the disputes involving the {user}, we filter on disputed_at instead if status
        To track also disputes that will eventualy become resolved.
        """

        return Transaction.objects.filter(
            Q(disputed_at__isnull=False) & (Q(party1=user) | Q(party2=user))
        )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["item"],
                condition=Q(status__in=OPEN_TRANSACTION_STATUSES),
                name="unique_open_transaction_per_item",
            )
        ]


class AvailabilitySubscriptionStatus(IntegerChoices):
    """
    Represents the status of an Availability Subscription.
    This is used to track the current state of an Availability Subscription,
    and to determine which actions are available to the user.
    """

    ACTIVE = 10, "Active"
    NOTIFIED = 20, "Notified"
    CANCELLED = 30, "Cancelled"
    EXPIRED = 40, "Expired"


class AvailabilitySubscription(Model):
    item = ForeignKey(
        to="Item",
        on_delete=PROTECT,
        related_name="subscriptions",
        help_text="The Item which is the subject of the Subscription.",
    )
    user = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The User who is subscribed to the Item.",
    )
    status = IntegerField(
        choices=AvailabilitySubscriptionStatus.choices,
        default=AvailabilitySubscriptionStatus.ACTIVE,
        help_text="The current status of the Subscription.",
    )
    created_at = DateTimeField(
        auto_now_add=True,
        help_text="When this Subscription was created.",
    )
    notified_at = DateTimeField(
        null=True,
        blank=True,
        help_text="When the user was notified that the item became available.",
    )
    language = CharField(
        max_length=10,
        null=False,
        blank=False,
        default="en",
        help_text="The user's preferred language for notifications (e.g. 'en', 'fr', etc.)",
    )

    @staticmethod
    def get_active_subscriptions_for_user(
        user: BorrowdUser,
    ) -> QuerySet["AvailabilitySubscription"]:
        """
        Returns all active Availability Subscriptions for the given User.
        """
        return AvailabilitySubscription.objects.filter(
            user=user,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )

    @staticmethod
    def get_active_subscriptions_for_item(
        item: Item,
    ) -> QuerySet["AvailabilitySubscription"]:
        """
        Returns all active Availability Subscriptions for the given Item.
        """
        return AvailabilitySubscription.objects.filter(
            item=item,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )

    @staticmethod
    def get_active_subscription_for_user_and_item(
        user: BorrowdUser, item: Item
    ) -> Optional["AvailabilitySubscription"]:
        """
        Returns the active Availability Subscription for the given User and Item, if any.
        """
        try:
            return AvailabilitySubscription.objects.get(
                item=item,
                user=user,
                status=AvailabilitySubscriptionStatus.ACTIVE,
            )
        except AvailabilitySubscription.DoesNotExist:
            return None
        except AvailabilitySubscription.MultipleObjectsReturned:
            # This shouldn't happen with proper business logic, but just in case
            return AvailabilitySubscription.objects.filter(
                item=item,
                user=user,
                status=AvailabilitySubscriptionStatus.ACTIVE,
            ).first()

    def cancel_subscription(self) -> None:
        """
        Cancel the given subscription, e.g. if the user manually cancels it or if they request to be notified again.
        """
        self.status = AvailabilitySubscriptionStatus.CANCELLED
        self.save()

    def expire_subscription(self) -> None:
        """
        Expire the given subscription, e.g. if a certain amount of time has passed since the user was notified without them taking action.
        """
        self.status = AvailabilitySubscriptionStatus.EXPIRED
        self.save()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["item", "user"],
                condition=Q(status=AvailabilitySubscriptionStatus.ACTIVE),
                name="unique_active_subscription_per_user_and_item",
            )
        ]


class ItemCommandRecord(Model):
    """
    A lifecycle command that succeeded, kept so that a retry of it gets the
    same answer instead of running again. `prune_item_command_records` drops
    them after 30 days; a retry older than that is caught by the revision.
    """

    actor = ForeignKey(BorrowdUser, on_delete=CASCADE, related_name="+")
    key = UUIDField(
        help_text="Picked by the client, once per command it means to send."
    )
    fingerprint = CharField(
        max_length=64,
        help_text="What the command asked for, so a key sent with another one is caught.",
    )
    action = CharField(max_length=50, choices=ItemAction.choices)
    item = ForeignKey(Item, on_delete=CASCADE, related_name="+")
    transaction = ForeignKey(
        Transaction, null=True, blank=True, on_delete=CASCADE, related_name="+"
    )
    transaction_status = IntegerField(
        null=True, blank=True, choices=TransactionStatus.choices
    )
    revision = PositiveBigIntegerField(
        help_text="The item's revision once the command was done."
    )
    created_at = DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["actor", "key"], name="unique_item_command_key_per_actor"
            )
        ]


# Sent when a LifecycleEvent row is written; borrowd_items.events delivers it
# once the database transaction commits.
transition_recorded = Signal()


class LifecycleEvent(Model):
    """
    One change to a transaction's status, written in the same database
    transaction as the change. Consumers (borrowd_items.events) run after
    commit, and `deliver_lifecycle_events` retries whatever a crash or an
    error left behind.
    """

    id = UUIDField(primary_key=True, default=uuid4, editable=False)
    schema_version = PositiveSmallIntegerField(default=2)
    item = ForeignKey(Item, on_delete=CASCADE, related_name="+")
    transaction = ForeignKey(Transaction, on_delete=CASCADE, related_name="+")
    revision = PositiveBigIntegerField(
        help_text="The item's revision once the change was made. Orders a transaction's events."
    )
    action = CharField(
        max_length=50,
        blank=True,
        choices=ItemAction.choices,
        help_text="The action behind the change. Blank for account closure or a forced resolution.",
    )
    source_status = IntegerField(
        null=True,
        blank=True,
        choices=TransactionStatus.choices,
        help_text="NULL when the change opened the transaction.",
    )
    target_status = IntegerField(choices=TransactionStatus.choices)
    actor = ForeignKey(BorrowdUser, on_delete=CASCADE, related_name="+")
    command_key = UUIDField(
        null=True, blank=True, help_text="The client's command key, if it sent one."
    )
    occurred_at = DateTimeField(default=timezone.now)

    processed_at = DateTimeField(null=True, blank=True)
    attempts = PositiveSmallIntegerField(default=0)
    next_attempt_at = DateTimeField(default=timezone.now)
    failed_at = DateTimeField(
        null=True,
        blank=True,
        help_text="Set once retries ran out. Holds back the transaction's later events until replayed or skipped.",
    )
    last_error = TextField(blank=True)
    skipped_by = ForeignKey(
        BorrowdUser, null=True, blank=True, on_delete=SET_NULL, related_name="+"
    )
    skip_reason = TextField(blank=True)

    class Meta:
        indexes = [
            Index(fields=["transaction", "revision"], name="lifecycle_event_order"),
            Index(
                fields=["next_attempt_at"],
                condition=Q(processed_at__isnull=True),
                name="lifecycle_event_pending",
            ),
        ]

    def __str__(self) -> str:
        source = (
            TransactionStatus(self.source_status).name
            if self.source_status is not None
            else "new"
        )
        target = TransactionStatus(self.target_status).name
        return f"Transaction {self.transaction_id}: {source} -> {target}"

    @classmethod
    def record(
        cls,
        tx: Transaction,
        *,
        source: TransactionStatus | None,
        target: TransactionStatus,
        actor: BorrowdUser,
        action: ItemAction | None = None,
        command_key: UUID | None = None,
    ) -> "LifecycleEvent":
        """Write the event for a change the caller just saved, under its locks."""
        event = cls.objects.create(
            item_id=tx.item_id,
            transaction=tx,
            revision=Item.all_objects.values_list("revision", flat=True).get(
                pk=tx.item_id
            ),
            action=action or "",
            source_status=source,
            target_status=target,
            actor=actor,
            command_key=command_key,
        )
        transition_recorded.send(sender=cls, event=event)
        return event


class LifecycleEventConsumption(Model):
    """A consumer's note that it handled an event, written with its effects."""

    consumer = CharField(max_length=50)
    event = ForeignKey(LifecycleEvent, on_delete=CASCADE, related_name="consumptions")
    consumed_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["consumer", "event"], name="unique_event_per_consumer"
            )
        ]
