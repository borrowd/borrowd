"""
Tests for item list pagination.
"""

from django.test import TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_items.views import (
    PAGE_SIZE_DESKTOP_DEFAULT,
    PAGE_SIZE_MAX,
    PAGE_SIZE_MIN,
    PAGE_SIZE_MOBILE_DEFAULT,
)
from borrowd_users.models import BorrowdUser

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


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

        self.group = BorrowdGroup.objects.create(
            name="Test Group",
            description="Test group",
            created_by=self.owner,
            updated_by=self.owner,
            trust_level=TrustLevel.STANDARD,
            membership_requires_approval=False,
        )
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

    # --- explicit page_size param ---

    def test_explicit_page_size_respected(self) -> None:
        """?page_size=6 returns exactly 6 items on the first page."""
        for i in range(8):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"page_size": "6"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 6)
        self.assertTrue(response.context["page_obj"].has_next())
        self.assertFalse(response.context["page_obj"].has_previous())

    def test_explicit_page_size_second_page(self) -> None:
        """Second page contains remaining items when page_size is explicit."""
        for i in range(8):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("item-list"), {"page_size": "6", "page": "2"}
        )

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
            reverse("item-list"), {"search": "Test", "page": "1", "page_size": "6"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 6)
        self.assertIn("page_obj", response.context)
        self.assertContains(response, "search=Test")
        self.assertContains(response, "page_size=6")
        self.assertContains(response, "page=2")

    def test_pagination_preserves_multi_value_category_params(self) -> None:
        """Pagination preserves multi-value category query parameters."""
        second_category = ItemCategory.objects.create(name="Second Category")
        for i in range(8):
            item = self.create_item(name=f"Item {i}", description=f"Description {i}")
            item.categories.add(second_category)

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("item-list"),
            {
                "categories": [str(self.category.pk), str(second_category.pk)],
                "page": "1",
                "page_size": "6",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 6)
        self.assertIn("page_obj", response.context)
        self.assertContains(response, f"categories={self.category.pk}")
        self.assertContains(response, f"categories={second_category.pk}")
        self.assertContains(response, "page_size=6")
        self.assertContains(response, "page=2")

    def test_no_pagination_when_few_items(self) -> None:
        """Single page when item count is below the page size."""
        for i in range(3):
            self.create_item(name=f"Item {i}", description=f"Description {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"page_size": "6"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), 3)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 1)

    # --- user-agent–based defaults ---

    def test_mobile_ua_uses_mobile_default(self) -> None:
        """Mobile user agent falls back to PAGE_SIZE_MOBILE_DEFAULT."""
        for i in range(PAGE_SIZE_MOBILE_DEFAULT + 1):
            self.create_item(name=f"Item {i}", description=f"Desc {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), HTTP_USER_AGENT=MOBILE_UA)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), PAGE_SIZE_MOBILE_DEFAULT)

    def test_desktop_ua_uses_desktop_default(self) -> None:
        """Desktop user agent falls back to PAGE_SIZE_DESKTOP_DEFAULT."""
        for i in range(PAGE_SIZE_DESKTOP_DEFAULT + 1):
            self.create_item(name=f"Item {i}", description=f"Desc {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), HTTP_USER_AGENT=DESKTOP_UA)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), PAGE_SIZE_DESKTOP_DEFAULT)

    # --- clamping ---

    def test_page_size_clamped_to_minimum(self) -> None:
        """?page_size below the minimum is clamped up."""
        for i in range(PAGE_SIZE_MIN + 2):
            self.create_item(name=f"Item {i}", description=f"Desc {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"page_size": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), PAGE_SIZE_MIN)

    def test_page_size_clamped_to_maximum(self) -> None:
        """?page_size above the maximum is clamped down."""
        for i in range(PAGE_SIZE_MAX + 5):
            self.create_item(name=f"Item {i}", description=f"Desc {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("item-list"), {"page_size": "9999"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), PAGE_SIZE_MAX)

    def test_invalid_page_size_falls_back_to_default(self) -> None:
        """Non-numeric ?page_size falls back to the UA-based default."""
        for i in range(PAGE_SIZE_DESKTOP_DEFAULT + 1):
            self.create_item(name=f"Item {i}", description=f"Desc {i}")

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("item-list"),
            {"page_size": "abc"},
            HTTP_USER_AGENT=DESKTOP_UA,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["item_cards"]), PAGE_SIZE_DESKTOP_DEFAULT)
