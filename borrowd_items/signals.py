from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from borrowd_permissions.models import ItemOLP

from .models import Item


@receiver(post_save, sender=Item)
def assign_item_permissions(
    sender: Item, instance: Item, created: bool, **kwargs: str
) -> None:
    """
    When a new Item is created, assign all relevant Item permissions to the owner.
    On every save (update and creation), (re)derive the item's group-level permissions
    based on the current item owner
    """

    if created:
        for perm in [ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE]:
            assign_perm(perm, instance.owner, instance)
    instance.recompute_group_visibility()
