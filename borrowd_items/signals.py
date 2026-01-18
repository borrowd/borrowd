from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd_permissions.models import ItemOLP

from .models import Item


@receiver(post_save, sender=Item)
def assign_item_permissions(
    sender: Item, instance: Item, created: bool, **kwargs: str
) -> None:
    """
    When a new Item is created or updated, assign all relevant Item permissions
    to the owner and relevant Groups.
    """
    owner_borrowd_groups = instance.owner.borrowd_groups.all()  # type: ignore[attr-defined]
    owner_groups = Group.objects.filter(
        name__in=owner_borrowd_groups.values_list("name", flat=True)
    )

    if created:
        # For new items, assign owner permissions
        for perm in [ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE]:
            assign_perm(
                perm,
                instance.owner,
                instance,
            )
    else:
        # For updated items, remove existing group permissions first
        for group in owner_groups:
            remove_perm(ItemOLP.VIEW, group, instance)

    # Assign view permissions to all Groups of which the owner
    # is a member and has an equal or greater Trust Level than
    # the level required by this Item.
    allowed_borrowd_groups = owner_borrowd_groups.filter(
        membership__trust_level__gte=instance.trust_level_required
    )
    allowed_groups = owner_groups.filter(
        name__in=allowed_borrowd_groups.values_list("name", flat=True)
    )
    assign_perm(ItemOLP.VIEW, allowed_groups, instance)
