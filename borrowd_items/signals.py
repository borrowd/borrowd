from typing import Any

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm

from borrowd_permissions.models import ItemOLP

from .models import Item

# The Item fields that decide which groups can see it. Group membership and
# shared_with_groups have receivers of their own.
_VISIBILITY_FIELDS = frozenset({"owner", "share_with_all_groups"})


@receiver(post_save, sender=Item)
def assign_item_permissions(
    sender: type[Item],
    instance: Item,
    created: bool,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    """
    When a new Item is created, assign all relevant Item permissions to the owner.
    On every save that could change who sees the item, (re)derive the item's
    group-level permissions based on the current item owner
    """

    if created:
        for perm in [ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE]:
            assign_perm(perm, instance.owner, instance)
    # A save limited to other fields, like a status change, leaves them as is.
    if update_fields is not None and not _VISIBILITY_FIELDS & update_fields:
        return
    instance.recompute_group_visibility()


@receiver(m2m_changed, sender=Item.shared_with_groups.through)
def recompute_visibility_on_shared_groups_change(
    sender: Any, instance: Any, action: str, **kwargs: Any
) -> None:
    # post_add / post_remove / post_clear fire after the M2M table is updated
    if action in ("post_add", "post_remove", "post_clear"):
        if isinstance(instance, Item):
            instance.recompute_group_visibility()
