from dataclasses import dataclass
from typing import Never, Optional

from django.core.exceptions import ValidationError
from django.db.models import (
    CASCADE,
    PROTECT,
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
)
from django.urls import reverse
from imagekit.models import ImageSpecField, ProcessedImageField
from imagekit.processors import ResizeToFill, ResizeToFit

from borrowd.models import TrustLevel
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser

from .exceptions import InvalidItemAction, ItemAlreadyRequested


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
    MARK_RETURNED = "MARK_RETURNED", "Mark Returned"
    CONFIRM_RETURNED = "CONFIRM_RETURNED", "Confirm Returned"
    CANCEL_REQUEST = "CANCEL_REQUEST", "Cancel Request"


@dataclass
class ItemActionContext:
    """
    Container for item actions and related context information.
    Combines action buttons with status text, eliminating the need for
    separate frontend logic and multiple DB calls.
    """

    actions: tuple[ItemAction, ...]
    status_text: str


class ItemCategory(Model):
    name: CharField[str, str] = CharField(max_length=50, null=False, blank=False)
    description: CharField[str, str] = CharField(max_length=100, null=True, blank=True)

    # Hint for mypy (actual field created from reverse M2M relation)
    items: QuerySet["Item"]

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name: str = "Item Category"
        verbose_name_plural: str = "Item Categories"


class ItemStatus(IntegerChoices):
    """
    Represents the status of an Item. This is used to track the
    current state of an Item, and to determine which actions are
    available to the user.
    """

    # Paranoia forcing to me to use value increments of at least 10,
    # for when we later realize we need to add more in between...
    AVAILABLE = 10, "Available"
    RESERVED = 20, "Reserved"
    BORROWED = 30, "Borrowed"


class Item(Model):
    name: CharField[str, str] = CharField(max_length=50, null=False, blank=False)
    description: CharField[str, str] = CharField(
        max_length=500, null=False, blank=False
    )
    # If user is deleted, delete their Items
    owner: ForeignKey[BorrowdUser] = ForeignKey(BorrowdUser, on_delete=CASCADE)

    categories: ManyToManyField[ItemCategory, ItemCategory] = ManyToManyField(
        ItemCategory,
        related_name="items",
        blank=False,
        help_text="Categories this item belongs to. At least one required.",
    )
    trust_level_required: IntegerField[TrustLevel, int] = IntegerField(
        choices=TrustLevel,
        default=TrustLevel.HIGH,
        help_text=(
            "The minimum required Group trust level required for"
            " this Item to be visible to and borrowable by members"
            " of that Group."
        ),
    )
    status: IntegerField[ItemStatus, int] = IntegerField(
        choices=ItemStatus.choices,
        default=ItemStatus.AVAILABLE,
        help_text="The current status of the Item.",
    )

    # Hint for mypy (actual field created from reverse relation)
    transactions: QuerySet["Transaction"]

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

    def get_action_context_for(self, user: BorrowdUser) -> ItemActionContext:
        """
        Returns ItemActionContext containing ItemActions [e.g. REQUEST_ITEM, ACCEPT_REQUEST]
        and status information [e.g. "You are currently borrowing this item."] for the given user.
        """

        current_borrower = self.get_current_borrower()
        requesting_user = self.get_requesting_user()
        actions = self.get_actions_for(user)

        # Generate status text based on user role and current actions/status
        status_text = self._get_status_text_for_user(
            user=user,
            actions=actions,
            current_borrower=current_borrower,
            requesting_user=requesting_user,
        )

        return ItemActionContext(actions=actions, status_text=status_text)

    def _get_status_text_for_user(
        self,
        user: BorrowdUser,
        actions: tuple[ItemAction, ...],
        current_borrower: Optional[BorrowdUser],
        requesting_user: Optional[BorrowdUser],
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
            return self._get_owner_status_text(actions, requester_name, borrower_name)
        elif is_borrower:
            return self._get_borrower_status_text(actions)
        else:
            return self._get_other_user_status_text(actions)

    def _get_owner_status_text(
        self, actions: tuple[ItemAction, ...], requester_name: str, borrower_name: str
    ) -> str:
        """Generate status text for item owners."""

        if ItemAction.ACCEPT_REQUEST in actions:
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
    def _get_borrower_status_text(self, actions: tuple[ItemAction, ...]) -> str:
        owner_name = self.owner.profile.full_name()  # type: ignore[attr-defined]
        """Generate status text for current borrowers."""
        if ItemAction.CANCEL_REQUEST in actions:
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

    def _get_other_user_status_text(self, actions: tuple[ItemAction, ...]) -> str:
        """Generate status text for users who are neither owner nor borrower."""
        if len(actions) == 1 and ItemAction.CANCEL_REQUEST in actions:
            # Intentionally obscuring owner name here for privacy to reject
            return "Requested to borrow, waiting on owner response..."
        elif ItemAction.REQUEST_ITEM in actions:
            return "Available to request!"
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

        Splitting the status / context between the Item itself and
        Transactions related to the Item enables e.g. simultaneous
        Requests from multiple Users, from which the lender can
        choose; as opposed to immediately blocking the Item's status
        based on the first Request that happens to come in.

        This smooths the borrowing process, giving inventory more
        apparent liquidity (there will be less time when Users will
        see Items as unavailable) and will also help provide lenders
        with some "plausible deniability" if they do not wish to
        accept a Request from a specific User.
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
            else:
                # At this point, either:
                #   the item is not Available
                #   OR the user is the owner
                #   OR there's already a pending request from another user;
                # either way, no Request can be initiated.

                # NOTE Later we may want to allow new Requests on Items
                # even when they're currently Borrowed; that will
                # imply date-based borrowing bookings, which we're
                # not tackling yet.
                return tuple()

        # If we get here, we have exactly one Transaction involving
        # this Item and this User. Let's figure out what are the
        # valid next ItemActions...
        # TODO. This is a bit hairy. Upgrade to state machine?
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
            return (ItemAction.MARK_RETURNED,)
        elif current_tx.status == TransactionStatus.RETURN_ASSERTED:
            # Make sure the same person doesn't confirm the assertion
            if current_tx.updated_by != user:
                return (ItemAction.CONFIRM_RETURNED,)
            else:
                # Otherwise, nothing to do but wait...
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
            return transaction.party2  # type: ignore[return-value]
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
            return txn.party2 if txn else None  # type: ignore[return-value]

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
                        TransactionStatus.RETURN_ASSERTED,
                    ]
                )
            )
            # party2 is the borrower
            return transaction.party2  # type: ignore[return-value]
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
                            TransactionStatus.RETURN_ASSERTED,
                        ]
                    )
                )
                .order_by("-updated_at")
                .first()
            )
            return txn.party2 if txn else None  # type: ignore[return-value]

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
                    ]
                )
            )
        except Transaction.DoesNotExist:
            return None

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
                updated_by=user,
                # This is default; just being explicit
                status=TransactionStatus.REQUESTED,
            )
            return

        current_tx = self.get_current_transaction_for_user(user=user)
        if current_tx is None:
            # This should have been caught earlier, but check again
            # partly to keep mypy happy.
            raise ValueError("No existing Transaction")

        # TODO: Wrap in transaction
        match action:
            case ItemAction.REJECT_REQUEST:
                # The owner/lender/giver rejects the Request.
                current_tx.status = TransactionStatus.REJECTED
                current_tx.updated_by = user
                current_tx.save()
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
            case ItemAction.CONFIRM_RETURNED:
                # The other party confirms return.
                current_tx.status = TransactionStatus.RETURNED
                current_tx.updated_by = user
                current_tx.save()
                self.status = ItemStatus.AVAILABLE
                self.save()
            case ItemAction.CANCEL_REQUEST:
                # The requestor cancels the Request.
                current_tx.status = TransactionStatus.CANCELLED
                current_tx.updated_by = user
                current_tx.save()
                self.status = ItemStatus.AVAILABLE
                self.save()
            case _:
                # We shouldn't get here...
                raise ValueError(
                    f"Unexpected action '{action}' for Item '{self}' and User '{user}'"
                )

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
    item: ForeignKey[Item] = ForeignKey(Item, on_delete=CASCADE, related_name="photos")
    item_id: int  # hint for mypy
    image = ProcessedImageField(
        upload_to="items/",
        processors=[ResizeToFit(1600, 1600)],
        format="JPEG",
        options={"quality": 75},
    )
    thumbnail = ImageSpecField(
        source="image",
        processors=[ResizeToFill(200, 200)],
        format="JPEG",
        options={"quality": 75},
    )

    def __str__(self) -> str:
        # error: "_ST" has no attribute "name"  [attr-defined]
        return f"Photo of {self.item.name}"  # type: ignore[attr-defined]


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
    RETURN_ASSERTED = 60, "Return Asserted"
    RETURNED = 70, "Returned"
    CANCELLED = 80, "Cancelled"


class Transaction(Model):
    item: ForeignKey["Item"] = ForeignKey(
        to="Item",
        on_delete=PROTECT,
        related_name="transactions",
        help_text="The Item which is the subject of the Transaction.",
    )
    party1: ForeignKey[BorrowdUser] = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The first party in the Transaction: 'lender', 'giver', 'owner', etc.",
    )
    party2: ForeignKey[BorrowdUser] = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The second party in the Transaction: 'borrower', 'receiver', etc.",
    )
    status: IntegerField[TransactionStatus, int] = IntegerField(
        choices=TransactionStatus.choices,
        default=TransactionStatus.REQUESTED,
        help_text="The current status of the Transaction.",
    )
    updated_by: ForeignKey[BorrowdUser] = ForeignKey(
        to=BorrowdUser,
        on_delete=PROTECT,
        related_name="+",  # No reverse relation needed
        help_text="The User who last updated the Transaction.",
    )
    created_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now_add=True,
        help_text="When this Transaction was created.",
    )
    updated_at: DateTimeField[Never, Never] = DateTimeField(
        auto_now=True,
        help_text="When this Transaction was last updated.",
    )

    @staticmethod
    def get_pending_transactions_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns all Transactions that are currently pending for the given User.
        This includes both requests to borrow Items and requests from the User
        to borrow Items.
        """
        return Transaction.objects.filter(
            Q(
                status__in=[
                    TransactionStatus.REQUESTED,
                    TransactionStatus.ACCEPTED,
                ]
            )
            # Considering transactions to confirm collection/return as pending requests also
            | ~Q(updated_by=user)
            & Q(
                status__in=[
                    TransactionStatus.COLLECTION_ASSERTED,
                    TransactionStatus.RETURN_ASSERTED,
                ]
            )
        )

    @staticmethod
    def get_borrow_requests_to_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns other Users' requests to the given User to borrow Items.
        """
        return Transaction.get_pending_transactions_for_user(user).filter(
            Q(party1=user)
        )

    @staticmethod
    def get_borrow_requests_from_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns requests from the given User to borrow from others.
        """
        return Transaction.get_pending_transactions_for_user(user).filter(
            Q(party2=user)
        )

    @staticmethod
    def get_current_borrows_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns the Items the given User is currently borrowing from others.
        """
        return Transaction.objects.filter(
            Q(party2=user)
            # We could query on item__status=BORROWED, however in that case items marked 'Collection Asserted'
            # would not appear as Borrowed until they were confirmed/marked as collected by both parties
            & ~Q(
                status__in=[
                    TransactionStatus.RETURNED,
                    TransactionStatus.REQUESTED,
                    # only considering it "Borrowed" once it has been collected, not just accepted
                    TransactionStatus.ACCEPTED,
                    TransactionStatus.REJECTED,
                    TransactionStatus.CANCELLED,
                ]
            )
        )
