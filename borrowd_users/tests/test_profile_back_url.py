"""
Regression tests for #469: the profile page's back arrow must not send the
user back to a form they just submitted (password change, profile edit).
"""

from django.test import TestCase
from django.urls import reverse

from borrowd_users.models import BorrowdUser


class ProfileBackUrlTests(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="rowan", email="rowan@example.com", password="hunter22!"
        )
        self.client.force_login(self.user)

    def test_back_url_does_not_point_at_password_change_form(self) -> None:
        """
        Reproduces the issue's exact repro: profile -> password change ->
        submit -> land on profile -> back arrow. The Referer at that point
        is the password-change form itself, which isn't a sane back target.
        """
        response = self.client.get(
            reverse("profile"),
            HTTP_REFERER="http://testserver" + reverse("account_change_password"),
        )

        self.assertEqual(response.context["back_url"], reverse("index"))

    def test_back_url_honors_allowed_referer(self) -> None:
        """A Referer on the allowlist (e.g. inventory) is honored as-is."""
        inventory_url = reverse("profile-inventory")
        response = self.client.get(
            reverse("profile"),
            HTTP_REFERER=f"http://testserver{inventory_url}",
        )

        self.assertEqual(response.context["back_url"], inventory_url)

    def test_back_url_falls_back_with_no_referer(self) -> None:
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.context["back_url"], reverse("index"))
