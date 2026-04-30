from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemAction, ItemStatus, TransactionStatus
from borrowd_items.views import ItemDetailView, borrow_item
from borrowd_users.models import BorrowdUser


# Use SimpleTestCase to prevent database cleanup between tests.
class RejectedFlowTest(SimpleTestCase):
    """
    This sequential set of tests is designed to test each step along
    the a borrowing flow which ultimately ends up Rejected.

    Note there does not seem to be a more formal way to specify the
    order in which tests should be run, other than to wrangle their
    alphabetical order as done below. This is probably because
    logical dependencies between tests is normally seen as a big red
    flag.

    However, there are exceptions to every rule, and in this
    scenario, where the objective is to test a workflow with multiple
    sequential steps, I feel it makes much more sense to test each
    step of a workflow as a separate test, each building on the
    previous. We still have encapsulation from the rest of the test
    suite by virtue keeping all relevant tests within this test class.

    The alternative would be to either A) have a single test with
    lots and lots of assertions crammed in, or B) have multiple tests
    with each having to rebuild the entire context each time, and
    only formally testing the "new" step added in each. IMO, flexing
    the rule of "no dependencies between tests" is preferable in this
    situation.
    """

    lender: BorrowdUser
    borrower: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    # SimpleTestCase expects no database access;
    # setting this class attribute makes it allowed again.
    databases = "__all__"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.lender = BorrowdUser.objects.create(
            username="lender", email="lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username="borrower", email="borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create(
            name="Test Group",
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.borrower, trust_level=TrustLevel.HIGH)
        cls.item = Item.objects.create(
            name="Test Item",
            description="Test Description",
            owner=cls.lender,
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level_required=TrustLevel.STANDARD,
        )
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls) -> None:
        # Clean up the database after the class completes
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.lender.delete()
        cls.borrower.delete()
        super().tearDownClass()

    def test_010_borrower_item_actions_initial_state(self) -> None:
        """
        Borrower's initial option is to Request Item.
        """
        #
        # Arrange
        #
        borrower = self.borrower

        ## Prepare the request
        request = self.factory.get(reverse("item-detail", args=[self.item.pk]))
        request.user = borrower

        #
        # Act
        #
        response = ItemDetailView.as_view()(request, pk=self.item.pk)
        # Required because this is (at least according to mypy) a
        # HttpResponseBase object, not a TemplateResponse like we get
        # from FilterViews. Hence, even though we can debug and.
        # observe that there is *in fact* a context_data attribute,
        # mypy doesn't know that.
        if not hasattr(response, "context_data"):
            self.fail("Response should have context_data")
        item_actions = response.context_data["action_context"].actions

        #
        # Assert
        #
        ## Check if the owner can see the item
        self.assertTupleEqual(
            item_actions,
            (ItemAction.REQUEST_ITEM,),
        )
        ## Item should still be available
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)

    def test_020_lender_item_actions_initial_state(self) -> None:
        """
        Lender can't borrow their own item.
        """
        #
        # Arrange
        #
        lender = self.lender

        ## Prepare the request
        request = self.factory.get(reverse("item-detail", args=[self.item.pk]))
        request.user = lender

        #
        # Act
        #
        response = ItemDetailView.as_view()(request, pk=self.item.pk)
        # Required because this is (at least according to mypy) a
        # HttpResponseBase object, not a TemplateResponse like we get
        # from FilterViews. Hence, even though we can debug and.
        # observe that there is *in fact* a context_data attribute,
        # mypy doesn't know that.
        if not hasattr(response, "context_data"):
            self.fail("Response should have context_data")
        item_actions = response.context_data["action_context"].actions

        #
        # Assert
        #
        ## No action options for the lender at this point
        self.assertTupleEqual(item_actions, tuple())

    def test_030_borrower_request_item_action(self) -> None:
        """
        Request Item action from Borrower succeeds.
        """
        #
        # Arrange
        #
        borrower = self.borrower

        ## Prepare the request
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": ItemAction.REQUEST_ITEM},
        )
        request.user = borrower

        #
        # Act
        #
        response = borrow_item(request, pk=self.item.pk)

        #
        # Assert
        #
        ## Check return code
        self.assertEqual(response.status_code, 302)
        ## Check that one Transaction was created
        self.assertEqual(self.item.transactions.count(), 1)
        ## Check that the transaction is in the correct state
        tx = self.item.transactions.first()
        if tx is None:
            self.fail("Should have a Transaction")
        self.assertEqual(tx.status, TransactionStatus.REQUESTED)
        ## Item status should now be REQUESTED
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)
        ## Redirects to item detail page after processing action
        self.assertEqual(
            response.url,  # type: ignore[attr-defined]
            reverse("item-detail", kwargs={"pk": self.item.pk}),
        )

    def test_040_lender_item_actions_following_request(self) -> None:
        """
        Once Item is Requested, Lender can Accept or Reject.
        """
        #
        # Arrange
        #
        lender = self.lender

        ## Prepare the request
        request = self.factory.get(reverse("item-detail", args=[self.item.pk]))
        request.user = lender

        #
        # Act
        #
        response = ItemDetailView.as_view()(request, pk=self.item.pk)
        # Required because this is (at least according to mypy) a
        # HttpResponseBase object, not a TemplateResponse like we get
        # from FilterViews. Hence, even though we can debug and.
        # observe that there is *in fact* a context_data attribute,
        # mypy doesn't know that.
        if not hasattr(response, "context_data"):
            self.fail("Response should have context_data")
        item_actions = response.context_data["action_context"].actions

        #
        # Assert
        #
        ## Check if the owner can see the item
        self.assertCountEqual(
            item_actions,
            (
                ItemAction.ACCEPT_REQUEST,
                ItemAction.REJECT_REQUEST,
            ),
        )
        self.assertIn(ItemAction.ACCEPT_REQUEST, item_actions)
        self.assertIn(ItemAction.REJECT_REQUEST, item_actions)

    def test_050_lender_reject_request_action(self) -> None:
        """
        Lender can Reject a Request.
        """
        #
        # Arrange
        #
        lender = self.lender

        ## Prepare the request
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": ItemAction.REJECT_REQUEST},
        )
        request.user = lender

        #
        # Act
        #
        response = borrow_item(request, pk=self.item.pk)

        #
        # Assert
        #
        ## Check return code
        self.assertEqual(response.status_code, 302)
        ## Check that one Transaction was created
        self.assertEqual(self.item.transactions.count(), 1)
        ## Check that the transaction is in the correct state
        tx = self.item.transactions.first()
        if tx is None:
            self.fail("Should have a Transaction")
        self.assertEqual(tx.status, TransactionStatus.REJECTED)
        ## Item status should be back to AVAILABLE after rejection
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


# Use SimpleTestCase to prevent database cleanup between tests.
class AcceptedFlowTest(SimpleTestCase):
    """
    Tests the full happy-path borrow flow:
    AVAILABLE -> REQUESTED -> ACCEPTED ->
    MARK_COLLECTED -> CONFIRM_COLLECTED ->
    MARK_RETURNED -> CONFIRM_RETURNED -> AVAILABLE

    Asserts both TransactionStatus and ItemStatus at each step.
    """

    lender: BorrowdUser
    borrower: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    # SimpleTestCase expects no database access;
    # setting this class attribute makes it allowed again.
    databases = "__all__"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.lender = BorrowdUser.objects.create(
            username="accept_lender", email="accept_lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username="accept_borrower", email="accept_borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create(
            name="Accept Test Group",
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.borrower, trust_level=TrustLevel.HIGH)
        cls.item = Item.objects.create(
            name="Accept Test Item",
            description="Test Description",
            owner=cls.lender,
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level_required=TrustLevel.STANDARD,
        )
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls) -> None:
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.lender.delete()
        cls.borrower.delete()
        super().tearDownClass()

    def _post_action(self, user: BorrowdUser, action: ItemAction) -> None:
        """Submit a borrow action via POST and assert it redirects (302)."""
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": action},
        )
        request.user = user
        response = borrow_item(request, pk=self.item.pk)
        self.assertEqual(response.status_code, 302)

    def _assert_state(
        self, tx_status: TransactionStatus, item_status: ItemStatus
    ) -> None:
        """Refresh item from DB and assert both transaction and item status."""
        self.item.refresh_from_db()
        tx = self.item.transactions.exclude(
            status__in=[TransactionStatus.RETURNED, TransactionStatus.CANCELLED]
        ).first()
        if tx is None:
            self.fail("Should have an active Transaction")
        self.assertEqual(tx.status, tx_status)
        self.assertEqual(self.item.status, item_status)

    def test_010_request(self) -> None:
        """Borrower requests the item."""
        self._post_action(self.borrower, ItemAction.REQUEST_ITEM)
        self._assert_state(TransactionStatus.REQUESTED, ItemStatus.REQUESTED)

    def test_020_accept(self) -> None:
        """Lender accepts the borrow request."""
        self._post_action(self.lender, ItemAction.ACCEPT_REQUEST)
        self._assert_state(TransactionStatus.ACCEPTED, ItemStatus.RESERVED)

    def test_030_mark_collected(self) -> None:
        """Borrower marks the item as picked up."""
        self._post_action(self.borrower, ItemAction.MARK_COLLECTED)
        self._assert_state(TransactionStatus.COLLECTION_ASSERTED, ItemStatus.RESERVED)

    def test_040_confirm_collected(self) -> None:
        """Lender confirms the item was picked up."""
        self._post_action(self.lender, ItemAction.CONFIRM_COLLECTED)
        self._assert_state(TransactionStatus.COLLECTED, ItemStatus.BORROWED)

    def test_050_mark_returned(self) -> None:
        """Borrower marks the item as returned."""
        self._post_action(self.borrower, ItemAction.MARK_RETURNED)
        self._assert_state(TransactionStatus.RETURN_ASSERTED, ItemStatus.BORROWED)

    def test_060_confirm_returned(self) -> None:
        """Lender confirms the item was returned, item becomes available again."""
        self._post_action(self.lender, ItemAction.CONFIRM_RETURNED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


class CancelFromRequestedFlowTest(SimpleTestCase):
    """
    See `RejectedFlowTest` docstring for info about why this is structured like it is.

    Tests cancelling a borrow request from the REQUESTED state.
    """

    lender: BorrowdUser
    borrower: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    # SimpleTestCase expects no database access;
    # setting this class attribute makes it allowed again.
    databases = "__all__"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.lender = BorrowdUser.objects.create(
            username="cancel_req_lender", email="cancel_req_lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username="cancel_req_borrower", email="cancel_req_borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create(
            name="Cancel Req Test Group",
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.borrower, trust_level=TrustLevel.HIGH)
        cls.item = Item.objects.create(
            name="Cancel Req Test Item",
            description="Test Description",
            owner=cls.lender,
            trust_level_required=TrustLevel.STANDARD,
            created_by=cls.lender,
            updated_by=cls.lender,
        )
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls) -> None:
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.lender.delete()
        cls.borrower.delete()
        super().tearDownClass()

    def _post_action(self, user: BorrowdUser, action: ItemAction) -> None:
        """Submit a borrow action via POST and assert it redirects (302)."""
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": action},
        )
        request.user = user
        response = borrow_item(request, pk=self.item.pk)
        self.assertEqual(response.status_code, 302)

    def test_010_request(self) -> None:
        """Borrower requests the item."""
        self._post_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.item.refresh_from_db()
        tx = self.item.transactions.first()
        if tx is None:
            self.fail("Should have a Transaction")
        self.assertEqual(tx.status, TransactionStatus.REQUESTED)
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)

    def test_020_cancel(self) -> None:
        """Borrower cancels before lender responds, item becomes available again."""
        self._post_action(self.borrower, ItemAction.CANCEL_REQUEST)
        self.item.refresh_from_db()
        tx = self.item.transactions.first()
        if tx is None:
            self.fail("Should have a Transaction")
        self.assertEqual(tx.status, TransactionStatus.CANCELLED)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


class CancelFromAcceptedFlowTest(SimpleTestCase):
    """
    See `RejectedFlowTest` docstring for info about why this is structured like it is.

    Tests cancelling a borrow request from the ACCEPTED state.
    """

    lender: BorrowdUser
    borrower: BorrowdUser
    group: BorrowdGroup
    item: Item
    factory: RequestFactory
    # SimpleTestCase expects no database access;
    # setting this class attribute makes it allowed again.
    databases = "__all__"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.lender = BorrowdUser.objects.create(
            username="cancel_acc_lender", email="cancel_acc_lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username="cancel_acc_borrower", email="cancel_acc_borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create(
            name="Cancel Acc Test Group",
            created_by=cls.lender,
            updated_by=cls.lender,
            trust_level=TrustLevel.HIGH,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.borrower, trust_level=TrustLevel.HIGH)
        cls.item = Item.objects.create(
            name="Cancel Acc Test Item",
            description="Test Description",
            owner=cls.lender,
            trust_level_required=TrustLevel.STANDARD,
            created_by=cls.lender,
            updated_by=cls.lender,
        )
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls) -> None:
        for tx in cls.item.transactions.all():
            tx.delete()
        cls.item.delete()
        cls.group.delete()
        cls.lender.delete()
        cls.borrower.delete()
        super().tearDownClass()

    def _post_action(self, user: BorrowdUser, action: ItemAction) -> None:
        """Submit a borrow action via POST and assert it redirects (302)."""
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": action},
        )
        request.user = user
        response = borrow_item(request, pk=self.item.pk)
        self.assertEqual(response.status_code, 302)

    def test_010_request(self) -> None:
        """Borrower requests the item."""
        self._post_action(self.borrower, ItemAction.REQUEST_ITEM)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.REQUESTED)

    def test_020_accept(self) -> None:
        """Lender accepts the borrow request."""
        self._post_action(self.lender, ItemAction.ACCEPT_REQUEST)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.RESERVED)

    def test_030_cancel(self) -> None:
        """Borrower cancels after lender accepted, item becomes available again."""
        self._post_action(self.borrower, ItemAction.CANCEL_REQUEST)
        self.item.refresh_from_db()
        tx = self.item.transactions.first()
        if tx is None:
            self.fail("Should have a Transaction")
        self.assertEqual(tx.status, TransactionStatus.CANCELLED)
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)
