from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd_groups.models import Membership
from borrowd_items.models import Item


@receiver(post_save, sender=Membership)
def refresh_item_permissions_on_membership_update(
    sender: Membership, instance: Membership, created: bool, **kwargs: str
) -> None:
    """
    Refresh the permissions of items for the given group when a
    user's membership in the group is updated.
    """
    # Get the user and group from the membership instance
    user = instance.user
    group = instance.group
    new_trust_level = instance.trust_level

    # Get all items associated with the group
    items_requiring_higher_trust = Item.objects.filter(
        owner=user, trust_level_required__gt=new_trust_level
    )
    items_requiring_lower_trust = Item.objects.filter(
        owner=user, trust_level_required__lte=new_trust_level
    )

    for perm in ["view_this_item"]:  # will have more later
        remove_perm(perm, group, items_requiring_higher_trust)
        assign_perm(perm, group, items_requiring_lower_trust)
