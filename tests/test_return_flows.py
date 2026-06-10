from datetime import timedelta

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from borrowd.models import TrustLevel
from borrowd_groups.models import BorrowdGroup
from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.models import (
    Item,
    ItemAction,
    ItemStatus,
    ResolutionReason,
    Transaction,
    TransactionStatus,
)
from borrowd_items.views import borrow_item
from borrowd_users.models import BorrowdUser


class ReturnFlowTestBase(SimpleTestCase):
    """
    Shared fixtures and helpers for the sequential return/dispute flow
    tests below. See `RejectedFlowTest` in test_borrowing_flows.py for
    why these flows are tested as ordered steps within a class.
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
    def create_loan_fixtures(cls, prefix: str) -> None:
        """Create a lender, borrower, shared group, and item."""
        cls.lender = BorrowdUser.objects.create(
            username=f"{prefix}_lender", email=f"{prefix}_lender@example.com"
        )
        cls.borrower = BorrowdUser.objects.create(
            username=f"{prefix}_borrower", email=f"{prefix}_borrower@example.com"
        )
        cls.group = BorrowdGroup.objects.create(
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
        """Walk the loan to COLLECTED (item out with the borrower)."""
        cls.item.process_action(user=cls.borrower, action=ItemAction.REQUEST_ITEM)
        cls.item.process_action(user=cls.lender, action=ItemAction.ACCEPT_REQUEST)
        cls.item.process_action(user=cls.borrower, action=ItemAction.MARK_COLLECTED)
        cls.item.process_action(user=cls.lender, action=ItemAction.CONFIRM_COLLECTED)

    @classmethod
    def advance_to_return_requested(cls) -> None:
        """Walk the loan to RETURN_REQUESTED (lender wants it back)."""
        cls.advance_to_collected()
        cls.item.process_action(user=cls.lender, action=ItemAction.REQUEST_RETURN)

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
        """Submit a borrow action via POST and assert it redirects (302)."""
        request = self.factory.post(
            reverse("item-borrow", args=[self.item.pk]),
            {"action": action},
        )
        request.user = user
        response = borrow_item(request, pk=self.item.pk)
        self.assertEqual(response.status_code, 302)

    def current_tx(self) -> Transaction:
        """Return the flow's single Transaction, refreshed from the DB."""
        tx = self.item.transactions.order_by("-created_at").first()
        if tx is None:
            self.fail("Should have a Transaction")
        return tx


class ReturnRequestedHappyFlowTest(ReturnFlowTestBase):
    """
    COLLECTED -> lender requests return -> borrower asserts return ->
    lender confirms -> RETURNED, item AVAILABLE.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_happy")
        cls.advance_to_collected()

    def test_010_actions_at_collected(self) -> None:
        """Lender can request return; borrower can only assert return."""
        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (ItemAction.MARK_RETURNED, ItemAction.REQUEST_RETURN),
        )
        self.assertTupleEqual(
            self.item.get_actions_for(self.borrower),
            (ItemAction.MARK_RETURNED,),
        )

    def test_020_lender_requests_return(self) -> None:
        """Return request moves the transaction and stamps the timestamp."""
        self.post_action(self.lender, ItemAction.REQUEST_RETURN)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RETURN_REQUESTED)
        self.assertIsNotNone(tx.return_requested_at)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BORROWED)

    def test_030_actions_at_return_requested(self) -> None:
        """Lender can confirm (no dispute yet); borrower can assert or flag."""
        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (ItemAction.CONFIRM_RETURNED,),
        )
        self.assertTupleEqual(
            self.item.get_actions_for(self.borrower),
            (ItemAction.MARK_RETURNED, ItemAction.FLAG_CANNOT_RETURN),
        )

    def test_040_borrower_asserts_return(self) -> None:
        """Borrower's assertion locks them out until the lender confirms."""
        self.post_action(self.borrower, ItemAction.MARK_RETURNED)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RETURN_ASSERTED)
        self.assertTupleEqual(self.item.get_actions_for(self.borrower), tuple())
        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED),
        )

    def test_050_lender_confirms_return(self) -> None:
        """Confirmation completes the loan and frees the item."""
        self.post_action(self.lender, ItemAction.CONFIRM_RETURNED)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RETURNED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


class LenderConfirmsFromReturnRequestedTest(ReturnFlowTestBase):
    """
    The lender who requested the return can confirm receipt directly,
    without waiting for the borrower to assert.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_direct")
        cls.advance_to_return_requested()

    def test_010_lender_confirms_directly(self) -> None:
        """Direct confirmation completes the loan and frees the item."""
        self.post_action(self.lender, ItemAction.CONFIRM_RETURNED)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RETURNED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


class BorrowerCannotReturnFlowTest(ReturnFlowTestBase):
    """
    RETURN_REQUESTED -> borrower flags they cannot return -> DISPUTED ->
    lender resolves with the item returned.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_cannot")
        cls.advance_to_return_requested()

    def test_010_borrower_flags_cannot_return(self) -> None:
        """Flagging moves the transaction to DISPUTED and records who/when."""
        self.post_action(self.borrower, ItemAction.FLAG_CANNOT_RETURN)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.DISPUTED)
        self.assertIsNotNone(tx.disputed_at)
        self.assertEqual(tx.dispute_raised_by, self.borrower)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BORROWED)

    def test_020_actions_at_disputed(self) -> None:
        """Only the lender can act on a disputed transaction."""
        self.assertTupleEqual(self.item.get_actions_for(self.borrower), tuple())
        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (
                ItemAction.RESOLVE_DISPUTE_NOT_RETURNED,
                ItemAction.RESOLVE_DISPUTE_RETURNED,
            ),
        )

    def test_030_lender_resolves_returned(self) -> None:
        """Resolution frees the item; the dispute record survives."""
        self.post_action(self.lender, ItemAction.RESOLVE_DISPUTE_RETURNED)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RETURNED)
        self.assertIsNotNone(tx.disputed_at)
        self.assertEqual(tx.dispute_raised_by, self.borrower)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.AVAILABLE)


class LenderDisputeEscalationFlowTest(ReturnFlowTestBase):
    """
    RETURN_REQUESTED -> wait window passes -> lender raises a dispute ->
    lender resolves with the item not returned.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_escalate")
        cls.advance_to_return_requested()

    def test_010_dispute_gated_before_wait_elapses(self) -> None:
        """The lender cannot dispute until the wait window has passed."""
        self.assertNotIn(
            ItemAction.RAISE_DISPUTE, self.item.get_actions_for(self.lender)
        )
        with self.assertRaises(InvalidItemAction):
            self.item.process_action(user=self.lender, action=ItemAction.RAISE_DISPUTE)

    def test_020_lender_disputes_after_wait(self) -> None:
        """Once the window passes, the lender can escalate to a dispute."""
        tx = self.current_tx()
        if tx.return_requested_at is None:
            self.fail("Should have a return_requested_at timestamp")
        tx.return_requested_at = tx.return_requested_at - timedelta(
            days=settings.RETURN_DISPUTE_WAIT_DAYS
        )
        tx.save()

        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED),
        )
        self.post_action(self.lender, ItemAction.RAISE_DISPUTE)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.DISPUTED)
        self.assertIsNotNone(tx.disputed_at)
        self.assertEqual(tx.dispute_raised_by, self.lender)

    def test_030_lender_resolves_not_returned(self) -> None:
        """Not-returned resolution closes the loan and removes the item."""
        self.post_action(self.lender, ItemAction.RESOLVE_DISPUTE_NOT_RETURNED)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.RESOLVED)
        self.assertEqual(
            tx.resolution_reason, ResolutionReason.DISPUTE_ITEM_NOT_RETURNED
        )
        self.assertEqual(tx.dispute_raised_by, self.lender)
        self.item.refresh_from_db()
        self.assertIsNotNone(self.item.deleted_at)
        self.assertEqual(self.item.deleted_by, self.lender)


class LenderDeniesReturnAssertionFlowTest(ReturnFlowTestBase):
    """
    COLLECTED -> borrower asserts return -> lender denies the claim by
    raising a dispute (no wait window on this path).
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_deny")
        cls.advance_to_collected()

    def test_010_borrower_asserts_return(self) -> None:
        """Lender can confirm or dispute the borrower's return claim."""
        self.post_action(self.borrower, ItemAction.MARK_RETURNED)
        self.assertTupleEqual(
            self.item.get_actions_for(self.lender),
            (ItemAction.RAISE_DISPUTE, ItemAction.CONFIRM_RETURNED),
        )

    def test_020_lender_disputes_return_claim(self) -> None:
        """Denying the claim moves the transaction to DISPUTED."""
        self.post_action(self.lender, ItemAction.RAISE_DISPUTE)
        tx = self.current_tx()
        self.assertEqual(tx.status, TransactionStatus.DISPUTED)
        self.assertEqual(tx.dispute_raised_by, self.lender)


class BorrowerCannotDisputeLenderAssertionTest(ReturnFlowTestBase):
    """
    When the lender asserts the return themselves, the borrower may only
    confirm -- the dispute deny-path is lender-only.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create_loan_fixtures("ret_noborrower")
        cls.advance_to_collected()

    def test_010_borrower_gets_confirm_only(self) -> None:
        """Borrower sees only the confirm action on the lender's assertion."""
        self.post_action(self.lender, ItemAction.MARK_RETURNED)
        self.assertTupleEqual(
            self.item.get_actions_for(self.borrower),
            (ItemAction.CONFIRM_RETURNED,),
        )


class DisputeWaitWindowTest(SimpleTestCase):
    """Unit tests for Transaction.dispute_wait_has_elapsed."""

    @override_settings(RETURN_DISPUTE_WAIT_DAYS=3)
    def test_no_return_request_means_window_closed(self) -> None:
        tx = Transaction()
        self.assertFalse(tx.dispute_wait_has_elapsed())

    @override_settings(RETURN_DISPUTE_WAIT_DAYS=3)
    def test_window_closed_immediately_after_request(self) -> None:
        tx = Transaction(return_requested_at=timezone.now())
        self.assertFalse(tx.dispute_wait_has_elapsed())

    @override_settings(RETURN_DISPUTE_WAIT_DAYS=3)
    def test_window_open_after_wait(self) -> None:
        tx = Transaction(return_requested_at=timezone.now() - timedelta(days=3))
        self.assertTrue(tx.dispute_wait_has_elapsed())

    @override_settings(RETURN_DISPUTE_WAIT_DAYS=0)
    def test_zero_wait_opens_window_immediately(self) -> None:
        tx = Transaction(return_requested_at=timezone.now())
        self.assertTrue(tx.dispute_wait_has_elapsed())
