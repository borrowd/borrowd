from typing import Iterable, Optional

from django.db.models import (
    CASCADE,
    PROTECT,
    SET_NULL,
    CharField,
    ForeignKey,
    ImageField,
    IntegerChoices,
    IntegerField,
    Model,
    Q,
    QuerySet,
    TextChoices,
)
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_users.models import BorrowdUser

from .exceptions import InvalidItemAction


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


class ItemCategory(Model):
    name: CharField[str, str] = CharField(max_length=50, null=False, blank=False)
    description: CharField[str, str] = CharField(max_length=100, null=True, blank=True)

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
    category: ForeignKey[ItemCategory] = ForeignKey(
        ItemCategory, on_delete=SET_NULL, null=True, blank=False
    )
    trust_level_required: IntegerField[TrustLevel, int] = IntegerField(
        choices=TrustLevel,
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

    def get_actions_for(self, user: BorrowdUser) -> Iterable[ItemAction]:
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
            if self.status == ItemStatus.AVAILABLE and self.owner != user:
                # THEN
                #   the User can Request the Item.
                return (ItemAction.REQUEST_ITEM,)
            else:
                # At this point, either:
                #   the item is not Available
                #   OR the user is the owner;
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
                    ItemAction.ACCEPT_REQUEST,
                    ItemAction.REJECT_REQUEST,
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
                ItemAction.MARK_COLLECTED,
                ItemAction.CANCEL_REQUEST,
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
        # permission `view_this_item` allows viewing a specific Item.
        permissions = [
            (
                "view_this_item",
                "Can view this item",
            ),
            (
                "edit_this_item",
                "Can edit this item",
            ),
            (
                "delete_this_item",
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
    image: ImageField = ImageField(upload_to="items", null=False, blank=False)

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

    @staticmethod
    def get_current_lends_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns the Items that are currently loaned to others by the given User.
        """
        return Transaction.objects.filter(
            Q(party1=user)
            & ~Q(
                status__in=[
                    TransactionStatus.RETURNED,
                    TransactionStatus.REJECTED,
                    TransactionStatus.CANCELLED,
                ]
            )
        )

    @staticmethod
    def get_current_borrows_for_user(user: BorrowdUser) -> QuerySet["Transaction"]:
        """
        Returns the Items the given User is currently borrowing from others.
        """
        return Transaction.objects.filter(
            Q(party2=user)
            & ~Q(
                status__in=[
                    TransactionStatus.RETURNED,
                    TransactionStatus.REJECTED,
                    TransactionStatus.CANCELLED,
                ]
            )
        )
