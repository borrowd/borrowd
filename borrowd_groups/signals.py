from typing import Any

from django.contrib.auth.models import Group
from django.db.models.query import QuerySet
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd.models import TrustLevel
from borrowd_groups.exceptions import ModeratorRequiredException
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser


@receiver(post_save, sender=BorrowdGroup)
def create_perms_group_on_borrowd_group_creation(
    sender: BorrowdGroup, instance: BorrowdGroup, created: bool, **kwargs: str
) -> None:
    # Only run this logic on instance creation
    if not created:
        return

    Group.objects.create(name=instance.name)


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


def _raise_if_last_moderator(
    user: BorrowdUser, group: BorrowdGroup, **kwargs: Any
) -> None:
    """
    Check if a group has any remaining moderators.
    If not, raise a ModeratorRequiredException.
    """
    # First, only apply this logic if we're NOT in a cascade delete
    # from the Group itself.
    origin = kwargs.get("origin")
    if not origin or (
        origin
        and not isinstance(origin, BorrowdGroup)
        and not (
            isinstance(origin, QuerySet) and isinstance(origin.model, BorrowdGroup)
        )
    ):
        other_moderators = Membership.objects.filter(
            group=group, is_moderator=True
        ).exclude(user=user)

        if not other_moderators.exists():
            # This error message applies whether the attempted action
            # is removing the User from the Group, _or_ changing them
            # to non-moderator status.
            raise ModeratorRequiredException(
                f"User '{user.username}' is the last moderator in"
                f" Group '{group.name}': cannot remove."
            )


@receiver(post_save, sender=Membership)
def refresh_permissions_on_membership_update(
    sender: Membership, instance: Membership, created: bool, **kwargs: str
) -> None:
    """
    Refresh the permissions of Items and Groups for the given Group
    when a User's Membership in the Group is updated.
    """
    #
    # Handle Item permissions
    #
    user = instance.user
    borrowd_group = instance.group
    # error: "_ST" has no attribute "name"  [attr-defined]
    group = Group.objects.get(name=borrowd_group.name)  # type: ignore[attr-defined]
    new_trust_level = instance.trust_level
    membership = instance

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

    #
    # Handle Group permissions
    #
    member_perms = ["view_this_group"]
    moderator_perms = [
        "edit_this_group",
        "delete_this_group",
    ]
    if membership.is_moderator:
        member_perms += moderator_perms
    else:
        # Remove moderator permissions if the user is no longer a moderator
        for perm in moderator_perms:
            remove_perm(perm, user, borrowd_group)

    for perm in member_perms:
        assign_perm(perm, user, borrowd_group)


@receiver(pre_delete, sender=BorrowdGroup)
def borrowd_group_pre_delete_remove_perms_group(
    sender: BorrowdGroup, instance: BorrowdGroup, **kwargs: Any
) -> None:
    # Use get() as there should always be exactly one; see
    # `create_perms_group_on_borrowd_group_creation()` above.
    group = Group.objects.get(name=instance.name)
    group.delete()


@receiver(pre_delete, sender=Membership)
def pre_membership_delete(
    sender: Membership, instance: Membership, **kwargs: Any
) -> None:
    """
    Remove all permissions for the user on the group and items
    when their membership is deleted.
    """
    membership = instance
    user: BorrowdUser = membership.user  # type: ignore[assignment]
    borrowd_group: BorrowdGroup = membership.group  # type: ignore[assignment]

    #
    # Check the group will not be left without a Moderator
    #
    _raise_if_last_moderator(user, borrowd_group, **kwargs)

    #
    # Handle permissions removal
    #
    all_perms = [
        "view_this_group",
        "edit_this_group",
        "delete_this_group",
    ]
    # Remove all permissions for the user on the group
    for perm in all_perms:
        remove_perm(perm, user, borrowd_group)


@receiver(pre_save, sender=Membership)
def pre_membership_save(
    sender: Membership, instance: Membership, **kwargs: Any
) -> None:
    """
    Check if the user being saved is a moderator of the group.
    If not, check if the group has any other moderators.
    If not, raise a ModeratorRequiredException.
    """
    membership = instance
    user: BorrowdUser = membership.user  # type: ignore[assignment]
    group: BorrowdGroup = membership.group  # type: ignore[assignment]

    # Check if the user is being added as a moderator
    if not membership.is_moderator:
        _raise_if_last_moderator(user, group, **kwargs)
