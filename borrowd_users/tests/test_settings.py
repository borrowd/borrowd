"""
Tests for the settings section: its routes, the section tabs, and the controls
that moved there off the profile page.
"""

from django.test import TestCase
from django.urls import reverse

from borrowd_users.models import BorrowdUser

SECTION_URL_NAMES = (
    "settings-security",
    "notification-preferences",
    "settings-account",
)


class SettingsTestCase(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="sage", email="sage@example.com", password="hunter22!"
        )
        self.client.force_login(self.user)


class SettingsRoutingTests(SettingsTestCase):
    def test_root_opens_the_first_section(self) -> None:
        response = self.client.get(reverse("settings"))

        self.assertRedirects(response, reverse("settings-security"))

    def test_sections_are_deep_linkable(self) -> None:
        for url_name in SECTION_URL_NAMES:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_sections_require_login(self) -> None:
        self.client.logout()

        for url_name in SECTION_URL_NAMES:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_tabs_link_to_every_other_section(self) -> None:
        for current in SECTION_URL_NAMES:
            with self.subTest(current=current):
                response = self.client.get(reverse(current))

                self.assertContains(response, 'aria-current="page"', count=1)
                self.assertNotContains(response, f'href="{reverse(current)}"')
                for other in SECTION_URL_NAMES:
                    if other != current:
                        self.assertContains(response, f'href="{reverse(other)}"')

    def test_drawer_lists_settings_between_profile_and_faq(self) -> None:
        content = self.client.get(reverse("settings-security")).content.decode()

        profile_link = content.index(f'href="{reverse("profile")}"')
        settings_link = content.index(f'href="{reverse("settings")}"')
        faq_link = content.index(f'href="{reverse("faq")}"')
        self.assertLess(profile_link, settings_link)
        self.assertLess(settings_link, faq_link)


class ProfileWithoutSettingsTests(SettingsTestCase):
    def test_profile_drops_the_settings_controls(self) -> None:
        response = self.client.get(reverse("profile"))

        for url_name in (
            "account_change_password",
            "notification-preferences",
            "account-delete",
        ):
            with self.subTest(url_name=url_name):
                self.assertNotContains(response, reverse(url_name))

    def test_push_prompt_lives_on_notification_settings(self) -> None:
        self.assertNotContains(self.client.get(reverse("profile")), "pushPermissionCta")
        self.assertContains(
            self.client.get(reverse("notification-preferences")),
            "pushPermissionCta()",
        )


class SecuritySettingsTests(SettingsTestCase):
    def test_links_to_change_password(self) -> None:
        response = self.client.get(reverse("settings-security"))

        self.assertContains(response, f'href="{reverse("account_change_password")}"')

    def test_password_change_form_backs_out_to_security(self) -> None:
        response = self.client.get(reverse("account_change_password"))

        self.assertContains(response, f'href="{reverse("settings-security")}"')

    def test_password_change_lands_on_security(self) -> None:
        response = self.client.post(
            reverse("account_change_password"),
            {"password1": "Correct-Horse-9", "password2": "Correct-Horse-9"},
        )

        self.assertRedirects(response, reverse("settings-security"))


class AccountSettingsTests(SettingsTestCase):
    def test_delete_form_posts_to_account_delete(self) -> None:
        response = self.client.get(reverse("settings-account"))

        self.assertContains(response, f'action="{reverse("account-delete")}"')
