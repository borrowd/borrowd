"""
Tests for item card helper functions.

Covers:
- build_card_ids: Card ID generation
- get_banner_info_for_item: Banner type determination
- build_item_card_context: Full context building
"""

from datetime import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from borrowd.models import TrustLevel
from borrowd_items.card_helpers import (
    build_card_ids,
    build_item_card_context,
    get_banner_info_for_item,
)
from borrowd_items.models import (
    Item,
    ItemCategory,
    ItemStatus,
    ListingType,
    Transaction,
    TransactionStatus,
)
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
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
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


class ReturnFlowBannerTests(TestCase):
    """Tests for return-request and dispute banner info."""

    lender: BorrowdUser
    borrower: BorrowdUser
    other_user: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a lender, borrower, and an uninvolved viewer."""
        cls.lender = BorrowdUser.objects.create(
            username="banner_lender",
            email="banner_lender@example.com",
            first_name="lena",
            last_name="lender",
        )
        cls.borrower = BorrowdUser.objects.create(
            username="banner_borrower",
            email="banner_borrower@example.com",
            first_name="bo",
            last_name="borrower",
        )
        cls.other_user = BorrowdUser.objects.create(
            username="banner_other",
            email="banner_other@example.com",
        )

    def setUp(self) -> None:
        """Create a borrowed item owned by the lender."""
        self.item = Item.objects.create(
            name="Banner Item",
            description="Test description",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
            status=ItemStatus.BORROWED,
        )

    def _create_transaction(
        self,
        status: TransactionStatus,
        return_requested_at: datetime | None = None,
        dispute_raised_by: BorrowdUser | None = None,
    ) -> Transaction:
        return Transaction.objects.create(
            item=self.item,
            party1=self.lender,
            party2=self.borrower,
            status=status,
            return_requested_at=return_requested_at,
            dispute_raised_by=dispute_raised_by,
            created_by=self.borrower,
            updated_by=self.lender,
        )

    def test_return_requested_owner_sees_you(self) -> None:
        """Owner sees the return-requested banner attributed to themselves."""
        self._create_transaction(
            TransactionStatus.RETURN_REQUESTED, return_requested_at=timezone.now()
        )
        info = get_banner_info_for_item(self.item, self.lender)
        self.assertEqual(
            info, {"banner_type": "return_requested", "person_name": "you"}
        )

    def test_return_requested_borrower_sees_lender_name(self) -> None:
        """Borrower sees the return-requested banner with the lender's name."""
        self._create_transaction(
            TransactionStatus.RETURN_REQUESTED, return_requested_at=timezone.now()
        )
        info = get_banner_info_for_item(self.item, self.borrower)
        self.assertEqual(
            info, {"banner_type": "return_requested", "person_name": "Lena"}
        )

    def test_return_requested_other_user_sees_borrowed(self) -> None:
        """Uninvolved viewers get the generic borrowed banner."""
        self._create_transaction(
            TransactionStatus.RETURN_REQUESTED, return_requested_at=timezone.now()
        )
        info = get_banner_info_for_item(self.item, self.other_user)
        self.assertEqual(info, {"banner_type": "borrowed"})

    def test_return_asserted_after_request_keeps_banner(self) -> None:
        """Banner stays up while the borrower's assertion awaits the lender."""
        self._create_transaction(
            TransactionStatus.RETURN_ASSERTED, return_requested_at=timezone.now()
        )
        info = get_banner_info_for_item(self.item, self.lender)
        self.assertEqual(
            info, {"banner_type": "return_requested", "person_name": "you"}
        )

    def test_return_asserted_without_request_shows_borrowed(self) -> None:
        """The legacy no-request return flow keeps the borrowed banner."""
        self._create_transaction(TransactionStatus.RETURN_ASSERTED)
        info = get_banner_info_for_item(self.item, self.lender)
        self.assertEqual(info["banner_type"], "borrowed")

    def test_disputed_parties_see_disputed(self) -> None:
        """Both parties see the disputed banner."""
        self._create_transaction(
            TransactionStatus.DISPUTED, dispute_raised_by=self.borrower
        )
        for viewer in (self.lender, self.borrower):
            info = get_banner_info_for_item(self.item, viewer)
            self.assertEqual(info, {"banner_type": "disputed"})

    def test_disputed_other_user_sees_borrowed(self) -> None:
        """Uninvolved viewers don't learn about the dispute."""
        self._create_transaction(
            TransactionStatus.DISPUTED, dispute_raised_by=self.borrower
        )
        info = get_banner_info_for_item(self.item, self.other_user)
        self.assertEqual(info, {"banner_type": "borrowed"})


class GiveawayBannerTests(TestCase):
    """Tests for giveaway listing and giveaway-request banner info."""

    giver: BorrowdUser
    requester: BorrowdUser
    other_user: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a giver, requester, and an uninvolved viewer."""
        cls.giver = BorrowdUser.objects.create(
            username="gift_giver",
            email="gift_giver@example.com",
            first_name="gia",
            last_name="giver",
        )
        cls.requester = BorrowdUser.objects.create(
            username="gift_requester",
            email="gift_requester@example.com",
            first_name="rita",
            last_name="requester",
        )
        cls.other_user = BorrowdUser.objects.create(
            username="gift_other",
            email="gift_other@example.com",
        )

    def setUp(self) -> None:
        """Create an available giveaway listing owned by the giver."""
        self.item = Item.objects.create(
            name="Giveaway Item",
            description="Test description",
            owner=self.giver,
            created_by=self.giver,
            updated_by=self.giver,
            listing_type=ListingType.GIVEAWAY,
        )

    def _create_giveaway_request(self) -> Transaction:
        self.item.status = ItemStatus.REQUESTED
        self.item.save()
        return Transaction.objects.create(
            item=self.item,
            party1=self.giver,
            party2=self.requester,
            status=TransactionStatus.GIVEAWAY_REQUESTED,
            created_by=self.requester,
            updated_by=self.requester,
        )

    def test_unrequested_giveaway_advertises_itself(self) -> None:
        """Without an active transaction, everyone sees the listing banner."""
        for viewer in (self.giver, self.requester, self.other_user):
            info = get_banner_info_for_item(self.item, viewer)
            self.assertEqual(info, {"banner_type": "giveaway_listing"})

    def test_requested_giveaway_owner_sees_requester(self) -> None:
        """Owner sees who's asking, with a link to their profile."""
        self._create_giveaway_request()
        info = get_banner_info_for_item(self.item, self.giver)
        self.assertEqual(
            info,
            {
                "banner_type": "giveaway_requested",
                "person_name": "Rita",
                "person_url": reverse("public-profile", args=[self.requester.pk]),
            },
        )

    def test_requested_giveaway_requester_sees_pending_request(self) -> None:
        """Requester sees their request is pending, without their own name."""
        self._create_giveaway_request()
        info = get_banner_info_for_item(self.item, self.requester)
        self.assertEqual(info, {"banner_type": "giveaway_requested"})

    def test_requested_giveaway_other_user_sees_pending(self) -> None:
        """Uninvolved viewers don't learn who requested the giveaway."""
        self._create_giveaway_request()
        info = get_banner_info_for_item(self.item, self.other_user)
        self.assertEqual(info, {"banner_type": "pending"})
