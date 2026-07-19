from django.test import TestCase
from django.utils import timezone

from borrowd_items.models import Item, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser


def _user(username: str) -> BorrowdUser:
    return BorrowdUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="password",
    )


def _item(owner: BorrowdUser, name: str) -> Item:
    return Item.objects.create(
        name=name,
        description="Useful for testing",
        owner=owner,
        created_by=owner,
        updated_by=owner,
    )


def _transaction(
    item: Item,
    party1: BorrowdUser,
    party2: BorrowdUser,
    status: TransactionStatus,
    **kwargs: object,
) -> Transaction:
    return Transaction.objects.create(
        item=item,
        party1=party1,
        party2=party2,
        status=status,
        created_by=party1,
        updated_by=party1,
        **kwargs,
    )


class TransactionQueryHelperTests(TestCase):
    def setUp(self) -> None:
        self.owner = _user("owner")
        self.borrower = _user("borrower")
        self.other_user = _user("other")

    def test_get_successful_borrows_returns_user_returned_borrow_transactions(
        self,
    ) -> None:
        matching_tx = _transaction(
            _item(self.owner, "Returned drill"),
            self.owner,
            self.borrower,
            TransactionStatus.RETURNED,
        )
        _transaction(
            _item(self.owner, "Collected drill"),
            self.owner,
            self.borrower,
            TransactionStatus.COLLECTED,
        )
        _transaction(
            _item(self.borrower, "Returned saw"),
            self.borrower,
            self.owner,
            TransactionStatus.RETURNED,
        )
        _transaction(
            _item(self.owner, "Other returned drill"),
            self.owner,
            self.other_user,
            TransactionStatus.RETURNED,
        )

        transactions = Transaction.get_successful_borrows(self.borrower)

        self.assertQuerySetEqual(transactions, [matching_tx], ordered=False)

    def test_get_successful_lends_returns_user_returned_only(
        self,
    ) -> None:
        returned_tx = _transaction(
            _item(self.owner, "Returned drill"),
            self.owner,
            self.borrower,
            TransactionStatus.RETURNED,
        )
        _transaction(
            _item(self.owner, "Given away saw"),
            self.owner,
            self.borrower,
            TransactionStatus.OWNERSHIP_TRANSFERRED,
        )
        _transaction(
            _item(self.owner, "Collected drill"),
            self.owner,
            self.borrower,
            TransactionStatus.COLLECTED,
        )
        _transaction(
            _item(self.borrower, "Borrower lent item"),
            self.borrower,
            self.owner,
            TransactionStatus.RETURNED,
        )
        _transaction(
            _item(self.other_user, "Other lent item"),
            self.other_user,
            self.borrower,
            TransactionStatus.RETURNED,
        )

        transactions = Transaction.get_successful_lends(self.owner)

        self.assertQuerySetEqual(
            transactions,
            [returned_tx],
            ordered=False,
        )

    def test_get_pending_return_requests_returns_user_pending_return_borrows(
        self,
    ) -> None:
        return_requested_tx = _transaction(
            _item(self.owner, "Requested return drill"),
            self.owner,
            self.borrower,
            TransactionStatus.RETURN_REQUESTED,
        )
        return_asserted_tx = _transaction(
            _item(self.owner, "Asserted return saw"),
            self.owner,
            self.borrower,
            TransactionStatus.RETURN_ASSERTED,
        )
        _transaction(
            _item(self.owner, "Collected drill"),
            self.owner,
            self.borrower,
            TransactionStatus.COLLECTED,
        )
        _transaction(
            _item(self.borrower, "Borrower requested return"),
            self.borrower,
            self.owner,
            TransactionStatus.RETURN_REQUESTED,
        )
        _transaction(
            _item(self.owner, "Other requested return"),
            self.owner,
            self.other_user,
            TransactionStatus.RETURN_REQUESTED,
        )

        transactions = Transaction.get_pending_return_requests(self.borrower)

        self.assertQuerySetEqual(
            transactions,
            [return_requested_tx, return_asserted_tx],
            ordered=False,
        )

    def test_get_past_disputes_returns_disputed_transactions_for_either_party(
        self,
    ) -> None:
        lender_dispute_tx = _transaction(
            _item(self.owner, "Lender disputed drill"),
            self.owner,
            self.borrower,
            TransactionStatus.DISPUTED,
            disputed_at=timezone.now(),
        )
        borrower_dispute_tx = _transaction(
            _item(self.borrower, "Borrower disputed saw"),
            self.borrower,
            self.owner,
            TransactionStatus.RETURNED,
            disputed_at=timezone.now(),
        )
        _transaction(
            _item(self.owner, "Resolved drill"),
            self.owner,
            self.borrower,
            TransactionStatus.RESOLVED,
        )
        _transaction(
            _item(self.other_user, "Other disputed item"),
            self.other_user,
            self.borrower,
            TransactionStatus.DISPUTED,
            disputed_at=timezone.now(),
        )

        transactions = Transaction.get_past_disputes(self.owner)

        self.assertQuerySetEqual(
            transactions,
            [lender_dispute_tx, borrower_dispute_tx],
            ordered=False,
        )
