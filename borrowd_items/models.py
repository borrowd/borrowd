from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    SET_NULL,
    CharField,
    DateTimeField,
    ForeignKey,
    IntegerChoices,
    IntegerField,
    ManyToManyField,
    Model,
    Q,
    QuerySet,
    TextChoices,
    UniqueConstraint,
)
from django.urls import reverse
from django.utils import timezone
from imagekit.models import ImageSpecField, ProcessedImageField
from imagekit.processors import ResizeToFill, ResizeToFit

from borrowd.models import TrustLevel
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .exceptions import InvalidItemAction, ItemAlreadyRequested
from .processors import AutoOrientProcessor


class ActiveItemQuerySet(QuerySet["Item"]):
    def active(self) -> "ActiveItemQuerySet":
        return self.filter(deleted_at__isnull=True)

    def deleted(self) -> "ActiveItemQuerySet":
        return self.filter(deleted_at__isnull=False)


class ActiveItemManager(models.Manager["Item"]):
    def get_queryset(self) -> ActiveItemQuerySet:
        return ActiveItemQuerySet(self.model, using=self._db).active()


class ItemAction(TextChoices):
    """
    Represents the actions that can be performed on an Item.
    This is used to determine which actions are available to the
    user when viewing an Item.
    """

    REQUEST_ITEM = "REQUEST_ITEM", "Request Item"
    ACCEPT_REQUEST = "ACCEPT_REQUEST", "Accept Request"
    REJECT_REQUEST = "REJECT_REQUEST", "Reject Request"
    MARK_COLLECTED = "MARK_COLLECTED", "Mark Collected"
    CONFIRM_COLLECTED = "CONFIRM_COLLECTED", "Confirm Collected"
    NOTIFY_WHEN_AVAILABLE = "NOTIFY_WHEN_AVAILABLE", "Notify when available"
    CANCEL_NOTIFICATION_REQUEST = (
        "CANCEL_NOTIFICATION_REQUEST",
        "Cancel notification request",
    )
    MARK_RETURNED = "MARK_RETURNED", "Mark Returned"
    CONFIRM_RETURNED = "CONFIRM_RETURNED", "Confirm Returned"
    CANCEL_REQUEST = "CANCEL_REQUEST", "Cancel Request"
    RESOLVE_TRANSACTION = "RESOLVE_TRANSACTION", "Close Out Transaction"
    REQUEST_RETURN = "REQUEST_RETURN", "Request Return"
    FLAG_CANNOT_RETURN = "FLAG_CANNOT_RETURN", "Cannot Return Item"
    RAISE_DISPUTE = "RAISE_DISPUTE", "Raise Dispute"
    RESOLVE_DISPUTE_RETURNED = (
        "RESOLVE_DISPUTE_RETURNED",
        "Resolve Dispute: Item Returned",
    )
    RESOLVE_DISPUTE_NOT_RETURNED = (
        "RESOLVE_DISPUTE_NOT_RETURNED",
        "Resolve Dispute: Item Not Returned",
    )
    OFFER_GIVEAWAY = "OFFER_GIVEAWAY", "Give Away"
    ACCEPT_GIVEAWAY = "ACCEPT_GIVEAWAY", "Accept Gift"
    DECLINE_GIVEAWAY = "DECLINE_GIVEAWAY", "Decline Gift"


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
    waiting_text: Optional[str] = None


class ItemCategory(Model):
    name = CharField(max_length=50, null=False, blank=False)
    description = CharField(max_length=100, null=True, blank=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Item Category"
        verbose_name_plural = "Item Categories"


class ItemStatus(IntegerChoices):
    """
    Represents the status of an Item. This is used to track the
    current state of an Item, and to determine which actions are
    available to the user.
    """

    # Paranoia forcing to me to use value increments of at least 10,
    # for when we later realize we need to add more in between...
    AVAILABLE = 10, "Available"
    REQUESTED = 15, "Requested"
    RESERVED = 20, "Reserved"
    BORROWED = 30, "Borrowed"


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
    trust_level_required = IntegerField(
        choices=TrustLevel,
        default=TrustLevel.STANDARD,
        help_text=(
            "The minimum required Group trust level required for"
            " this Item to be visible to and borrowable by members"
            " of that Group."
        ),
    )
    status = IntegerField(
        choices=ItemStatus.choices,
        default=ItemStatus.AVAILABLE,
        help_text="The current status of the Item.",
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
    objects = ActiveItemManager()
    all_objects = models.Manager()

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("item-detail", args=[self.pk])

    def clean(self) -> None:
        """Validate that Item has at least one category assigned."""
        super().clean()
        # M2M validation only works for saved instances
        if self.pk and not self.categories.exists():
            raise ValidationError({"categories": "At least one category is required."})

    def soft_delete(self, deleted_by: BorrowdUser) -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save()

    def get_action_context_for(self, user: BorrowdUser) -> ItemActionContext:
        """
        Returns ItemActionContext containing ItemActions [e.g. REQUEST_ITEM, ACCEPT_REQUEST]
        and status information [e.g. "You are currently borrowing this item."] for the given user.
        """

        current_borrower = self.get_current_borrower()
        requesting_user = self.get_requesting_user()
        current_tx = self.get_current_transaction_for_user(user)
        actions = self.get_actions_for(user)

        # Generate status text based on user role and current actions/status
        status_text = self._get_status_text_for_user(
            user=user,
            actions=actions,
            current_borrower=current_borrower,
            requesting_user=requesting_user,
            current_tx=current_tx,
        )

        # The borrower who asserted return of a requested item must wait for
        # the lender to confirm the item has been returned.
        waiting_text = None
        if (
            current_tx is not None
            and current_tx.status == TransactionStatus.RETURN_ASSERTED
            and current_tx.return_requested_at is not None
            and current_tx.updated_by == user
        ):
            waiting_text = "Waiting on confirmation from lender..."

        return ItemActionContext(
            actions=actions, status_text=status_text, waiting_text=waiting_text
        )

    def _get_status_text_for_user(
        self,
        user: BorrowdUser,
        actions: tuple[ItemAction, ...],
        current_borrower: Optional[BorrowdUser],
        requesting_user: Optional[BorrowdUser],
        current_tx: Optional["Transaction"] = None,
    ) -> str:
        """Generate context-appropriate status text for the user."""
        # Determine user role
        is_owner = self.owner == user
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
            return self._get_other_user_status_text(actions, user)

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
        self, actions: tuple[ItemAction, ...], user: BorrowdUser
    ) -> str:
        """Generate status text for users who are neither owner nor borrower."""
        if len(actions) == 1 and ItemAction.CANCEL_REQUEST in actions:
            # Intentionally obscuring owner name here for privacy to reject
            return "Requested to borrow, waiting on owner response..."
        elif ItemAction.REQUEST_ITEM in actions:
            return "Available to request!"
        elif (
            AvailabilitySubscription.get_active_subscription_for_user_and_item(
                user=user, item=self
            )
            is not None
        ):
            return "You've requested to be notified when this item is available again."
        elif self.get_requesting_user() is not None:
            # There's a pending request from another user
            return "Item is reserved"
        else:
            return "Not available for borrowing"

    def get_actions_for(self, user: BorrowdUser) -> tuple[ItemAction, ...]:
        """
        Returns a tuple of ItemAction objects representing the
        current valid actions that the given User may perform on this
        Item.

        The actions are determined by:
        - The status of the Item itself
        - The status of the current open Transaction involving this
          Item and the given User, if any.
        """
        # This may raise Transaction.MultipleObjectsReturned.
        # Let it propagate.
        current_tx = self.get_current_transaction_for_user(user)

        # IF there are no current Txns involving this user...
        if current_tx is None:
            #   AND the item status Available,
            #   AND the user is not the owner,
            #   AND there's no pending request from another user
            if (
                self.status == ItemStatus.AVAILABLE
                and self.owner != user
                and self.get_requesting_user() is None
            ):
                # THEN
                #   the User can Request the Item.
                return (ItemAction.REQUEST_ITEM,)
            elif (
                not self.is_borrowable(user=user)
                and AvailabilitySubscription.get_active_subscription_for_user_and_item(
                    user=user, item=self
                )
                is None
            ) and self.owner != user:
                # If the item is currently BORROWED or RESERVED by another user,
                # allow requesting notification for when it becomes available again
                return (ItemAction.NOTIFY_WHEN_AVAILABLE,)
            elif (
                not self.is_borrowable(user=user)
                and AvailabilitySubscription.get_active_subscription_for_user_and_item(
                    user=user, item=self
                )
                is not None
            ) and self.owner != user:
                # If the item is currently BORROWED or RESERVED by another user,
                # but the current user has an active subscription, allow cancelling the subscription
                return (ItemAction.CANCEL_NOTIFICATION_REQUEST,)
            else:
                # At this point, either:
                # - the user is the owner of the item (and thus can't request to borrow their
                # no Request can be initiated.

                # NOTE Later we may want to allow new Requests on Items
                # even when they're currently Borrowed; that will
                # imply date-based borrowing bookings, which we're
                # not tackling yet.
                return tuple()

        # If we get here, we have exactly one Transaction involving
        # this Item and this User. Let's figure out what are the
        # valid next ItemActions...
        # TODO. This is a bit hairy. Upgrade to state machine?

        # If the other party's account is inactive (they closed it), the
        # dual-confirmation handshake can never complete.
        # therefore, let the remaining party close the loan out single-handed.
        if current_tx.status in (
            TransactionStatus.COLLECTION_ASSERTED,
            TransactionStatus.COLLECTED,
            TransactionStatus.GIVEAWAY_OFFERED,
            TransactionStatus.RETURN_REQUESTED,
            TransactionStatus.RETURN_ASSERTED,
            TransactionStatus.DISPUTED,
        ):
            counterparty = (
                current_tx.party1 if current_tx.party2 == user else current_tx.party2
            )
            if not counterparty.is_active:
                return (ItemAction.RESOLVE_TRANSACTION,)

        if current_tx.status == TransactionStatus.REQUESTED:
            if self.owner == user:
                # The User is the owner of the Item, and the current
                # Transaction is a Request from another User.
                # The owner can either Accept or Reject the Request.
                return (
                    ItemAction.REJECT_REQUEST,
                    ItemAction.ACCEPT_REQUEST,
                )
            else:
                # The User is the requestor and the current
                # Transaction is a Request from them.
                # No next steps until owner confirms,
                # but may cancel.
                return (ItemAction.CANCEL_REQUEST,)
        elif current_tx.status == TransactionStatus.ACCEPTED:
            # Either borrower or lender can assert collection.
            return (
                ItemAction.CANCEL_REQUEST,
                ItemAction.MARK_COLLECTED,
            )
        elif current_tx.status == TransactionStatus.COLLECTION_ASSERTED:
            # Make sure the same person doesn't confirm the assertion
            if current_tx.updated_by != user:
                # TODO: What's the escape hatch if a dispute arises?
                return (ItemAction.CONFIRM_COLLECTED,)
            else:
                # Otherwise, nothing to do but wait...
                return tuple()
        elif current_tx.status == TransactionStatus.COLLECTED:
            # Either borrower or lender can assert return.
            # The lender can also request the item back, or give it away.
            if self.owner == user:
                return (
                    ItemAction.MARK_RETURNED,
                    ItemAction.REQUEST_RETURN,
                    ItemAction.OFFER_GIVEAWAY,
                )
            return (ItemAction.MARK_RETURNED,)
        elif current_tx.status == TransactionStatus.GIVEAWAY_OFFERED:
            # The borrower decides whether to accept the gift.
            # The lender waits on that decision.
            if self.owner == user:
                return tuple()
            return (ItemAction.ACCEPT_GIVEAWAY, ItemAction.DECLINE_GIVEAWAY)
        elif current_tx.status == TransactionStatus.RETURN_REQUESTED:
            if self.owner == user:
                # The lender can escalate to a dispute only if the wait window has passed
                if current_tx.dispute_wait_has_elapsed():
                    return (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED)
                return (ItemAction.CONFIRM_RETURNED,)
            # The borrower confirms the return or flags that they can't return the item.
            return (ItemAction.MARK_RETURNED, ItemAction.FLAG_CANNOT_RETURN)
        elif current_tx.status == TransactionStatus.RETURN_ASSERTED:
            # Make sure the same person doesn't confirm the assertion
            if current_tx.updated_by != user:
                if self.owner == user:
                    # The lender can deny the borrower's return claim.
                    return (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED)
                return (ItemAction.CONFIRM_RETURNED,)
            else:
                # Otherwise, nothing to do but wait...
                return tuple()
        elif current_tx.status == TransactionStatus.DISPUTED:
            if self.owner == user:
                # The lender settles the dispute one way or the other.
                return (
                    ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
                    ItemAction.RESOLVE_DISPUTE_RETURNED,
                )
            # The borrower waits on the lender. (no options for borrower)
            return tuple()
        else:
            # We shouldn't get here...
            raise ValueError(
                f"Unexpected Transaction status '{current_tx.status}' for Item '{self}' and User '{user}'"
            )

    def get_requesting_user(self) -> Optional[BorrowdUser]:
        """
        Returns the User who has requested to borrow this Item, if any.
        This is specifically for items in REQUESTED status.
        """
        try:
            transaction = Transaction.objects.get(
                Q(item=self) & Q(status=TransactionStatus.REQUESTED)
            )
            # party2 is the requestor
            return transaction.party2
        except Transaction.DoesNotExist:
            return None
        except Transaction.MultipleObjectsReturned:
            # Return the most recent request (for now)
            txn: Optional["Transaction"] = (
                Transaction.objects.filter(
                    Q(item=self) & Q(status=TransactionStatus.REQUESTED)
                )
                .order_by("-created_at")
                .first()
            )
            return txn.party2 if txn else None

    def get_current_borrower(self) -> Optional[BorrowdUser]:
        """
        Returns the User who is currently borrowing this Item, if any.
        """
        # Look for an active transaction where the item is borrowed or reserved
        try:
            transaction = Transaction.objects.get(
                Q(item=self)
                & Q(
                    status__in=[
                        TransactionStatus.ACCEPTED,
                        TransactionStatus.COLLECTION_ASSERTED,
                        TransactionStatus.COLLECTED,
                        TransactionStatus.GIVEAWAY_OFFERED,
                        TransactionStatus.RETURN_REQUESTED,
                        TransactionStatus.RETURN_ASSERTED,
                        TransactionStatus.DISPUTED,
                    ]
                )
            )
            # party2 is the borrower
            return transaction.party2
        except Transaction.DoesNotExist:
            return None
        except Transaction.MultipleObjectsReturned:
            # This shouldn't happen with proper business logic, but just in case
            # return the most recent one
            txn: Optional["Transaction"] = (
                Transaction.objects.filter(
                    Q(item=self)
                    & Q(
                        status__in=[
                            TransactionStatus.ACCEPTED,
                            TransactionStatus.COLLECTION_ASSERTED,
                            TransactionStatus.COLLECTED,
                            TransactionStatus.GIVEAWAY_OFFERED,
                            TransactionStatus.RETURN_REQUESTED,
                            TransactionStatus.RETURN_ASSERTED,
                            TransactionStatus.DISPUTED,
                        ]
                    )
                )
                .order_by("-updated_at")
                .first()
            )
            return txn.party2 if txn else None

    def get_current_transaction_for_user(
        self, user: BorrowdUser
    ) -> Optional["Transaction"]:
        """
        Returns the current Transaction involving this Item and the
        given User, if any.
        """
        try:
            # Using `get()` here because if there *is* a current
            # Transaction involving this Item and this User, there
            # should only be one.
            return Transaction.objects.get(
                Q(item=self)
                & (Q(party1=user) | Q(party2=user))
                & ~Q(
                    status__in=[
                        TransactionStatus.RETURNED,
                        TransactionStatus.REJECTED,
                        TransactionStatus.CANCELLED,
                        TransactionStatus.RESOLVED,
                        TransactionStatus.OWNERSHIP_TRANSFERRED,
                    ]
                )
            )
        except Transaction.DoesNotExist:
            return None

    def is_borrowable(self, user: Optional[BorrowdUser] = None) -> bool:
        if self.status != ItemStatus.AVAILABLE:
            return False

        active_borrow = self.get_current_borrower()
        if active_borrow:
            return False

        active_request = self.get_requesting_user()

        if active_request and active_request != user:
            return False

        return True

    def process_action(self, user: BorrowdUser, action: ItemAction) -> None:
        """
        Process the given action for this Item and User.
        """
        # Check for specific case: trying to request an item that already has a pending request
        if action == ItemAction.REQUEST_ITEM and self.get_requesting_user() is not None:
            raise ItemAlreadyRequested(
                f"Item '{self}' already has a pending request from another user."
            )

        valid_actions = self.get_actions_for(user=user)
        if action not in valid_actions:
            raise InvalidItemAction(
                (
                    f"User '{user}' cannot perform action '{action}' on"
                    f"Item '{self}' at this time."
                )
            )

        if action == ItemAction.REQUEST_ITEM:
            Transaction.objects.create(
                item=self,
                # By convention "party1" is the owner/lender/giver.
                party1=self.owner,
                party2=user,
                created_by=user,
                updated_by=user,
                # This is default; just being explicit
                status=TransactionStatus.REQUESTED,
            )
            self.status = ItemStatus.REQUESTED
            self.save()
            return

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
            return

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
            return

        current_tx = self.get_current_transaction_for_user(user=user)
        if current_tx is None:
            # This should have been caught earlier, but check again
            # partly to keep mypy happy.
            raise ValueError("No existing Transaction")

        with transaction.atomic():
            match action:
                case ItemAction.REJECT_REQUEST:
                    # The owner/lender/giver rejects the Request.
                    current_tx.status = TransactionStatus.REJECTED
                    current_tx.updated_by = user
                    current_tx.save()
                    self.status = ItemStatus.AVAILABLE
                    self.save()
                case ItemAction.ACCEPT_REQUEST:
                    # The owner/lender/giver accepts the Request.
                    current_tx.status = TransactionStatus.ACCEPTED
                    current_tx.updated_by = user
                    current_tx.save()
                    self.status = ItemStatus.RESERVED
                    self.save()
                case ItemAction.MARK_COLLECTED:
                    # Either party can assert collection.
                    current_tx.status = TransactionStatus.COLLECTION_ASSERTED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.CONFIRM_COLLECTED:
                    # The other party confirms collection.
                    current_tx.status = TransactionStatus.COLLECTED
                    current_tx.updated_by = user
                    current_tx.save()
                    self.status = ItemStatus.BORROWED
                    self.save()
                case ItemAction.MARK_RETURNED:
                    # Either party can assert return.
                    current_tx.status = TransactionStatus.RETURN_ASSERTED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.CONFIRM_RETURNED | ItemAction.RESOLVE_DISPUTE_RETURNED:
                    # The other party confirms return or lender resolved dispute happily
                    self.status = ItemStatus.AVAILABLE
                    self.save()
                    current_tx.status = TransactionStatus.RETURNED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.REQUEST_RETURN:
                    # The lender asks for the item back from the borrower
                    current_tx.status = TransactionStatus.RETURN_REQUESTED
                    current_tx.return_requested_at = timezone.now()
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.FLAG_CANNOT_RETURN | ItemAction.RAISE_DISPUTE:
                    # Either side escalates to a dispute
                    current_tx.status = TransactionStatus.DISPUTED
                    current_tx.disputed_at = timezone.now()
                    current_tx.dispute_raised_by = user
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.RESOLVE_DISPUTE_NOT_RETURNED:
                    # Item is gone for good
                    # soft-delete it and close out the transaction.
                    self.soft_delete(deleted_by=user)
                    current_tx.force_resolve(
                        resolved_by=user,
                        reason=ResolutionReason.DISPUTE_ITEM_NOT_RETURNED,
                    )
                case ItemAction.OFFER_GIVEAWAY:
                    # The lender offers to give the item to the borrower for keeps.
                    # Item stays BORROWED until the borrower accepts.
                    current_tx.status = TransactionStatus.GIVEAWAY_OFFERED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.DECLINE_GIVEAWAY:
                    # The borrower turns down the gift; the loan continues.
                    current_tx.status = TransactionStatus.COLLECTED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.ACCEPT_GIVEAWAY:
                    # The borrower accepts; ownership transfers for good.
                    current_tx.status = TransactionStatus.OWNERSHIP_TRANSFERRED
                    current_tx.updated_by = user
                    current_tx.save()
                    self._transfer_ownership(new_owner=user, by=user)
                case ItemAction.CANCEL_REQUEST:
                    # The requestor cancels the Request.
                    self.status = ItemStatus.AVAILABLE
                    self.save()
                    current_tx.status = TransactionStatus.CANCELLED
                    current_tx.updated_by = user
                    current_tx.save()
                case ItemAction.RESOLVE_TRANSACTION:
                    # Counterparty's account is gone, so the normal confirm step
                    # can't happen; close the loan out single-handed.
                    counterparty = (
                        current_tx.party1
                        if current_tx.party2 == user
                        else current_tx.party2
                    )
                    owner_deleted = (
                        counterparty == current_tx.party1
                        and counterparty.deleted_at is not None
                    )
                    reason = (
                        ResolutionReason.OWNER_ACCOUNT_DELETED
                        if owner_deleted
                        else ResolutionReason.COUNTERPARTY_UNRESPONSIVE
                    )
                    current_tx.force_resolve(resolved_by=user, reason=reason)
                case _:
                    # We shouldn't get here...
                    raise ValueError(
                        f"Unexpected action '{action}' for Item '{self}' and User '{user}'"
                    )

    def _transfer_ownership(self, new_owner: BorrowdUser, by: BorrowdUser) -> None:
        """
        Permanently hand this Item to new_owner.

        Reassigns ownership in place: the same Item record (and its photos,
        description, categories) shows up in the new owner's inventory and
        leaves the old owner's.
        """
        from django.contrib.auth.models import Group
        from guardian.shortcuts import assign_perm, remove_perm

        from borrowd_groups.models import MembershipStatus

        old_owner = self.owner

        # Drop the old owner's group-based visibility before reassigning.
        # The post_save signal only recomputes group perms for the new owner,
        # so it would otherwise leave the old owner's groups able to
        # see an item they no longer should be able to.
        old_owner_group_ids = (
            old_owner.borrowd_groups.filter(
                membership__user=old_owner,
                membership__status=MembershipStatus.ACTIVE,
            )
            .exclude(perms_group=None)
            .values_list("perms_group", flat=True)
        )
        for group in Group.objects.filter(pk__in=old_owner_group_ids):
            remove_perm(ItemOLP.VIEW, group, self)

        # Reassign and save. The save fires `assign_item_permissions`
        # See signals.py
        self.owner = new_owner
        self.status = ItemStatus.AVAILABLE
        self.updated_by = by
        self.save()

        # `assign_item_permissions` grants personal perms only on create
        # so we have to hand pervious owner's perms to new owner explicitly.
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

    def __str__(self) -> str:
        # error: "_ST" has no attribute "name"  [attr-defined]
        return f"Photo of {self.item.name}"


class TransactionStatus(IntegerChoices):
    """
    Represents the status of a Transaction. This is used to track
    the current state of a Transaction, and to determine which
    actions are available to the user.
    """

    # Paranoia forcing to me to use value increments of at least 10,
    # for when we later realize we need to add more in between...
    REQUESTED = 10, "Requested"
    REJECTED = 20, "Rejected"
    ACCEPTED = 30, "Accepted"
    COLLECTION_ASSERTED = 40, "Collection Asserted"
    COLLECTED = 50, "Collected"
    GIVEAWAY_OFFERED = 52, "Giveaway Offered"
    RETURN_REQUESTED = 55, "Return Requested"
    RETURN_ASSERTED = 60, "Return Asserted"
    DISPUTED = 65, "Disputed"
    RETURNED = 70, "Returned"
    CANCELLED = 80, "Cancelled"
    RESOLVED = 90, "Resolved"  # any force-resolved transaction, regardless of reason
    OWNERSHIP_TRANSFERRED = 95, "Ownership Transferred"


class ResolutionReason(TextChoices):
    """
    Why a Transaction was force-resolved instead of completing the normal flow.
    Set alongside TransactionStatus.RESOLVED.
    """

    OWNER_ACCOUNT_DELETED = ("owner_account_deleted", "Owner closed their account")
    MODERATOR_OVERRIDE = ("moderator_override", "Resolved by a moderator")
    COUNTERPARTY_UNRESPONSIVE = (
        "counterparty_unresponsive",
        "Other party was unresponsive",
    )
    DISPUTE_ITEM_NOT_RETURNED = (
        "dispute_item_not_returned",
        "Disputed item was not returned",
    )


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

    def counter_party(self, user: BorrowdUser) -> BorrowdUser:
        if user == self.party1:
            return self.party2

        if user == self.party2:
            return self.party1

        raise ValueError("User is not a party to this transaction.")

    def dispute_wait_has_elapsed(self) -> bool:
        """
        Whether the lender has waited long enough since requesting a return
        to be allowed to raise a dispute. Wait time is (RETURN_DISPUTE_WAIT_DAYS)
        """

        if self.return_requested_at is None:
            return False
        wait = timedelta(days=settings.RETURN_DISPUTE_WAIT_DAYS)
        return timezone.now() - self.return_requested_at >= wait

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
        """

        with transaction.atomic():
            item: Item = self.item
            item.refresh_from_db()
            if item.deleted_at is None:  # item not deleted
                item.status = ItemStatus.AVAILABLE
                item.save()

            self.status = TransactionStatus.RESOLVED
            self.resolution_reason = reason
            self.updated_by = resolved_by
            self.save()

    @staticmethod
    def get_requested_status_transactions_for_user(
        user: BorrowdUser,
    ) -> QuerySet["Transaction"]:
        """
        Returns Transactions which have a status of REQUESTED involving the given User.
        I.E., the borrower has asked, but the lender hasn't accepted or rejected yet.

        See get_active_borrows_for_user and get_active_lends_for_user for
        other transaction states that require user confirmation (pick ups/returns).
        """
        return Transaction.objects.filter(
            Q(status=TransactionStatus.REQUESTED) & (Q(party1=user) | Q(party2=user))
        )

    @staticmethod
    def get_active_borrows_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns Transactions where the given User is the active borrower (party 2)

        "Active" is defined by exclusion: every state except the closed ones
        (RETURNED, REJECTED, CANCELLED, RESOLVED) and the not-yet-accepted
        REQUESTED. In-flight states like COLLECTION_ASSERTED, RETURN_REQUESTED,
        and DISPUTED all count as active borrows.
        """
        return Transaction.objects.filter(
            Q(party2=user)
            # We filter by transaction status rather than item status so that
            # intermediate states like COLLECTION_ASSERTED appear as active
            # borrows before both parties have confirmed collection.
            & ~Q(
                # exclude these states
                status__in=[
                    TransactionStatus.RETURNED,
                    TransactionStatus.REQUESTED,
                    TransactionStatus.REJECTED,
                    TransactionStatus.CANCELLED,
                    TransactionStatus.RESOLVED,
                    TransactionStatus.OWNERSHIP_TRANSFERRED,
                ]
            )
        )

    @staticmethod
    def get_active_lends_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns Transactions where the given User is the active lender (party 1)

        "Active" is defined by exclusion: every state except the closed ones
        (RETURNED, REJECTED, CANCELLED, RESOLVED) and the not-yet-accepted
        REQUESTED. In-flight states like COLLECTION_ASSERTED, RETURN_REQUESTED,
        and DISPUTED all count as active lends.
        """
        return Transaction.objects.filter(
            Q(party1=user)
            & ~Q(
                status__in=[
                    TransactionStatus.RETURNED,
                    TransactionStatus.REQUESTED,
                    TransactionStatus.REJECTED,
                    TransactionStatus.CANCELLED,
                    TransactionStatus.RESOLVED,
                    TransactionStatus.OWNERSHIP_TRANSFERRED,
                ]
            )
        )


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
