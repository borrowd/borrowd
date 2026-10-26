from django.test import TestCase
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
