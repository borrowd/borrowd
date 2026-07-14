"""Tests for the request-scoped auth helpers in `borrowd_users.request`."""

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase

from borrowd_users.models import BorrowdUser
from borrowd_users.request import get_authenticated_user


class GetAuthenticatedUserTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_returns_borrowd_user(self) -> None:
        user = BorrowdUser.objects.create_user(
            username="alice", email="alice@example.com", password="pw"
        )
        request = self.factory.get("/")
        request.user = user

        self.assertEqual(get_authenticated_user(request), user)

    def test_raises_for_anonymous_user(self) -> None:
        request = self.factory.get("/")
        request.user = AnonymousUser()

        with self.assertRaises(PermissionDenied):
            get_authenticated_user(request)
