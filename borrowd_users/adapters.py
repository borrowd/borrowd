import string

from allauth.account.adapter import DefaultAccountAdapter
from django.utils.crypto import get_random_string


class BorrowdAccountAdapter(DefaultAccountAdapter):
    """Project-owned allauth adapter for auth flow customizations."""

    def generate_login_code(self) -> str:
        """Generate numeric-only login codes for email sign-in."""
        return get_random_string(length=6, allowed_chars=string.digits)
