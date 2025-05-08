from django.db.models.signals import post_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser


@receiver(post_save, sender=BorrowdGroup)
def set_moderator_on_group_creation(
    sender: BorrowdGroup, instance: BorrowdGroup, created: bool, **kwargs: str
) -> None:
    """
    When a Group is created, ensure the user that created it becomes
    a member automatically, and is designated a moderator.
    """
    if not created:
        return

    group: BorrowdGroup = instance
    # mypy error: Incompatible types in assignment (expression has type "_ST", variable has type "BorrowdUser")  [assignment]
    creator: BorrowdUser = group.created_by  # type: ignore[assignment]
    # By default, assume High trust for a Group which a user has
    # created themselves.
    trust_level: TrustLevel = (
        getattr(group, "_temp_trust_level", None) or TrustLevel.HIGH
    )

    group.add_user(
        user=creator,
        trust_level=trust_level,
        is_moderator=True,
    )


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
