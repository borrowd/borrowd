from borrowd.exceptions import BorrowdException


class InvalidItemAction(BorrowdException):
    # Stable for clients to switch on; the message is for people.
    code = "invalid_action"


class ItemAlreadyRequested(InvalidItemAction):
    """Raised when a user tries to request an item that already has a pending request."""

    code = "already_requested"


class TransactionLenderMismatch(InvalidItemAction):
    """Raised when an open Transaction's lender is not the Item's owner."""

    code = "invalid_state"


class AccountInactive(InvalidItemAction):
    """Raised when the acting account has been closed or deactivated."""

    code = "forbidden"


class StaleItemCommand(InvalidItemAction):
    """Raised when a command was decided on a version of the item that's gone."""

    code = "stale"

    def __init__(self, message: str, *, current_revision: int) -> None:
        super().__init__(message)
        self.current_revision = current_revision


class CommandKeyReused(InvalidItemAction):
    """Raised when a command key comes back attached to a different command."""

    code = "key_reused"
