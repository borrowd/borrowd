from dataclasses import dataclass

from django.templatetags.static import static

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser

from .models import Badge, UserBadge

# Badge.slug values for the badges with an automated earning condition.
# Matches the static asset naming convention (see Badge's docstring).
SHARING_IS_CARING_SLUG = "items-badge"
SOCIAL_BUTTERFLY_SLUG = "groups-badge"
LOCAL_ACTIVIST_SLUG = "multi-group-badge"

_SHARING_IS_CARING_ITEM_THRESHOLD = 5
_SOCIAL_BUTTERFLY_MEMBER_THRESHOLD = 5
_LOCAL_ACTIVIST_GROUP_THRESHOLD = 2


@dataclass(frozen=True)
class BadgeDisplay:
    name: str
    description: str
    earned: bool
    icon_url: str


def get_badge_display_list(user: BorrowdUser) -> list[BadgeDisplay]:
    """All preloaded badges for display on a profile, each annotated with
    whether `user` has earned it and which icon (color or grayscale) to
    show -- grayscale for badges not yet earned.
    """
    earned_badge_ids = set(
        UserBadge.objects.filter(user=user).values_list("badge_id", flat=True)
    )
    return [
        BadgeDisplay(
            name=badge.name,
            description=badge.description,
            earned=badge.pk in earned_badge_ids,
            icon_url=static(
                f"badges/{badge.slug}.png"
                if badge.pk in earned_badge_ids
                else f"badges/{badge.slug}-gray.png"
            ),
        )
        for badge in Badge.objects.all()
    ]


def _award(user: BorrowdUser, slug: str) -> None:
    """Awards the badge with the given slug to `user`, if it's been seeded
    (see the `badges/badges` fixture) and not already earned. A badge
    referenced here but not yet seeded is a no-op rather than an error, so
    wiring up a condition can land ahead of its fixture entry.
    """
    badge = Badge.objects.filter(slug=slug).first()
    if badge is None:
        return
    UserBadge.objects.get_or_create(user=user, badge=badge)


def award_sharing_is_caring_if_needed(user: BorrowdUser) -> None:
    """Awards "Sharing is Caring" once a user has added 5 items to their
    inventory. Called from `ItemCreateView.form_valid` -- the one place a
    user adds an item through the app -- rather than an Item post_save
    signal, so it fires only on a user's own deliberate action and not on
    every incidental `Item.objects.create()` elsewhere (fixtures, other
    flows).
    """
    if Item.objects.filter(owner=user).count() >= _SHARING_IS_CARING_ITEM_THRESHOLD:
        _award(user, SHARING_IS_CARING_SLUG)


def award_local_activist_if_needed(user: BorrowdUser) -> None:
    """Awards "Local Activist" once a user has created 2 groups. Called
    from `GroupCreateView.form_valid` for the same reason as above.
    """
    group_count = BorrowdGroup.objects.filter(
        created_by=user, deleted_at__isnull=True
    ).count()
    if group_count >= _LOCAL_ACTIVIST_GROUP_THRESHOLD:
        _award(user, LOCAL_ACTIVIST_SLUG)


def award_social_butterfly_if_needed(group: BorrowdGroup) -> None:
    """Awards "Social Butterfly" to a group's creator once that group has 5
    active members. Unlike the item/group creation badges above, a
    membership can become active through several distinct flows (a direct
    add, an invite link, or a moderator approving a pending request), so
    this is called from a Membership post_save signal (see
    borrowd_groups/signals.py) rather than from any one view.
    """
    member_count = Membership.objects.filter(
        group=group, status=MembershipStatus.ACTIVE
    ).count()
    if member_count >= _SOCIAL_BUTTERFLY_MEMBER_THRESHOLD:
        _award(group.created_by, SOCIAL_BUTTERFLY_SLUG)
