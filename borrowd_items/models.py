from django.db.models import (
    CASCADE,
    SET_NULL,
    CharField,
    ForeignKey,
    IntegerField,
    ImageField,
    Model,
)
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_users.models import BorrowdUser


class ItemCategory(Model):
    name: CharField[str, str] = CharField(max_length=50, null=False, blank=False)
    description: CharField[str, str] = CharField(max_length=100, null=True, blank=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name: str = "Item Category"
        verbose_name_plural: str = "Item Categories"


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

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("item-detail", args=[self.pk])

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
    image: ImageField = ImageField(upload_to="items", null=False, blank=False)

    def __str__(self) -> str:
        return f"Photo of {self.item.name}"