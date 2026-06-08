from borrowd.exceptions import BorrowdException


class AccountDeletionBlocked(BorrowdException):
    """Raised when a user can't delete their account yet (e.g. still borrowing items)."""

    pass
