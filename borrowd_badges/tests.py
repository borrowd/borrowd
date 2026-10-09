from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser

from .models import Badge, UserBadge
from .services import (
    LOCAL_ACTIVIST_SLUG,
    SHARING_IS_CARING_SLUG,
    SOCIAL_BUTTERFLY_SLUG,
    award_local_activist_if_needed,
    award_sharing_is_caring_if_needed,
    award_social_butterfly_if_needed,
    get_badge_display_list,
)


class BadgeTests(TestCase):
    def test_str_returns_name(self) -> None:
        badge = Badge.objects.create(slug="trophy", name="Trophy")
        self.assertEqual(str(badge), "Trophy")


class UserBadgeTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="earner", email="earner@example.com", password="password"
        )
        self.badge = Badge.objects.create(slug="trophy", name="Trophy")

    def test_str_describes_the_award(self) -> None:
        user_badge = UserBadge.objects.create(user=self.user, badge=self.badge)
        self.assertEqual(str(user_badge), f"{self.user} earned {self.badge}")

    def test_a_badge_can_only_be_earned_once_per_user(self) -> None:
        UserBadge.objects.create(user=self.user, badge=self.badge)
        with self.assertRaises(IntegrityError):
            UserBadge.objects.create(user=self.user, badge=self.badge)


class GetBadgeDisplayListTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="viewer", email="viewer@example.com", password="password"
        )
        self.badge = Badge.objects.create(
            slug="trophy", name="Trophy", description="A test badge.", display_order=1
        )

    def test_unearned_badge_shows_the_grayscale_icon(self) -> None:
        [display] = get_badge_display_list(self.user)

        self.assertFalse(display.earned)
        self.assertEqual(display.name, "Trophy")
        self.assertEqual(display.description, "A test badge.")
        self.assertTrue(display.icon_url.endswith("badges/trophy-gray.png"))

    def test_earned_badge_shows_the_color_icon(self) -> None:
        UserBadge.objects.create(user=self.user, badge=self.badge)

        [display] = get_badge_display_list(self.user)

        self.assertTrue(display.earned)
        self.assertTrue(display.icon_url.endswith("badges/trophy.png"))
        self.assertFalse(display.icon_url.endswith("-gray.png"))

    def test_another_users_award_does_not_count(self) -> None:
        other_user = BorrowdUser.objects.create_user(
            username="other", email="other@example.com", password="password"
        )
        UserBadge.objects.create(user=other_user, badge=self.badge)

        [display] = get_badge_display_list(self.user)

        self.assertFalse(display.earned)

    def test_returns_every_preloaded_badge_in_display_order(self) -> None:
        Badge.objects.create(slug="early-bird", name="Early Bird", display_order=0)

        displays = get_badge_display_list(self.user)

        self.assertEqual([d.name for d in displays], ["Early Bird", "Trophy"])


def _earned(user: BorrowdUser, slug: str) -> bool:
    return UserBadge.objects.filter(user=user, badge__slug=slug).exists()


class AwardSharingIsCaringTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="lender", email="lender@example.com", password="password"
        )
        self.category = ItemCategory.objects.create(name="Tools")
        Badge.objects.create(slug=SHARING_IS_CARING_SLUG, name="Sharing is Caring")

    def _add_items(self, count: int) -> None:
        for i in range(count):
            item = Item.objects.create(
                name=f"Item {i}",
                description="A description",
                owner=self.user,
                created_by=self.user,
                updated_by=self.user,
            )
            item.categories.add(self.category)

    def test_not_awarded_below_the_threshold(self) -> None:
        self._add_items(4)

        award_sharing_is_caring_if_needed(self.user)

        self.assertFalse(_earned(self.user, SHARING_IS_CARING_SLUG))

    def test_awarded_once_the_threshold_is_reached(self) -> None:
        self._add_items(5)

        award_sharing_is_caring_if_needed(self.user)

        self.assertTrue(_earned(self.user, SHARING_IS_CARING_SLUG))

    def test_a_soft_deleted_item_does_not_count_toward_the_threshold(self) -> None:
        self._add_items(5)
        item = Item.objects.filter(owner=self.user).first()
        assert item is not None
        item.deleted_at = timezone.now()
        item.deleted_by = self.user
        item.save()

        award_sharing_is_caring_if_needed(self.user)

        self.assertFalse(_earned(self.user, SHARING_IS_CARING_SLUG))

    def test_is_a_no_op_when_the_badge_has_not_been_seeded(self) -> None:
        Badge.objects.filter(slug=SHARING_IS_CARING_SLUG).delete()
        self._add_items(5)

        award_sharing_is_caring_if_needed(self.user)

        self.assertEqual(UserBadge.objects.count(), 0)

    def test_calling_it_again_does_not_duplicate_the_award(self) -> None:
        self._add_items(6)

        award_sharing_is_caring_if_needed(self.user)
        award_sharing_is_caring_if_needed(self.user)

        self.assertEqual(
            UserBadge.objects.filter(
                user=self.user, badge__slug=SHARING_IS_CARING_SLUG
            ).count(),
            1,
        )


class AwardLocalActivistTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="organizer", email="organizer@example.com", password="password"
        )
        Badge.objects.create(slug=LOCAL_ACTIVIST_SLUG, name="Local Activist")

    def _create_groups(self, count: int) -> None:
        for i in range(count):
            BorrowdGroup.objects.create_group(
                name=f"Group {i}",
                created_by=self.user,
                updated_by=self.user,
                membership_requires_approval=False,
            )

    def test_not_awarded_below_the_threshold(self) -> None:
        self._create_groups(1)

        award_local_activist_if_needed(self.user)

        self.assertFalse(_earned(self.user, LOCAL_ACTIVIST_SLUG))

    def test_awarded_once_the_threshold_is_reached(self) -> None:
        self._create_groups(2)

        award_local_activist_if_needed(self.user)

        self.assertTrue(_earned(self.user, LOCAL_ACTIVIST_SLUG))

    def test_a_soft_deleted_group_does_not_count_toward_the_threshold(self) -> None:
        self._create_groups(2)
        group = BorrowdGroup.objects.filter(created_by=self.user).first()
        assert group is not None
        group.deleted_at = timezone.now()
        group.deleted_by = self.user
        group.save()

        award_local_activist_if_needed(self.user)

        self.assertFalse(_earned(self.user, LOCAL_ACTIVIST_SLUG))


class AwardSocialButterflyTests(TestCase):
    def setUp(self) -> None:
        self.creator = BorrowdUser.objects.create_user(
            username="host", email="host@example.com", password="password"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="A Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=False,
        )
        Badge.objects.create(slug=SOCIAL_BUTTERFLY_SLUG, name="Social Butterfly")

    def _add_members(self, count: int) -> None:
        for i in range(count):
            member = BorrowdUser.objects.create_user(
                username=f"member{i}", email=f"member{i}@example.com"
            )
            self.group.add_user(member)

    def test_not_awarded_below_the_threshold(self) -> None:
        # The creator is already an active member (1); 3 more makes 4.
        self._add_members(3)

        award_social_butterfly_if_needed(self.group)

        self.assertFalse(_earned(self.creator, SOCIAL_BUTTERFLY_SLUG))

    def test_awarded_to_the_creator_once_the_threshold_is_reached(self) -> None:
        # The creator is already an active member (1); 4 more makes 5.
        self._add_members(4)

        award_social_butterfly_if_needed(self.group)

        self.assertTrue(_earned(self.creator, SOCIAL_BUTTERFLY_SLUG))

    def test_joining_members_do_not_themselves_earn_the_badge(self) -> None:
        self._add_members(4)

        award_social_butterfly_if_needed(self.group)

        self.assertEqual(UserBadge.objects.count(), 1)


class MembershipSignalAwardsSocialButterflyTests(TestCase):
    """End-to-end: joining a group via Membership (not a direct call into
    the service) should award the creator once the group hits 5 active
    members -- covers the Membership post_save wiring in
    borrowd_groups/signals.py.
    """

    def test_fifth_member_joining_awards_the_creator(self) -> None:
        creator = BorrowdUser.objects.create_user(
            username="host2", email="host2@example.com", password="password"
        )
        group = BorrowdGroup.objects.create_group(
            name="Another Group",
            created_by=creator,
            updated_by=creator,
            membership_requires_approval=False,
        )
        Badge.objects.create(slug=SOCIAL_BUTTERFLY_SLUG, name="Social Butterfly")

        for i in range(4):
            member = BorrowdUser.objects.create_user(
                username=f"joiner{i}", email=f"joiner{i}@example.com"
            )
            group.add_user(member)

        self.assertTrue(_earned(creator, SOCIAL_BUTTERFLY_SLUG))
