from django.db.models import Exists, OuterRef, QuerySet

from borrowd_users.models import BorrowdUser

from .models import Membership, MembershipStatus


def memberships_in_groups_without_moderator(
    user: BorrowdUser,
) -> QuerySet[Membership]:
    """The user's active memberships in groups that have no active moderator."""
    active_moderator_memberships = Membership.objects.filter(
        group_id=OuterRef("group_id"),
        status=MembershipStatus.ACTIVE,
        is_moderator=True,
    )
    return (
        Membership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            is_moderator=False,
        )
        .annotate(has_active_moderator=Exists(active_moderator_memberships))
        .filter(has_active_moderator=False)
    )


def pending_memberships_moderated_by(user: BorrowdUser) -> QuerySet[Membership]:
    """Requests to join groups the user actively moderates, awaiting a decision."""
    moderated_group_ids = Membership.objects.filter(
        user=user,
        status=MembershipStatus.ACTIVE,
        is_moderator=True,
    ).values("group_id")
    return Membership.objects.filter(
        group_id__in=moderated_group_ids,
        status=MembershipStatus.PENDING,
    )


def group_action_count(user: BorrowdUser) -> int:
    """Group actions waiting on the user, for the Groups menu badge.

    Pending join requests the user can approve or deny, plus each of the
    user's groups that needs a moderator. Unlike the other menu badges this
    does not clear when the user opens Groups; each action counts until it
    is resolved.
    """
    return (
        pending_memberships_moderated_by(user).count()
        + memberships_in_groups_without_moderator(user).count()
    )
