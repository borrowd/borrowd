from django.db.models import CASCADE, SET_NULL, CharField, ForeignKey, Model
from django.urls import reverse

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

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("item-detail", args=[self.pk])
