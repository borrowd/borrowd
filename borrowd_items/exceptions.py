from borrowd.exceptions import BorrowdException


class InvalidItemAction(BorrowdException):
    pass


class ItemAlreadyRequested(InvalidItemAction):
    """Raised when a user tries to request an item that already has a pending request."""


class TransactionLenderMismatch(InvalidItemAction):
    """Raised when an open Transaction's lender is not the Item's owner."""
