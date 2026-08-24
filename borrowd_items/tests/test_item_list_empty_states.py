from urllib.parse import quote

from django.test import TestCase
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item
from borrowd_users.models import BorrowdUser


class ItemListEmptyStateTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create(
            username="searcher", email="searcher@example.com"
        )
        self.client.force_login(self.user)

    def test_zero_result_search_with_groups_shows_community_request_cta(
        self,
    ) -> None:
        """
        A search that returns no items, made by a user who belongs to an
        active group, should surface a Community Request CTA linking to the
        create view with the search term prefilled.
        """
        BorrowdGroup.objects.create_group(
            name="Searcher's Group",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("item-list"), {"search": "Cordless drill"})

        self.assertContains(
            response,
            "We couldn't find any Cordless drill. Would you like to make a "
            "community request?",
        )
        expected_link = (
            f"{reverse('community-request-create')}?item_name={quote('Cordless drill')}"
        )
        self.assertContains(response, expected_link)
        self.assertContains(response, "Request item")

    def test_zero_result_search_with_groups_url_encodes_special_characters(
        self,
    ) -> None:
        """
        The Community Request CTA link should URL-encode special characters
        and spaces in the search term.
        """
        BorrowdGroup.objects.create_group(
            name="Searcher's Group",
            created_by=self.user,
            updated_by=self.user,
        )
        search_term = "drill & saw?"

        response = self.client.get(reverse("item-list"), {"search": search_term})

        expected_link = (
            f"{reverse('community-request-create')}?item_name={quote(search_term)}"
        )
        self.assertContains(response, expected_link)

    def test_zero_result_search_without_groups_shows_generic_message_only(
        self,
    ) -> None:
        """
        A search that returns no items, made by a user with no active group
        memberships, should show a plain empty-state message with no
        Community Request CTA.
        """
        response = self.client.get(reverse("item-list"), {"search": "Cordless drill"})

        self.assertContains(response, "We couldn't find any Cordless drill.")
        self.assertNotContains(response, "community request")
        self.assertNotContains(response, "Request item")
        self.assertNotContains(response, reverse("community-request-create"))

    def test_no_search_and_no_items_shows_add_item_empty_state(self) -> None:
        """
        Regression test: a user with zero owned items and no group access
        should see the "Add an item to start sharing!" empty state, and the
        CTA button to add an item. This exercises the `user_has_items`
        boolean fix -- previously this branch was unreachable because
        `user_has_items` was always a truthy bound method.
        """
        response = self.client.get(reverse("item-list"))

        self.assertContains(response, "Add an item to start sharing!")
        self.assertContains(response, reverse("item-create"))

    def test_no_search_with_items_and_no_groups_shows_create_group_empty_state(
        self,
    ) -> None:
        """
        Regression test: a user who owns items but has no active group
        memberships should see the "create a group" empty state.
        """
        Item.objects.create(
            name="Owned Item",
            description="Owned by the searcher.",
            owner=self.user,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("item-list"))

        self.assertContains(
            response,
            "No items to borrow yet. Create a group and invite people you trust "
            "to start borrowing and lending.",
        )
        self.assertContains(response, reverse("borrowd_groups:group-create"))

    def test_no_search_with_items_and_groups_but_empty_inventory_shows_grow_message(
        self,
    ) -> None:
        """
        Regression test: a user who owns items and belongs to an active
        group, but whose group has no other items to show, should see the
        "grow your shared inventory" empty state with no CTA.
        """
        Item.objects.create(
            name="Owned Item",
            description="Owned by the searcher.",
            owner=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        BorrowdGroup.objects.create_group(
            name="Searcher's Group",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("item-list"))

        self.assertContains(
            response,
            "To grow your shared inventory, show your friends how easy it is "
            "to add items on Borrow'd!",
        )
