from django.test import TestCase, override_settings
from django.urls import reverse

from borrowd_beta.models import BetaCode, BetaSignup
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user


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


@override_settings(BORROWD_BETA_ENABLED=True)
class BetaGateRedirectLoopTests(TestCase):
    """The login page is where anonymous users land when ungated, so it must
    itself be exempt from the beta gate -- otherwise the gate's own redirect
    target redirects right back into the gate. See BETA_SIGNUP_REDIRECT_PATH
    in borrowd/config/base.py."""

    def test_root_with_no_beta_cookie_resolves_to_login_without_looping(self) -> None:
        response = self.client.get("/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse("account_login"))

    def test_login_page_with_no_beta_cookie_shows_beta_modal(self) -> None:
        response = self.client.get(reverse("account_login"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_beta_access"])
        self.assertContains(response, "This is a beta version of Borrow'd.")

    def test_root_with_valid_beta_cookie_redirects_to_login_without_modal(
        self,
    ) -> None:
        beta_code = BetaCode.objects.create(
            name="Test code", code="TESTCOD", created_by=get_system_user()
        )
        beta_signup = BetaSignup.objects.create(beta_code=beta_code)
        self.client.cookies["beta_key"] = str(beta_signup.token)

        response = self.client.get("/")
        self.assertRedirects(response, reverse("account_login"))

        login_response = self.client.get(reverse("account_login"))
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.context["has_beta_access"])
        self.assertNotContains(login_response, "This is a beta version of Borrow'd.")

    def test_non_exempt_page_with_no_beta_cookie_redirects_to_login(self) -> None:
        response = self.client.get(reverse("item-list"))
        self.assertRedirects(response, reverse("account_login"))


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
