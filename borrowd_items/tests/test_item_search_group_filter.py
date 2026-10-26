from django.test import TestCase
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


class ItemSearchGroupFilterTests(TestCase):
    """The item search page's `groups` filter (ItemFilter.filter_by_groups),
    in addition to the existing `categories` filter."""

    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.viewer = BorrowdUser.objects.create_user(
            username="viewer", email="viewer@example.com", password="password"
        )
        self.category = ItemCategory.objects.create(name="Tools")

    def _create_group(self, name: str) -> BorrowdGroup:
        return BorrowdGroup.objects.create_group(
            name=name,
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )

    def _create_item(self, name: str, *, share_with_all_groups: bool) -> Item:
        item = Item.objects.create(
            name=name,
            description="A description",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            share_with_all_groups=share_with_all_groups,
        )
        item.categories.add(self.category)
        return item

    def test_filter_matches_item_shared_with_all_groups(self) -> None:
        group = self._create_group("A Group")
        group.add_user(self.viewer)
        self._create_item("Drill", share_with_all_groups=True)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"groups": group.pk})

        self.assertContains(response, "Drill")

    def test_filter_matches_item_explicitly_shared_with_that_group(self) -> None:
        group = self._create_group("A Group")
        group.add_user(self.viewer)
        item = self._create_item("Drill", share_with_all_groups=False)
        item.shared_with_groups.add(group)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"groups": group.pk})

        self.assertContains(response, "Drill")

    def test_filter_excludes_item_shared_with_a_different_group(self) -> None:
        group_a = self._create_group("Group A")
        group_b = self._create_group("Group B")
        group_a.add_user(self.viewer)
        group_b.add_user(self.viewer)
        item = self._create_item("Drill", share_with_all_groups=False)
        item.shared_with_groups.add(group_b)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"groups": group_a.pk})

        self.assertNotContains(response, "Drill")

    def test_filter_excludes_item_when_owner_left_the_shared_group(self) -> None:
        """Regression: an owner leaving group A doesn't retract the item's
        stale shared_with_groups(A) entry, and the item stays guardian-
        visible to the viewer through group B's still-active sharing -- so
        excluding it from an A-only filter has to come from
        filter_by_groups's own owner-membership check, not from the
        earlier guardian-permission filtering (which group B satisfies
        regardless)."""
        group_a = self._create_group("Group A")
        group_b = self._create_group("Group B")
        group_a.add_user(self.viewer)
        group_b.add_user(self.viewer)
        item = self._create_item("Drill", share_with_all_groups=False)
        item.shared_with_groups.add(group_a, group_b)
        group_a.remove_user(self.owner, bypass_last_moderator_check=True)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"groups": group_a.pk})

        self.assertNotContains(response, "Drill")

    def test_filter_by_multiple_groups_is_or_matched(self) -> None:
        group_a = self._create_group("Group A")
        group_b = self._create_group("Group B")
        group_a.add_user(self.viewer)
        group_b.add_user(self.viewer)
        item_a = self._create_item("OnlyA", share_with_all_groups=False)
        item_a.shared_with_groups.add(group_a)
        item_b = self._create_item("OnlyB", share_with_all_groups=False)
        item_b.shared_with_groups.add(group_b)

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("item-list"), {"groups": [group_a.pk, group_b.pk]}
        )

        self.assertContains(response, "OnlyA")
        self.assertContains(response, "OnlyB")

    def test_group_not_in_viewers_choices_yields_no_results(self) -> None:
        """django-filter's FilterView is strict: a group id outside the
        bound ModelMultipleChoiceFilter's queryset (the viewer's own active
        groups) makes the whole filter form invalid, which empties the
        results rather than silently ignoring the bad value -- the same
        behavior the existing categories filter already relies on."""
        own_group = self._create_group("Own Group")
        own_group.add_user(self.viewer)
        other_group = self._create_group("Group the viewer isn't in")
        self._create_item("Drill", share_with_all_groups=True)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"groups": other_group.pk})

        self.assertNotContains(response, "Drill")

    def test_group_filter_control_hidden_for_a_groupless_user(self) -> None:
        """ "Filter by group" also appears as literal JS inside the always-
        present Alpine x-data (the groupButtonText getter), so assert on
        the gated trigger markup itself rather than that text."""
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("item-list"))

        self.assertNotContains(response, "showModal('group-filter-modal')")

    def test_group_filter_control_shown_for_a_user_with_groups(self) -> None:
        group = self._create_group("A Group")
        group.add_user(self.viewer)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"))

        self.assertContains(response, "showModal('group-filter-modal')")
