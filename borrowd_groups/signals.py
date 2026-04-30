from typing import Any, cast

from django.contrib.auth.models import Group
from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, remove_perm

from borrowd.models import TrustLevel
from borrowd_groups.exceptions import ModeratorRequiredException
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item
from borrowd_permissions.models import BorrowdGroupOLP, ItemOLP
from borrowd_users.models import BorrowdUser


def compute_per_group_unique_name(base_name: str, user_id: int) -> str:
    """
    Compute a unique name for the auth Group associated with a BorrowdGroup,
    based on the BorrowdGroup's name and the ID of the user that created it.
    This is necessary because Django's auth Groups require globally unique names,
    but we want to allow different users to create groups with the same name.
    """
    return f"{base_name}_user_{user_id}"


@receiver(post_save, sender=BorrowdGroup)
def maintain_perms_group_on_borrowd_group_change(
    sender: BorrowdGroup, instance: BorrowdGroup, created: bool, **kwargs: str
) -> None:
    # on create, create the perms group, then save the reference to the perms
    # group onto the borrowd group, because we need to maintain this linkage
    # even if the name changes
    if created:
        creator = instance.created_by
        perms_group = Group.objects.create(
            name=compute_per_group_unique_name(instance.name, creator.pk)  # type: ignore[attr-defined]
        )
        instance.perms_group = perms_group
        instance.save()

    # on update, make sure that the names still match
    else:
        perms_group = instance.perms_group
        creator = instance.created_by
        perms_group_name = compute_per_group_unique_name(
            instance.name,
            creator.pk,  # type: ignore[attr-defined]
        )
        if perms_group.name != perms_group_name:
            perms_group.name = perms_group_name
            perms_group.save()


@receiver(pre_delete, sender=BorrowdGroup)
def stash_perms_group_for_cleanup(
    sender: type[BorrowdGroup], instance: BorrowdGroup, **kwargs: Any
) -> None:
    """
    Keep track of the linked auth Group so it can be deleted once the
    BorrowdGroup cascade has completed.
    """
    setattr(instance, "_perms_group_id_for_cleanup", instance.perms_group.pk)


@receiver(post_delete, sender=BorrowdGroup)
def delete_perms_group_on_borrowd_group_delete(
    sender: type[BorrowdGroup], instance: BorrowdGroup, **kwargs: Any
) -> None:
    """
    Delete the linked auth Group after related Membership cleanup has run.
    """
    perms_group_id = getattr(instance, "_perms_group_id_for_cleanup", None)
    if perms_group_id is not None:
        Group.objects.filter(pk=perms_group_id).delete()


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
    # Allow flows like leave group to bypass this guard.
    membership = kwargs.get("instance")
    if membership and getattr(membership, "_bypass_last_moderator_check", False):
        return

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
    membership = instance
    # error: "_ST" has no attribute "perms_group" / "groups"
    user = cast(BorrowdUser, instance.user)
    borrowd_group = cast(BorrowdGroup, instance.group)
    group = borrowd_group.perms_group
    if group is None:
        # This should never happen, but just in case...
        raise ValueError(
            "This BorrowdGroup has no perms_group; cannot sync permissions."
        )
    new_trust_level = instance.trust_level

    # Handle Group permissions
    all_group_perms = [
        BorrowdGroupOLP.VIEW,
        BorrowdGroupOLP.EDIT,
        BorrowdGroupOLP.DELETE,
    ]
    moderator_perms = [
        BorrowdGroupOLP.EDIT,
        BorrowdGroupOLP.DELETE,
    ]
    items_of_user = Item.objects.filter(owner=user)

    if membership.status == MembershipStatus.ACTIVE:
        # Keep auth group membership in sync with ACTIVE status.
        user.groups.add(group)

        # Get all items associated with the group
        items_requiring_higher_trust = Item.objects.filter(
            owner=user, trust_level_required__gt=new_trust_level
        )
        items_requiring_lower_trust = Item.objects.filter(
            owner=user, trust_level_required__lte=new_trust_level
        )

        for item_perm in [ItemOLP.VIEW]:  # will have more later
            remove_perm(item_perm, group, items_requiring_higher_trust)
            assign_perm(item_perm, group, items_requiring_lower_trust)

        member_perms = [BorrowdGroupOLP.VIEW]
        if membership.is_moderator:
            member_perms += moderator_perms
        else:
            # Remove moderator permissions if the user is no longer a moderator
            for group_perm in moderator_perms:
                remove_perm(group_perm, user, borrowd_group)

        for group_perm in member_perms:
            assign_perm(group_perm, user, borrowd_group)
    else:
        user.groups.remove(group)
        for group_perm in all_group_perms:
            remove_perm(group_perm, user, borrowd_group)
        for item_perm in [ItemOLP.VIEW]:  # will have more later
            remove_perm(item_perm, group, items_of_user)


@receiver(pre_delete, sender=Membership)
def pre_membership_delete(
    sender: Membership, instance: Membership, **kwargs: Any
) -> None:
    """
    Remove all permissions for the user on the group and items
    when their membership is deleted.
    """
    membership = instance
    user = cast(BorrowdUser, membership.user)
    borrowd_group = cast(BorrowdGroup, membership.group)
    group = borrowd_group.perms_group
    #
    # Check the group will not be left without a Moderator
    # Pass the membership instance through so intentional bypass flags
    # set by specific flows, such as leave-group, are respected.
    #
    _raise_if_last_moderator(user, borrowd_group, instance=membership, **kwargs)
    #
    # Remove the user from the Django auth Group so they immediately lose
    # all group-inherited object-level permissions (e.g. VIEW on other
    # members' items). This is idempotent — safe even if
    # BorrowdGroup.remove_user() already called it.
    #
    user.groups.remove(group)

    #
    # Handle Group removal
    #
    group_perms = [
        BorrowdGroupOLP.VIEW,
        BorrowdGroupOLP.EDIT,
        BorrowdGroupOLP.DELETE,
    ]
    # Remove all permissions for the user on the group
    for group_perm in group_perms:
        remove_perm(group_perm, user, borrowd_group)

    #
    # Handle Item removal
    #
    items_of_user = Item.objects.filter(owner=user)
    for item_perm in [ItemOLP.VIEW]:  # will have more later
        remove_perm(item_perm, group, items_of_user)


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
    user = cast(BorrowdUser, membership.user)
    group = cast(BorrowdGroup, membership.group)

    # Check if the user is being added as a moderator
    if not membership.is_moderator:
        _raise_if_last_moderator(user, group, **kwargs)
