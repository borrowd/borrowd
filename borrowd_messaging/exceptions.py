from borrowd.exceptions import BorrowdException


class NotThreadParticipant(BorrowdException):
    """Raised when a user acts on a ChatThread they are not a party to."""


class MessagingDisabled(BorrowdException):
    """Raised when messaging is used while MESSAGING_ENABLED is off."""


class ThreadNotWritable(BorrowdException):
    """Raised when a message is sent to an archived, read-only thread."""


class InvalidMessageBody(BorrowdException):
    """Raised when a message body is empty or longer than the column allows."""


class PreRequestChatUnavailable(BorrowdException):
    """
    Raised when a pre-request thread cannot be opened for an item, e.g. the
    item is not available or its owner has pre-request chat turned off.
    """
