from typing import Optional

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


class ItemAction(TextChoices):
    """
    Represents the actions that can be performed on an Item.
    This is used to determine which actions are available to the
    user when viewing an Item.
    """

    REQUEST_ITEM = "request_item", "Request Item"
    ACCEPT_REQUEST = "accept_request", "Accept Request"
    REJECT_REQUEST = "reject_request", "Reject Request"
    MARK_COLLECTED = "mark_collected", "Mark Collected"
    CONFIRM_COLLECTED = "confirm_collected", "Confirm Collected"
    MARK_RETURNED = "mark_returned", "Mark Returned"
    CONFIRM_RETURNED = "confirm_returned", "Confirm Returned"
    CANCEL_REQUEST = "cancel_request", "Cancel Request"


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
                    ]
                )
            )
        except Transaction.DoesNotExist:
            return None

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
