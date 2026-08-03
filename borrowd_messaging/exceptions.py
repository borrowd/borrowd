from borrowd.exceptions import BorrowdException


class NotThreadParticipant(BorrowdException):
    """Raised when a user acts on a ChatThread they are not a party to."""

    pass


class MessagingDisabled(BorrowdException):
    """Raised when messaging is used while MESSAGING_ENABLED is off."""

    pass


class PreRequestChatUnavailable(BorrowdException):
    """
    Raised when a pre-request thread cannot be opened for an item, e.g. the
    item is not available or its owner has pre-request chat turned off.
    """

    pass
