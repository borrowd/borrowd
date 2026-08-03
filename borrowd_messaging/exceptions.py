from borrowd.exceptions import BorrowdException


class NotThreadParticipant(BorrowdException):
    """Raised when a user acts on a ChatThread they are not a party to."""

    pass
