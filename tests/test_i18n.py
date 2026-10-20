from django.test import TestCase
from django.urls import reverse


class LocaleInfrastructureTests(TestCase):
    def test_foreign_accept_language_falls_back_to_english(self) -> None:
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="es")
        self.assertEqual(response.headers["Content-Language"], "en")

    def test_urls_have_no_language_prefix(self) -> None:
        self.assertFalse(reverse("account_signup").startswith("/en/"))
