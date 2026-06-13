from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .models import BorrowdUser


def get_authenticated_user(request: HttpRequest) -> BorrowdUser:
    """
    The request's user, narrowed to BorrowdUser.

    For views already behind a login requirement: narrows the
    AbstractBaseUser | AnonymousUser union for the type checker, and as
    defense in depth raises PermissionDenied if the view's login
    protection is ever lost.
    """
    user = request.user
    if not isinstance(user, BorrowdUser):
        raise PermissionDenied
    return user
