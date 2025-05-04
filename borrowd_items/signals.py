from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from .models import Item


@receiver(post_save, sender=Item)
def assign_item_permissions(
    sender: Item, instance: Item, created: bool, **kwargs: str
) -> None:
    """
    When a new Item is created, assign all relevant Item permissions
    to the owner and relevant Groups.
    """
    if created:
        for perm in ["view_this_item", "edit_this_item", "delete_this_item"]:
            assign_perm(
                perm,
                instance.owner,
                instance,
            )

        # Assign view permissions to all Groups of which the owner
        # is a member and has an equal or greater Trust Level than
        # the level required by this Item.
        # mypy struggling a bit here again, even though intellisense
        # knows that Item.owner (BorrowedUser) does indeed have a
        # a Groups accessor.
        allowed_groups = instance.owner.groups.filter(  # type: ignore[attr-defined]
            membership__trust_level__gte=instance.trust_level_required
        )
        assign_perm("view_this_item", allowed_groups, instance)
