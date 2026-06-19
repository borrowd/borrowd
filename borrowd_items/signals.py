from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd_groups.models import MembershipStatus
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
    owner_borrowd_groups = instance.owner.borrowd_groups.filter(
        membership__user=instance.owner,  # looks redundant, but fails without it
        membership__status=MembershipStatus.ACTIVE,
    )
    owner_group_ids = owner_borrowd_groups.exclude(perms_group=None).values_list(
        "perms_group", flat=True
    )
    owner_groups = Group.objects.filter(pk__in=owner_group_ids)

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
        membership__user=instance.owner,  # looks redundant, but fails without it
        membership__trust_level__gte=instance.trust_level_required,
    ).exclude(perms_group=None)
    allowed_group_ids = allowed_borrowd_groups.values_list("perms_group", flat=True)
    allowed_groups = Group.objects.filter(pk__in=allowed_group_ids)
    assign_perm(ItemOLP.VIEW, allowed_groups, instance)
