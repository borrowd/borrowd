from borrowd.exceptions import BorrowdException


class ExistingMemberException(BorrowdException):
    pass


class ModeratorRequiredException(BorrowdException):
    pass
