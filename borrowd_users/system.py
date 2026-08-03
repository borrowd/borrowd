"""System user tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

SYSTEM_USER_USERNAME = "system"


def get_system_user() -> BorrowdUser:
    """
    The account that owns actions no real user initiated. `get_or_create` for test purposes.
    """
    from django.contrib.auth.hashers import make_password

    from borrowd_users.models import BorrowdUser

    user, _ = BorrowdUser.objects.get_or_create(
        username=SYSTEM_USER_USERNAME,
        defaults={
            "password": make_password(None),
            "first_name": "System",
            "last_name": "User",
            "is_active": False,
            "is_staff": False,
            "is_superuser": False,
        },
    )
    return user
