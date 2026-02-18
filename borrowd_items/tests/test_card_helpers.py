"""
Tests for item card helper functions.

Covers:
- build_card_ids: Card ID generation
- get_banner_info_for_item: Banner type determination
- build_item_card_context: Full context building
"""

from django.test import TestCase

from borrowd.models import TrustLevel
from borrowd_items.card_helpers import build_card_ids, build_item_card_context
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


class BuildCardIdsTests(TestCase):
    """Tests for build_card_ids function."""

    def test_generates_all_required_ids(self) -> None:
        """Returns dict with all required ID keys."""
        ids = build_card_ids("search", 123)

        self.assertIn("card_id", ids)
        self.assertIn("modal_suffix", ids)
        self.assertIn("actions_container_id", ids)
        self.assertIn("request_modal_id", ids)
        self.assertIn("accept_modal_id", ids)

    def test_card_id_format(self) -> None:
        """card_id follows expected format."""
        ids = build_card_ids("search", 123)
        self.assertEqual(ids["card_id"], "item-card-search-123")

    def test_modal_suffix_format(self) -> None:
        """modal_suffix follows expected format."""
        ids = build_card_ids("search", 123)
        self.assertEqual(ids["modal_suffix"], "-search-123")

    def test_actions_container_id_format(self) -> None:
        """actions_container_id follows expected format."""
        ids = build_card_ids("search", 123)
        self.assertEqual(ids["actions_container_id"], "item-card-actions-search-123")

    def test_request_modal_id_format(self) -> None:
        """request_modal_id follows expected format."""
        ids = build_card_ids("search", 123)
        self.assertEqual(ids["request_modal_id"], "request-item-modal-search-123")

    def test_accept_modal_id_format(self) -> None:
        """accept_modal_id follows expected format."""
        ids = build_card_ids("search", 123)
        self.assertEqual(ids["accept_modal_id"], "accept-request-modal-search-123")

    def test_hyphenated_context(self) -> None:
        """Handles hyphenated context correctly."""
        ids = build_card_ids("my-items", 456)
        self.assertEqual(ids["card_id"], "item-card-my-items-456")
        self.assertEqual(ids["modal_suffix"], "-my-items-456")


class BuildItemCardContextTests(TestCase):
    """Tests for build_item_card_context function."""

    owner: BorrowdUser
    viewer: BorrowdUser
    category: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        """Create shared test data."""
        cls.owner = BorrowdUser.objects.create(
            username="owner",
            email="owner@example.com",
        )
        cls.viewer = BorrowdUser.objects.create(
            username="viewer",
            email="viewer@example.com",
        )
        cls.category = ItemCategory.objects.create(
            name="Test Category",
            description="Test category description",
        )

    def create_item(self) -> Item:
        """Create a test item."""
        item = Item.objects.create(
            name="Test Item",
            description="Test description",
            owner=self.owner,
            trust_level_required=TrustLevel.LOW,
        )
        item.categories.add(self.category)
        return item

    def test_includes_item_data(self) -> None:
        """Context includes basic item data."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertEqual(ctx["item"], item)
        self.assertEqual(ctx["pk"], item.pk)
        self.assertEqual(ctx["name"], item.name)
        self.assertEqual(ctx["description"], item.description)

    def test_includes_context_string(self) -> None:
        """Context includes the card context string."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "my-items")

        self.assertEqual(ctx["context"], "my-items")

    def test_includes_card_ids(self) -> None:
        """Context includes all card IDs."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertIn("card_id", ctx)
        self.assertIn("modal_suffix", ctx)
        self.assertIn("actions_container_id", ctx)
        self.assertEqual(ctx["card_id"], f"item-card-search-{item.pk}")

    def test_includes_banner_info(self) -> None:
        """Context includes banner information."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertIn("banner_type", ctx)
        self.assertEqual(ctx["banner_type"], "available")

    def test_is_yours_true_for_owner(self) -> None:
        """is_yours is True when viewer is the owner."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.owner, "search")

        self.assertTrue(ctx["is_yours"])

    def test_is_yours_false_for_non_owner(self) -> None:
        """is_yours is False when viewer is not the owner."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertFalse(ctx["is_yours"])

    def test_show_actions_is_true(self) -> None:
        """show_actions is always True."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertTrue(ctx["show_actions"])

    def test_includes_error_message_when_provided(self) -> None:
        """Context includes error fields when provided."""
        item = self.create_item()

        ctx = build_item_card_context(
            item,
            self.viewer,
            "search",
            error_message="Test error",
            error_type="test_error",
        )

        self.assertEqual(ctx["error_message"], "Test error")
        self.assertEqual(ctx["error_type"], "test_error")

    def test_no_error_fields_when_not_provided(self) -> None:
        """Context excludes error fields when not provided."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertNotIn("error_message", ctx)
        self.assertNotIn("error_type", ctx)

    def test_computes_action_context_when_not_provided(self) -> None:
        """Computes action_context if not provided."""
        item = self.create_item()

        ctx = build_item_card_context(item, self.viewer, "search")

        self.assertIn("action_context", ctx)
        self.assertIsNotNone(ctx["action_context"])

    def test_uses_provided_action_context(self) -> None:
        """Uses provided action_context without recomputing."""
        item = self.create_item()
        action_context = item.get_action_context_for(self.viewer)

        ctx = build_item_card_context(
            item, self.viewer, "search", action_context=action_context
        )

        self.assertEqual(ctx["action_context"], action_context)
