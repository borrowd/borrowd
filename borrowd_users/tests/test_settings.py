"""
Tests for the settings page: its route, its sections, the old per-section
URLs that now open those sections, and the security, notification,
messaging and account controls it hosts.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from borrowd_users.models import BorrowdUser

# Old per-section URL name -> the section of the settings page it now opens.
SECTION_REDIRECTS = {
    "settings-security": "security",
    "notification-preferences": "notifications",
    "settings-account": "account",
}


def section_url(section: str) -> str:
    return f"{reverse('settings')}#{section}"


class SettingsTestCase(TestCase):
    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="sage", email="sage@example.com", password="hunter22!"
        )
        self.client.force_login(self.user)


class SettingsPageTests(SettingsTestCase):
    def test_shows_every_section_in_order_under_a_heading(self) -> None:
        content = self.client.get(reverse("settings")).content.decode()

        positions = [
            content.index(f'<h2 id="{section}-heading"')
            for section in ("security", "notifications", "account")
        ]
        self.assertEqual(positions, sorted(positions))
        for section in ("security", "notifications", "account"):
            with self.subTest(section=section):
                self.assertIn(f'<section id="{section}"', content)

    def test_has_no_section_tabs(self) -> None:
        response = self.client.get(reverse("settings"))

        self.assertNotContains(response, 'aria-label="Settings sections"')
        self.assertNotContains(response, 'aria-current="page"')

    def test_requires_login(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("settings"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_old_section_urls_open_their_section(self) -> None:
        for url_name, section in SECTION_REDIRECTS.items():
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertRedirects(
                    response, section_url(section), fetch_redirect_response=False
                )

    def test_old_section_urls_require_login(self) -> None:
        self.client.logout()

        for url_name in SECTION_REDIRECTS:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_drawer_lists_settings_between_profile_and_faq(self) -> None:
        content = self.client.get(reverse("settings")).content.decode()

        profile_link = content.index(f'href="{reverse("profile")}"')
        settings_link = content.index(f'href="{reverse("settings")}"')
        faq_link = content.index(f'href="{reverse("faq")}"')
        self.assertLess(profile_link, settings_link)
        self.assertLess(settings_link, faq_link)


class ProfileWithoutSettingsTests(SettingsTestCase):
    def test_profile_has_no_settings_controls(self) -> None:
        response = self.client.get(reverse("profile"))

        for url_name in (
            "account_change_password",
            "notification-bulk-toggle",
            "account-delete",
        ):
            with self.subTest(url_name=url_name):
                self.assertNotContains(response, reverse(url_name))

    def test_push_prompt_lives_on_settings(self) -> None:
        self.assertNotContains(self.client.get(reverse("profile")), "pushPermissionCta")

    @override_settings(VAPID_PRIVATE_KEY="private", VAPID_PUBLIC_KEY="public")
    def test_push_prompt_is_on_settings_when_push_is_available(self) -> None:
        self.assertContains(self.client.get(reverse("settings")), "pushPermissionCta()")


class SecuritySettingsTests(SettingsTestCase):
    def test_links_to_change_password(self) -> None:
        response = self.client.get(reverse("settings"))

        self.assertContains(response, f'href="{reverse("account_change_password")}"')

    def test_password_change_form_backs_out_to_security(self) -> None:
        response = self.client.get(reverse("account_change_password"))

        self.assertContains(response, f'href="{section_url("security")}"')

    def test_password_change_lands_on_security(self) -> None:
        response = self.client.post(
            reverse("account_change_password"),
            {"password1": "Correct-Horse-9", "password2": "Correct-Horse-9"},
        )

        self.assertRedirects(
            response, section_url("security"), fetch_redirect_response=False
        )


class AccountSettingsTests(SettingsTestCase):
    def test_delete_form_posts_to_account_delete(self) -> None:
        response = self.client.get(reverse("settings"))

        self.assertContains(response, f'action="{reverse("account-delete")}"')

    def test_failed_delete_returns_to_account(self) -> None:
        response = self.client.post(
            reverse("account-delete"), {"confirm_username": "not-sage"}
        )

        self.assertRedirects(
            response, section_url("account"), fetch_redirect_response=False
        )


@override_settings(MESSAGING_ENABLED=True)
class MessagingSettingsTests(SettingsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("settings-messaging")

    def test_page_shows_the_stored_preference(self) -> None:
        settings_url = reverse("settings")
        self.assertContains(self.client.get(settings_url), "preRequestChatToggle(true)")

        self.user.profile.allow_pre_request_chat = False
        self.user.profile.save(update_fields=["allow_pre_request_chat"])

        self.assertContains(
            self.client.get(settings_url), "preRequestChatToggle(false)"
        )

    def test_old_url_opens_the_messaging_section(self) -> None:
        response = self.client.get(self.url)

        self.assertRedirects(
            response, section_url("messaging"), fetch_redirect_response=False
        )

    def test_turning_it_off_is_saved_and_attributed(self) -> None:
        response = self.client.post(self.url, {"enabled": "false"})

        self.assertEqual(response.status_code, 204)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.allow_pre_request_chat)
        self.assertEqual(self.user.profile.updated_by, self.user)

    def test_turning_it_back_on_is_saved(self) -> None:
        self.client.post(self.url, {"enabled": "false"})

        response = self.client.post(self.url, {"enabled": "true"})

        self.assertEqual(response.status_code, 204)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.allow_pre_request_chat)

    def test_rejects_anything_but_true_or_false(self) -> None:
        for data in ({}, {"enabled": ""}, {"enabled": "yes"}, {"enabled": "TRUE"}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data).status_code, 400)

        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.allow_pre_request_chat)

    def test_anonymous_visitors_are_sent_to_login(self) -> None:
        self.client.logout()

        for response in (
            self.client.get(self.url),
            self.client.post(self.url, {"enabled": "false"}),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response["Location"])

    def test_the_settings_page_has_a_messaging_section(self) -> None:
        response = self.client.get(reverse("settings"))

        self.assertContains(response, '<section id="messaging"')
        self.assertContains(response, f"fetch('{self.url}'")

    @override_settings(MESSAGING_ENABLED=False)
    def test_section_and_endpoint_disappear_while_messaging_is_off(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.post(self.url, {"enabled": "false"}).status_code, 404
        )
        response = self.client.get(reverse("settings"))
        self.assertNotContains(response, '<section id="messaging"')
        self.assertNotContains(response, self.url)
