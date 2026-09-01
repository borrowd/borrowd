from borrowd.exceptions import BorrowdException


class CannotActOnOwnRequestException(BorrowdException):
    """Raised when a user tries to fulfill or dismiss their own community request."""
