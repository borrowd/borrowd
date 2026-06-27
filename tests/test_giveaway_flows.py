from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from guardian.shortcuts import get_perms

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemAction,
    ItemStatus,
    Transaction,
    TransactionStatus,
)
from borrowd_items.views import borrow_item
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser


class GiveawayFlowTestBase(SimpleTestCase):
    """
    Shared fixtures for the active-loan giveaway flow. Mirrors
    ReturnFlowTestBase in test_return_flows.py: ordered steps within a class,
    SimpleTestCase with database access re-enabled.
    """

    lender: BorrowdUser
    borrower: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    databases = "__all__"

    @classmethod
    def create_loan_fixtures(cls, prefix: str) -> None:
        cls.lender = BorrowdUser.objects.create(
            username=f"{prefix}_lender", email=f"{prefix}_lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username=f"{prefix}_borrower", email=f"{prefix}_borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create_group(
            name=f"{prefix} Test Group",
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.borrower, trust_level=TrustLevel.HIGH)
        cls.item = Item.objects.create(
            name=f"{prefix} Test Item",
            description="Test Description",
            owner=cls.lender,
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level_required=TrustLevel.STANDARD,
        )
        cls.factory = RequestFactory()

    @classmethod
    def advance_to_collected(cls) -> None:
        cls.item.process_action(user=cls.borrower, action=ItemAction.REQUEST_ITEM)
        cls.item.process_action(user=cls.lender, action=ItemAction.ACCEPT_REQUEST)
        cls.item.process_action(user=cls.borrower, action=ItemAction.MARK_COLLECTED)
        cls.item.process_action(user=cls.lender, action=ItemAction.CONFIRM_COLLECTED)

    @classmethod
    def tearDownClass(cls) -> None:
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.lender.delete()
        cls.borrower.delete()
        super().tearDownClass()

    def post_action(self, user: BorrowdUser, action: ItemAction) -> None:
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": action},
        )
        request.user = user
        response = borrow_item(request, pk=self.item.pk)
        self.assertEqual(response.status_code, 302)

    def current_tx(self) -> Transaction:
        tx = self.item.transactions.order_by("-created_at").first()
        if tx is None:
            self.fail("Should have a Transaction")
        return tx


class GiveawayHappyFlowTest(GiveawayFlowTestBase):
    """
    COLLECTED -> lender offers giveaway -> GIVEAWAY_OFFERED -> borrower
    accepts -> OWNERSHIP_TRANSFERRED, ownership reassigned to the borrower.
    """

    watcher: BorrowdUser
    subscription: AvailabilitySubscription

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("give_happy")
        cls.advance_to_collected()
        # A third user is waiting for this item to free up.
        cls.watcher = BorrowdUser.objects.create(
            username="give_happy_watcher", email="give_happy_watcher@example.com"
        )
        cls.subscription = AvailabilitySubscription.objects.create(
            user=cls.watcher,
            item=cls.item,
            status=AvailabilitySubscriptionStatus.ACTIVE,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.subscription.delete()
        cls.watcher.delete()
        super().tearDownClass()

    def test_010_actions_at_collected(self) -> None:
        """Only the lender can offer a giveaway; the borrower cannot."""
        self.assertEqual(
            self.item.get_actions_for(self.lender),
            (
                ItemAction.MARK_RETURNED,
                ItemAction.REQUEST_RETURN,
                ItemAction.OFFER_GIVEAWAY,
            ),
        )
        self.assertNotIn(
            ItemAction.OFFER_GIVEAWAY, self.item.get_actions_for(self.borrower)
        )

    def test_020_lender_offers_giveaway(self) -> None:
        """Offer moves the transaction to GIVEAWAY_OFFERED; item still BORROWED."""
        self.post_action(self.lender, ItemAction.OFFER_GIVEAWAY)
        self.assertEqual(self.current_tx().status, TransactionStatus.GIVEAWAY_OFFERED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BORROWED)

    def test_030_actions_at_giveaway_offered(self) -> None:
        """Borrower can accept or decline; lender waits."""
        self.assertEqual(
            self.item.get_actions_for(self.borrower),
            (ItemAction.ACCEPT_GIVEAWAY, ItemAction.DECLINE_GIVEAWAY),
        )
        self.assertEqual(self.item.get_actions_for(self.lender), tuple())

    def test_040_borrower_accepts_gift(self) -> None:
        """Acceptance transfers ownership and frees the item."""
        self.post_action(self.borrower, ItemAction.ACCEPT_GIVEAWAY)
        self.assertEqual(
            self.current_tx().status, TransactionStatus.OWNERSHIP_TRANSFERRED
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.owner, self.borrower)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)

    def test_050_permissions_handed_off(self) -> None:
        """New owner gains owner perms; old owner loses edit/delete.

        The lender keeps VIEW via the shared group (the item is still visible
        to the community), but no longer controls it.
        """
        self.assertEqual(
            set(get_perms(self.borrower, self.item)),
            {ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE},
        )
        lender_perms = get_perms(self.lender, self.item)
        self.assertNotIn(ItemOLP.EDIT, lender_perms)
        self.assertNotIn(ItemOLP.DELETE, lender_perms)

    def test_060_inventory_moves(self) -> None:
        """Item leaves the lender's lends and is now owned by the borrower."""
        self.assertFalse(Transaction.get_active_lends_for_user(self.lender).exists())
        self.assertFalse(
            Transaction.get_active_borrows_for_user(self.borrower).exists()
        )
        self.assertTrue(
            Item.objects.filter(pk=self.item.pk, owner=self.borrower).exists()
        )

    def test_070_subscription_cancelled(self) -> None:
        """Stale availability subscriptions are cancelled on transfer."""
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.CANCELLED
        )


class GiveawayDeclineFlowTest(GiveawayFlowTestBase):
    """
    COLLECTED -> lender offers -> borrower declines -> back to COLLECTED with
    the lender's return/giveaway options restored.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("give_decline")
        cls.advance_to_collected()
        cls.item.process_action(user=cls.lender, action=ItemAction.OFFER_GIVEAWAY)

    def test_010_borrower_declines(self) -> None:
        """Decline reverts the transaction to COLLECTED; ownership unchanged."""
        self.post_action(self.borrower, ItemAction.DECLINE_GIVEAWAY)
        self.assertEqual(self.current_tx().status, TransactionStatus.COLLECTED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.owner, self.lender)
        self.assertEqual(self.item.status, ItemStatus.BORROWED)

    def test_020_lender_options_restored(self) -> None:
        """After a decline the lender can request return or offer again."""
        self.assertIn(ItemAction.OFFER_GIVEAWAY, self.item.get_actions_for(self.lender))
        self.assertIn(ItemAction.REQUEST_RETURN, self.item.get_actions_for(self.lender))


class GiveawayGuardsTest(GiveawayFlowTestBase):
    """Guards: who may offer/accept, and from which states."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("give_guards")
        cls.advance_to_collected()

    def test_010_borrower_cannot_offer(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(
                user=self.borrower, action=ItemAction.OFFER_GIVEAWAY
            )

    def test_020_cannot_offer_once_return_requested(self) -> None:
        """Give away must disappear once a return has been requested."""
        self.item.process_action(user=self.lender, action=ItemAction.REQUEST_RETURN)
        self.assertNotIn(
            ItemAction.OFFER_GIVEAWAY, self.item.get_actions_for(self.lender)
        )
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(user=self.lender, action=ItemAction.OFFER_GIVEAWAY)


class GiveawayOwnerCannotAcceptTest(GiveawayFlowTestBase):
    """The lender who offered cannot accept on the borrower's behalf."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("give_owner_accept")
        cls.advance_to_collected()
        cls.item.process_action(user=cls.lender, action=ItemAction.OFFER_GIVEAWAY)

    def test_010_owner_has_no_actions(self) -> None:
        self.assertEqual(self.item.get_actions_for(self.lender), tuple())

    def test_020_owner_accept_is_refused(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(
                user=self.lender, action=ItemAction.ACCEPT_GIVEAWAY
            )
