from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from guardian.shortcuts import get_perms

from borrowd_groups.models import BorrowdGroup
from borrowd_items.exceptions import InvalidItemAction, ItemAlreadyRequested
from borrowd_items.models import (
    AvailabilitySubscription,
    AvailabilitySubscriptionStatus,
    Item,
    ItemAction,
    ItemStatus,
    ListingType,
    Transaction,
    TransactionStatus,
)
from borrowd_items.views import borrow_item
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser


class GiveawayRequestFlowTestBase(SimpleTestCase):
    """
    Shared fixtures for the community giveaway-listing flow. Mirrors
    GiveawayFlowTestBase in test_giveaway_flows.py: ordered steps within a
    class, SimpleTestCase with database access re-enabled.
    """

    owner: BorrowdUser
    requester: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    databases = "__all__"

    @classmethod
    def create_giveaway_fixtures(cls, prefix: str) -> None:
        cls.owner = BorrowdUser.objects.create(
            username=f"{prefix}_owner",
            email=f"{prefix}_owner@example.com",
            first_name="Sofia",
        )
        cls.requester = BorrowdUser.objects.create(
            username=f"{prefix}_requester",
            email=f"{prefix}_requester@example.com",
            first_name="Marcus",
        )
        cls.group = BorrowdGroup.objects.create_group(
            name=f"{prefix} Test Group",
            created_by=cls.owner,
            updated_by=cls.owner,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.requester)
        cls.item = Item.objects.create(
            name=f"{prefix} Test Item",
            description="Test Description",
            owner=cls.owner,
            created_by=cls.owner,
            updated_by=cls.owner,
            listing_type=ListingType.GIVEAWAY,
        )
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls) -> None:
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.owner.delete()
        cls.requester.delete()
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


class GiveawayRequestHappyFlowTest(GiveawayRequestFlowTestBase):
    """
    Giveaway listing -> member requests the gift -> GIVEAWAY_REQUESTED ->
    owner approves -> OWNERSHIP_TRANSFERRED, ownership reassigned.
    """

    watcher: BorrowdUser
    subscription: AvailabilitySubscription

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_giveaway_fixtures("gwreq_happy")
        # A third user is waiting for this item to free up.
        cls.watcher = BorrowdUser.objects.create(
            username="gwreq_happy_watcher", email="gwreq_happy_watcher@example.com"
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

    def test_010_actions_on_giveaway_listing(self) -> None:
        """Members may request the gift, not a borrow; the owner has no action."""
        self.assertEqual(
            self.item.get_actions_for(self.requester),
            (ItemAction.REQUEST_GIVEAWAY,),
        )
        self.assertEqual(self.item.get_actions_for(self.owner), tuple())

    def test_020_member_requests_gift(self) -> None:
        """The request opens a GIVEAWAY_REQUESTED transaction and holds the item."""
        self.post_action(self.requester, ItemAction.REQUEST_GIVEAWAY)
        self.assertEqual(self.current_tx().status, TransactionStatus.GIVEAWAY_REQUESTED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)
        self.assertEqual(self.item.owner, self.owner)

    def test_030_actions_at_giveaway_requested(self) -> None:
        """Owner decides; the requester can only cancel."""
        self.assertEqual(
            self.item.get_actions_for(self.owner),
            (
                ItemAction.DECLINE_GIVEAWAY_REQUEST,
                ItemAction.APPROVE_GIVEAWAY_REQUEST,
            ),
        )
        self.assertEqual(
            self.item.get_actions_for(self.requester),
            (ItemAction.CANCEL_REQUEST,),
        )

    def test_040_shows_as_pending_request_not_active_loan(self) -> None:
        """The open request surfaces with borrow requests, not active lends."""
        tx = self.current_tx()
        self.assertIn(
            tx,
            Transaction.get_requested_status_transactions_for_user(self.owner),
        )
        self.assertIn(
            tx,
            Transaction.get_requested_status_transactions_for_user(self.requester),
        )
        self.assertFalse(Transaction.get_active_lends_for_user(self.owner).exists())
        self.assertFalse(
            Transaction.get_active_borrows_for_user(self.requester).exists()
        )

    def test_050_owner_approves_request(self) -> None:
        """Approval transfers ownership and relists the item as a plain lend."""
        self.post_action(self.owner, ItemAction.APPROVE_GIVEAWAY_REQUEST)
        self.assertEqual(
            self.current_tx().status, TransactionStatus.OWNERSHIP_TRANSFERRED
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.owner, self.requester)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)
        self.assertEqual(self.item.listing_type, ListingType.LEND)

    def test_060_permissions_handed_off(self) -> None:
        """New owner gains owner perms; old owner loses edit/delete."""
        self.assertEqual(
            set(get_perms(self.requester, self.item)),
            {ItemOLP.VIEW, ItemOLP.EDIT, ItemOLP.DELETE},
        )
        owner_perms = get_perms(self.owner, self.item)
        self.assertNotIn(ItemOLP.EDIT, owner_perms)
        self.assertNotIn(ItemOLP.DELETE, owner_perms)

    def test_070_subscription_cancelled(self) -> None:
        """Stale availability subscriptions are cancelled on transfer."""
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, AvailabilitySubscriptionStatus.CANCELLED
        )


class GiveawayRequestDeclineFlowTest(GiveawayRequestFlowTestBase):
    """
    Owner declines a giveaway request -> transaction REJECTED and the listing
    reopens for other members.
    """

    second_requester: BorrowdUser

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_giveaway_fixtures("gwreq_decline")
        cls.second_requester = BorrowdUser.objects.create(
            username="gwreq_decline_second", email="gwreq_decline_second@example.com"
        )
        cls.group.add_user(cls.second_requester)
        cls.item.process_action(user=cls.requester, action=ItemAction.REQUEST_GIVEAWAY)

    @classmethod
    def tearDownClass(cls) -> None:
        # The base teardown clears the item's transactions first; the second
        # requester's transaction protects them from deletion until then.
        super().tearDownClass()
        cls.second_requester.delete()

    def test_010_owner_declines(self) -> None:
        """Decline closes the transaction and reopens the listing."""
        self.post_action(self.owner, ItemAction.DECLINE_GIVEAWAY_REQUEST)
        self.assertEqual(self.current_tx().status, TransactionStatus.REJECTED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.owner, self.owner)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)
        self.assertEqual(self.item.listing_type, ListingType.GIVEAWAY)

    def test_020_listing_reopens_for_others(self) -> None:
        """Another member can request the reopened giveaway."""
        self.assertEqual(
            self.item.get_actions_for(self.second_requester),
            (ItemAction.REQUEST_GIVEAWAY,),
        )
        self.post_action(self.second_requester, ItemAction.REQUEST_GIVEAWAY)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.GIVEAWAY_REQUESTED)
        self.assertEqual(tx.party2, self.second_requester)


class GiveawayRequestCancelFlowTest(GiveawayRequestFlowTestBase):
    """The requester withdraws their own giveaway request."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_giveaway_fixtures("gwreq_cancel")
        cls.item.process_action(user=cls.requester, action=ItemAction.REQUEST_GIVEAWAY)

    def test_010_requester_cancels(self) -> None:
        """Cancel closes the transaction and reopens the listing."""
        self.post_action(self.requester, ItemAction.CANCEL_REQUEST)
        self.assertEqual(self.current_tx().status, TransactionStatus.CANCELLED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)
        self.assertEqual(self.item.listing_type, ListingType.GIVEAWAY)

    def test_020_requester_may_request_again(self) -> None:
        self.assertEqual(
            self.item.get_actions_for(self.requester),
            (ItemAction.REQUEST_GIVEAWAY,),
        )


class GiveawayRequestGuardsTest(GiveawayRequestFlowTestBase):
    """Guards: who may request/approve, and on which listing types."""

    second_requester: BorrowdUser
    lend_item: Item

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_giveaway_fixtures("gwreq_guards")
        cls.second_requester = BorrowdUser.objects.create(
            username="gwreq_guards_second", email="gwreq_guards_second@example.com"
        )
        cls.group.add_user(cls.second_requester)
        cls.lend_item = Item.objects.create(
            name="gwreq_guards Lend Item",
            description="Test Description",
            owner=cls.owner,
            created_by=cls.owner,
            updated_by=cls.owner,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.lend_item.delete()
        cls.second_requester.delete()
        super().tearDownClass()

    def test_010_owner_cannot_request_own_giveaway(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(
                user=self.owner, action=ItemAction.REQUEST_GIVEAWAY
            )

    def test_020_cannot_borrow_a_giveaway_listing(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(
                user=self.requester, action=ItemAction.REQUEST_ITEM
            )

    def test_030_cannot_request_gift_on_lend_listing(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.lend_item.process_action(
                user=self.requester, action=ItemAction.REQUEST_GIVEAWAY
            )

    def test_040_second_request_blocked_while_pending(self) -> None:
        self.item.process_action(
            user=self.requester, action=ItemAction.REQUEST_GIVEAWAY
        )
        with self.assertRaises(ItemAlreadyRequested):
            self.item.process_action(
                user=self.second_requester, action=ItemAction.REQUEST_GIVEAWAY
            )

    def test_050_requester_cannot_approve_own_request(self) -> None:
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(
                user=self.requester, action=ItemAction.APPROVE_GIVEAWAY_REQUEST
            )


class GiveawayRequestPageRenderingTest(GiveawayRequestFlowTestBase):
    """The giveaway listing renders its form toggle, banner, CTA, and the
    owner's approval controls."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_giveaway_fixtures("gwreq_render")

    def test_010_create_form_shows_listing_toggle(self) -> None:
        self.client.force_login(self.owner)
        response = self.client.get(reverse("item-create"))
        self.assertContains(response, 'name="listing_type"')

    def test_020_detail_shows_gift_banner_and_cta(self) -> None:
        self.client.force_login(self.requester)
        response = self.client.get(reverse("item-detail", args=[self.item.pk]))
        self.assertContains(response, "Free to a good home")
        self.assertContains(response, "Request gift")

    def test_030_owner_inventory_shows_pending_request(self) -> None:
        self.item.process_action(
            user=self.requester, action=ItemAction.REQUEST_GIVEAWAY
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("profile-inventory"))
        self.assertContains(response, "wants your giveaway!")
        self.assertContains(response, "Approve")
        self.assertContains(response, "Decline")
