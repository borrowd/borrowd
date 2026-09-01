"""
Tests for the profile page's back arrow: it must not send the user back to a
form they just submitted (password change, profile edit), and it must honor
the pages users actually arrive from.
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

    def _get_profile(self, referer_url: str | None = None) -> str:
        """Back-button target the profile page resolves for a given Referer."""
        if referer_url is None:
            response = self.client.get(reverse("profile"))
        else:
            response = self.client.get(
                reverse("profile"),
                HTTP_REFERER=f"http://testserver{referer_url}",
            )
        return str(response.context["back_url"])

    def test_back_url_does_not_point_at_password_change_form(self) -> None:
        """
        The original repro: profile -> password change -> submit -> land on
        profile -> back arrow. The Referer at that point is the password-change
        form itself, which isn't a sane back target.
        """
        self.assertEqual(
            self._get_profile(reverse("account_change_password")),
            reverse("item-list"),
        )

    def test_back_url_honors_allowed_referer(self) -> None:
        """A Referer on the allowlist (e.g. inventory) is honored as-is."""
        inventory_url = reverse("profile-inventory")

        self.assertEqual(self._get_profile(inventory_url), inventory_url)

    def test_back_url_honors_drawer_pages(self) -> None:
        """
        The drawer renders on every authenticated page, so anything reachable
        from it is a realistic Referer for the profile page.
        """
        for url_name in (
            "community-request-list",
            "notification-inbox",
            "notification-preferences",
        ):
            with self.subTest(url_name=url_name):
                referer_url = reverse(url_name)
                self.assertEqual(self._get_profile(referer_url), referer_url)

    def test_back_url_ignores_referer_from_profile_itself(self) -> None:
        """
        Saving the profile form redirects back to the profile, making the
        profile its own Referer. Pointing the arrow at the page you're on
        would be a no-op click, so fall back instead.
        """
        self.assertEqual(self._get_profile(reverse("profile")), reverse("item-list"))

    def test_back_url_falls_back_with_no_referer(self) -> None:
        """Direct navigation or a bookmark: no signal, so use the fallback."""
        self.assertEqual(self._get_profile(), reverse("item-list"))

    def test_back_arrow_renders_resolved_url(self) -> None:
        """The template half: the arrow href is the resolved URL, not history.back()."""
        inventory_url = reverse("profile-inventory")
        response = self.client.get(
            reverse("profile"),
            HTTP_REFERER=f"http://testserver{inventory_url}",
        )

        self.assertContains(response, f'href="{inventory_url}"')
        self.assertNotContains(response, "javascript:history.back()")
