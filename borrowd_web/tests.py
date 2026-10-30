from django.test import TestCase, override_settings
from django.urls import reverse

from borrowd_users.models import BorrowdUser


class IndexViewTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self) -> None:
        response = self.client.get(reverse("index"))
        self.assertRedirects(response, reverse("account_login"))

    def test_authenticated_user_is_redirected_to_item_list(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="borrower", email="borrower@example.com", password="password"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("index"))

        self.assertRedirects(response, reverse("item-list"))


class OnboardingStepLinksTests(TestCase):
    """Each step's Back/Continue links use {% url %}, not a hardcoded path --
    see CON-03 from the UX audit."""

    def setUp(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="onboarder", email="onboarder@example.com", password="password"
        )
        self.client.force_login(user)

    def test_step2_continue_link_uses_the_named_url(self) -> None:
        response = self.client.get(reverse("onboarding_step2"))

        self.assertContains(response, f'href="{reverse("onboarding_step3")}"')
        self.assertNotContains(response, 'href="/onboarding/3"')


@override_settings(APPLE_TEAM_ID="ABCDE12345")
class AppleAppSiteAssociationTests(TestCase):
    url = "/.well-known/apple-app-site-association"

    def test_lists_the_native_app_for_universal_links(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        details = response.json()["applinks"]["details"]
        self.assertEqual(details[0]["appIDs"], ["ABCDE12345.org.borrowd.app"])

    def test_admin_stays_in_the_browser(self) -> None:
        components = self.client.get(self.url).json()["applinks"]["details"][0][
            "components"
        ]

        self.assertIn({"/": "/admin/*", "exclude": True}, components)
        # Exclusions only apply when listed before the catch-all.
        self.assertEqual(components[-1], {"/": "/*"})

    @override_settings(APPLE_TEAM_ID="")
    def test_404s_when_team_id_is_not_configured(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_is_served_past_the_beta_wall(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 200)


@override_settings(ANDROID_CERT_SHA256_FINGERPRINTS=["AA:BB", "CC:DD"])
class AssetLinksTests(TestCase):
    url = "/.well-known/assetlinks.json"

    def test_lists_the_native_app_for_app_links(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        [statement] = response.json()
        self.assertEqual(
            statement["relation"], ["delegate_permission/common.handle_all_urls"]
        )
        self.assertEqual(
            statement["target"],
            {
                "namespace": "android_app",
                "package_name": "org.borrowd.app",
                "sha256_cert_fingerprints": ["AA:BB", "CC:DD"],
            },
        )

    @override_settings(ANDROID_CERT_SHA256_FINGERPRINTS=[])
    def test_404s_when_fingerprints_are_not_configured(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(BORROWD_BETA_ENABLED=True)
    def test_is_served_past_the_beta_wall(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 200)
