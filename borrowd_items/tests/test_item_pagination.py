"""
Tests for item list pagination.
"""

from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


class ItemListPaginationTests(TestCase):
    """Tests for item list view pagination."""

    def setUp(self) -> None:
        """Create test data for each test."""
        self.owner = BorrowdUser.objects.create(
            username="owner",
            email="owner@example.com",
        )
        self.viewer = BorrowdUser.objects.create(
            username="viewer",
            email="viewer@example.com",
        )
        self.category = ItemCategory.objects.create(name="Test Category")

        # Create a group with both users
        self.group = BorrowdGroup.objects.create(
            name="Test Group",
            description="Test group",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )

        # Add viewer to the group (owner is added automatically by signal)
        self.group.add_user(self.viewer, trust_level=TrustLevel.STANDARD)

    def create_item(self, name: str, description: str) -> Item:
        """Helper to create an item with required audit fields."""
        item = Item.objects.create(
            name=name,
            description=description,
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )
        item.categories.add(self.category)
        return item

    def test_pagination_shows_6_items_per_page(self) -> None:
        """First page shows 6 items."""
        # Create 8 items
        for i in range(8):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 6)
        self.assertTrue(response.context["page_obj"].has_next())
        self.assertFalse(response.context["page_obj"].has_previous())

    def test_pagination_second_page(self) -> None:
        """Second page shows remaining items."""

        for i in range(8):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"page": "2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 2)
        self.assertFalse(response.context["page_obj"].has_next())
        self.assertTrue(response.context["page_obj"].has_previous())

    def test_pagination_preserves_search_params(self) -> None:
        """Pagination preserves search query parameters."""

        for i in range(8):
            self.create_item(name=f"Test Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("item-list"), {"search": "Test", "page": "1"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 6)

        self.assertIn("page_obj", response.context)

    def test_no_pagination_when_6_or_fewer_items(self) -> None:
        """No pagination shown when 6 or fewer items."""

        for i in range(3):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 3)
        # Only 1 page, so no pagination controls shown
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 1)
