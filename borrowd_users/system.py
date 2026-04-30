"""System user tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from borrowd_users.models import BorrowdUser

SYSTEM_USER_USERNAME = "system"


def get_system_user() -> BorrowdUser:
    from borrowd_users.models import BorrowdUser

    return BorrowdUser.objects.get(username=SYSTEM_USER_USERNAME)
