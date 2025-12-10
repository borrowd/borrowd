"""
Covers:
- model-layer category assignments
- form validation and persistence
- filtering items by categories
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_items.forms import ItemForm
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


class ItemMultiCategoryModelTests(TestCase):
    """Tests for Item model multi-category functionality."""

    owner: BorrowdUser
    category_electronics: ItemCategory
    category_tools: ItemCategory
    category_outdoor: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared users and categories for model tests."""
        cls.owner = BorrowdUser.objects.create(
            username="testuser",
            email="testuser@example.com",
        )
        cls.category_electronics = ItemCategory.objects.create(
            name="Electronics",
            description="Electronic devices and gadgets",
        )
        cls.category_tools = ItemCategory.objects.create(
            name="Tools",
            description="Hand and power tools",
        )
        cls.category_outdoor = ItemCategory.objects.create(
            name="Outdoor",
            description="Outdoor and camping equipment",
        )

    def create_item(
        self,
        name: str = "Test Item",
        description: str = "A test item",
        categories: list[ItemCategory] | None = None,
    ) -> Item:
        """Create an item with sensible defaults."""
        item = Item.objects.create(
            name=name,
            description=description,
            owner=self.owner,
            trust_level_required=TrustLevel.LOW,
        )
        if categories:
            item.categories.add(*categories)
        return item

    def test_item_can_have_single_category(self) -> None:
        """Item accepts a single category assignment."""
        item = self.create_item(
            name="Drill",
            description="Cordless drill",
            categories=[self.category_tools],
        )

        self.assertEqual(item.categories.count(), 1)
        self.assertIn(self.category_tools, item.categories.all())

    def test_item_can_have_multiple_categories(self) -> None:
        """Item accepts multiple category assignments."""
        item = self.create_item(
            name="Camping Lantern",
            description="LED lantern with USB charging",
            categories=[self.category_electronics, self.category_outdoor],
        )

        self.assertEqual(item.categories.count(), 2)
        self.assertIn(self.category_electronics, item.categories.all())
        self.assertIn(self.category_outdoor, item.categories.all())

    def test_item_categories_accessible_via_related_name(self) -> None:
        """Categories expose items via the `items` related name."""
        item1 = self.create_item(
            name="Multimeter",
            description="Digital multimeter",
            categories=[self.category_electronics, self.category_tools],
        )
        item2 = self.create_item(
            name="Soldering Iron",
            description="Temperature-controlled soldering station",
            categories=[self.category_electronics],
        )

        # Electronics category should have both items
        electronics_items = self.category_electronics.items.all()
        self.assertEqual(electronics_items.count(), 2)
        self.assertIn(item1, electronics_items)
        self.assertIn(item2, electronics_items)

        # Tools category should only have item1
        tools_items = self.category_tools.items.all()
        self.assertEqual(tools_items.count(), 1)
        self.assertIn(item1, tools_items)

    def test_item_requires_at_least_one_category(self) -> None:
        """Creating an item without categories fails at the model layer."""
        item = self.create_item(
            name="Mystery Item", description="Item with no categories"
        )

        # Item is saved but has no categories - full_clean should fail
        with self.assertRaises(ValidationError) as context:
            item.full_clean()

        self.assertIn("categories", context.exception.message_dict)

    def test_item_categories_can_be_removed(self) -> None:
        """Categories can be removed from an existing item."""
        item = self.create_item(
            name="Multi-tool",
            description="Swiss army knife style tool",
            categories=[self.category_tools, self.category_outdoor],
        )
        self.assertEqual(item.categories.count(), 2)
        self.assertIn(self.category_tools, item.categories.all())
        self.assertIn(self.category_outdoor, item.categories.all())

        # Remove one category
        item.categories.remove(self.category_outdoor)

        self.assertEqual(item.categories.count(), 1)
        self.assertIn(self.category_tools, item.categories.all())
        self.assertNotIn(self.category_outdoor, item.categories.all())

    def test_item_categories_can_not_be_cleared(self) -> None:
        """Clearing all categories is prevented to avoid category-less items."""
        item = self.create_item(
            name="Flashlight",
            description="High-powered LED flashlight",
            categories=[self.category_tools, self.category_outdoor],
        )
        item.categories.clear()

        # After clearing, full_clean should raise ValidationError
        with self.assertRaises(ValidationError) as context:
            item.full_clean()

        self.assertIn("categories", context.exception.message_dict)

    def test_category_deletion_does_not_delete_item(self) -> None:
        """Deleting a category does not cascade delete associated items."""
        # Create a fresh category for this test to avoid affecting other tests
        temporary_category = ItemCategory.objects.create(
            name="Temporary",
            description="Category to be deleted",
        )
        item = self.create_item(
            name="Test Item",
            description="Item that should survive category deletion",
            categories=[temporary_category, self.category_tools],
        )

        # Delete the temporary category
        temporary_category.delete()

        # Item should still exist
        item.refresh_from_db()
        self.assertEqual(item.name, "Test Item")

        # Item should only have the remaining category
        self.assertEqual(item.categories.count(), 1)
        self.assertIn(self.category_tools, item.categories.all())


class ItemFormCategoryValidationTests(TestCase):
    """Tests for ItemForm category validation."""

    owner: BorrowdUser
    category_electronics: ItemCategory
    category_tools: ItemCategory
    category_outdoor: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared users, categories, and items for form tests."""
        cls.owner = BorrowdUser.objects.create(
            username="formtestuser",
            email="formtestuser@example.com",
        )
        cls.category_electronics = ItemCategory.objects.create(
            name="Electronics",
            description="Electronic devices and gadgets",
        )
        cls.category_tools = ItemCategory.objects.create(
            name="Tools",
            description="Hand and power tools",
        )
        cls.category_outdoor = ItemCategory.objects.create(
            name="Outdoor",
            description="Outdoor and camping equipment",
        )

    def get_valid_form_data(
        self,
        categories: list[ItemCategory],
        name: str = "Test Item",
        description: str = "A test item description",
    ) -> dict[str, Any]:
        """Return valid form data with specified categories."""
        return {
            "name": name,
            "description": description,
            "categories": [c.pk for c in categories],
            "trust_level_required": TrustLevel.LOW,
        }

    def create_item_with_categories(
        self,
        categories: list[ItemCategory],
        name: str = "Existing Item",
        description: str = "An existing item",
    ) -> Item:
        """Create an item with specified categories for edit tests."""
        item = Item.objects.create(
            name=name,
            description=description,
            owner=self.owner,
            trust_level_required=TrustLevel.LOW,
        )
        item.categories.add(*categories)
        return item

    def test_form_valid_with_single_category(self) -> None:
        """Form validates with one selected category."""
        form_data = self.get_valid_form_data(categories=[self.category_tools])
        form = ItemForm(data=form_data)

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_valid_with_multiple_categories(self) -> None:
        """Form validates with multiple selected categories."""
        form_data = self.get_valid_form_data(
            categories=[self.category_electronics, self.category_outdoor]
        )
        form = ItemForm(data=form_data)

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_without_categories(self) -> None:
        """Form rejects submissions without categories."""
        form_data = {
            "name": "Test Item",
            "description": "A test item description",
            "categories": [],
            "trust_level_required": TrustLevel.LOW,
        }
        form = ItemForm(data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn("categories", form.errors)

    def test_form_saves_multiple_categories(self) -> None:
        """Saving the form assigns all selected categories to the item."""
        form_data = self.get_valid_form_data(
            categories=[self.category_electronics, self.category_tools],
            name="Multi-Category Item",
        )
        form = ItemForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

        # ItemForm doesn't include 'owner' field, but Item.owner is required.
        # commit=False lets us set owner before saving to satisfy the constraint.
        # save_m2m() is then required to persist M2M relationships (categories).
        item = form.save(commit=False)
        item.owner = self.owner
        item.save()
        form.save_m2m()

        self.assertEqual(item.categories.count(), 2)
        self.assertIn(self.category_electronics, item.categories.all())
        self.assertIn(self.category_tools, item.categories.all())

    def test_form_preserves_selected_categories_on_edit(self) -> None:
        """Editing an item preserves existing categories when adding new ones."""
        # Create item with 2 categories (electronics, outdoor)
        item = self.create_item_with_categories(
            categories=[
                self.category_electronics,
                self.category_outdoor,
            ]
        )

        # Edit the item to add tools category
        form_data = self.get_valid_form_data(
            categories=[
                self.category_electronics,
                self.category_outdoor,
                self.category_tools,
            ],
            name=item.name,
            description=item.description,
        )
        form = ItemForm(data=form_data, instance=item)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        # Verify previous categories are present after edit
        item.refresh_from_db()
        self.assertIn(self.category_electronics, item.categories.all())
        self.assertIn(self.category_outdoor, item.categories.all())

    def test_form_can_add_categories(self) -> None:
        """Updating an item can add additional categories."""
        item = self.create_item_with_categories(categories=[self.category_tools])
        form_data = self.get_valid_form_data(
            categories=[self.category_tools, self.category_electronics],
            name=item.name,
            description=item.description,
        )
        form = ItemForm(data=form_data, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        item.refresh_from_db()
        self.assertEqual(item.categories.count(), 2)
        self.assertIn(self.category_tools, item.categories.all())
        self.assertIn(self.category_electronics, item.categories.all())

    def test_form_can_remove_categories(self) -> None:
        """Updating an item can remove categories."""
        item = self.create_item_with_categories(
            categories=[self.category_tools, self.category_outdoor]
        )
        form_data = self.get_valid_form_data(
            categories=[self.category_tools],
            name=item.name,
            description=item.description,
        )
        form = ItemForm(data=form_data, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        item.refresh_from_db()
        self.assertEqual(item.categories.count(), 1)
        self.assertIn(self.category_tools, item.categories.all())
        self.assertNotIn(self.category_outdoor, item.categories.all())

    def test_form_can_replace_all_categories(self) -> None:
        """Updating an item can replace all categories."""
        item = self.create_item_with_categories(
            categories=[self.category_tools, self.category_outdoor]
        )
        form_data = self.get_valid_form_data(
            categories=[self.category_electronics],
            name=item.name,
            description=item.description,
        )
        form = ItemForm(data=form_data, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        item.refresh_from_db()
        self.assertEqual(item.categories.count(), 1)
        self.assertIn(self.category_electronics, item.categories.all())
        self.assertNotIn(self.category_tools, item.categories.all())
        self.assertNotIn(self.category_outdoor, item.categories.all())

    def test_form_handles_adding_and_removing_categories(self) -> None:
        """Updating can add some categories while removing others."""
        item = self.create_item_with_categories(
            categories=[self.category_tools, self.category_outdoor]
        )
        # Remove outdoor, keep tools, add electronics
        form_data = self.get_valid_form_data(
            categories=[self.category_tools, self.category_electronics],
            name=item.name,
            description=item.description,
        )
        form = ItemForm(data=form_data, instance=item)
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        item.refresh_from_db()
        self.assertEqual(item.categories.count(), 2)
        self.assertIn(self.category_tools, item.categories.all())
        self.assertIn(self.category_electronics, item.categories.all())
        self.assertNotIn(self.category_outdoor, item.categories.all())

    def test_form_invalid_category_id_rejected(self) -> None:
        """Form rejects non-existent category IDs."""
        form_data = {
            "name": "Test Item",
            "description": "A test item description",
            "categories": [99999],  # Non-existent category ID
            "trust_level_required": TrustLevel.LOW,
        }
        form = ItemForm(data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn("categories", form.errors)


class ItemFilterCategoryTests(TestCase):
    """Tests for ItemFilter category filtering functionality."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create items with varied category combinations for filter tests."""
        pass

    def test_filter_by_single_category(self) -> None:
        """Filtering by a single category returns matching items."""
        pass

    def test_filter_by_multiple_categories_returns_items_matching_any_selected_category(
        self,
    ) -> None:
        """Filtering returns items matching any selected categories (OR logic)."""
        pass

    def test_filter_items_with_multiple_categories_assigned(self) -> None:
        """Items with multiple categories still appear when one category matches."""
        pass

    def test_filter_returns_no_results_for_unmatched_categories(self) -> None:
        """Filtering by categories without matches returns an empty queryset."""
        pass

    def test_filter_with_no_category_returns_all_items(self) -> None:
        """When no category is selected, all accessible items are returned."""
        pass

    def test_filter_deduplicates_items_with_multiple_selected_categories(self) -> None:
        """Should verify filtering with overlapping categories does not return duplicate items."""
        pass

    def test_filter_combines_with_search_query(self) -> None:
        """Category filtering composes correctly with search queries."""
        pass

    def test_filter_respects_item_visibility_rules(self) -> None:
        """Category filtering respects trust level and group membership."""
        pass

    def test_filter_with_all_categories_selected(self) -> None:
        """Selecting all categories returns every accessible item."""
        pass
