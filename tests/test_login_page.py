from django.test import TestCase
from django.urls import reverse

from borrowd_users.models import BorrowdUser


class LoginPageNextParamTests(TestCase):
    def test_signup_and_login_code_links_preserve_next_param(self) -> None:
        next_url = reverse("borrowd_groups:group-join", args=["abc123"])

        response = self.client.get(reverse("account_login"), {"next": next_url})

        content = response.content.decode()
        signup_url = reverse("account_signup")
        login_code_url = reverse("account_request_login_code")
        self.assertIn(f'href="{signup_url}?next={next_url}"', content)
        self.assertIn(f'href="{login_code_url}?next={next_url}"', content)


class LoginSessionPersistenceTests(TestCase):
    def test_password_login_session_outlives_browser_close(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="remembered", email="remembered@example.com", password="password"
        )

        self.client.post(
            reverse("account_login"), {"login": user.email, "password": "password"}
        )

        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))
        self.assertFalse(self.client.session.get_expire_at_browser_close())


class AnonymousAuthPagesTests(TestCase):
    def test_login_signup_and_password_reset_pages_return_200(self) -> None:
        for url_name in [
            "account_login",
            "custom_signup",
            "account_reset_password",
            "account_reset_password_done",
            "account_request_login_code",
        ]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_confirm_login_code_page_returns_200_after_requesting_a_code(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="coder", email="coder@example.com", password="password"
        )
        self.client.post(reverse("account_request_login_code"), {"email": user.email})

        response = self.client.get(reverse("account_confirm_login_code"))

        self.assertEqual(response.status_code, 200)
