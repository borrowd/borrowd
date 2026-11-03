import re

from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from borrowd_users.middleware import NATIVE_SESSION_REFRESHED_KEY
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


class LoginSessionLengthTests(TestCase):
    APP_USER_AGENT = (
        f"Mozilla/5.0 (Linux; Android 16) Mobile {settings.NATIVE_APP_USER_AGENT}"
    )

    def setUp(self) -> None:
        self.user = BorrowdUser.objects.create_user(
            username="sessions", email="sessions@example.com", password="password"
        )

    def _password_login(self, **headers: str) -> None:
        self.client.post(
            reverse("account_login"),
            {"login": self.user.email, "password": "password"},
            headers=headers,
        )
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))

    def test_web_password_login_ends_when_browser_closes(self) -> None:
        self._password_login()

        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_app_password_login_outlives_quitting_the_app(self) -> None:
        self._password_login(user_agent=self.APP_USER_AGENT)

        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), settings.NATIVE_APP_SESSION_AGE)

    def _login_by_code(self, **headers: str) -> None:
        self.client.post(
            reverse("account_request_login_code"),
            {"email": self.user.email},
            headers=headers,
        )
        code = re.search(r"\b\d{6}\b", str(mail.outbox[-1].body))
        assert code is not None
        self.client.post(
            reverse("account_confirm_login_code"),
            {"code": code.group()},
            headers=headers,
        )
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))

    def test_web_login_by_code_lasts_session_cookie_age(self) -> None:
        self._login_by_code()

        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        self.assertNotIn(NATIVE_SESSION_REFRESHED_KEY, session)

    def test_app_login_by_code_outlives_quitting_the_app(self) -> None:
        self._login_by_code(user_agent=self.APP_USER_AGENT)

        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), settings.NATIVE_APP_SESSION_AGE)

    def test_app_session_is_extended_on_the_next_days_use(self) -> None:
        self._password_login(user_agent=self.APP_USER_AGENT)
        session = self.client.session
        session.set_expiry(60)
        session[NATIVE_SESSION_REFRESHED_KEY] = "2000-01-01"
        session.save()

        self.client.get(
            reverse("item-list"), headers={"user_agent": self.APP_USER_AGENT}
        )

        session = self.client.session
        self.assertEqual(session.get_expiry_age(), settings.NATIVE_APP_SESSION_AGE)
        self.assertEqual(
            session[NATIVE_SESSION_REFRESHED_KEY], timezone.now().date().isoformat()
        )


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
