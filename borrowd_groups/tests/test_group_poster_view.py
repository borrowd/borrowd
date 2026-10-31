from urllib.parse import urlparse

from django.test import TestCase
from django.urls import resolve, reverse

from borrowd_groups.models import BorrowdGroup
from borrowd_groups.views import InviteSigner
from borrowd_users.models import BorrowdUser


class GroupPosterViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.outsider = BorrowdUser.objects.create_user(
            username="outsider", email="outsider@example.com", password="password"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="Maple Street Neighbours",
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.poster_url = reverse("borrowd_groups:group-poster", args=[self.group.pk])
        self.invite_url = reverse("borrowd_groups:group-invite", args=[self.group.pk])

    def _join_token(self, join_url: str) -> str:
        """The signed invite token: the last path segment of a join URL."""
        return urlparse(join_url).path.rstrip("/").rsplit("/", 1)[-1]

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        response = self.client.get(self.poster_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

    def test_non_member_is_refused_like_invite_page(self) -> None:
        self.client.force_login(self.outsider)

        poster_response = self.client.get(self.poster_url)
        invite_response = self.client.get(self.invite_url)

        self.assertEqual(poster_response.status_code, 404)
        self.assertEqual(poster_response.status_code, invite_response.status_code)

    def test_member_sees_group_name_and_invite_url(self) -> None:
        self.client.force_login(self.owner)

        response = self.client.get(self.poster_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maple Street Neighbours")
        join_url = response.context["join_url"]
        self.assertContains(response, f'data-qr-svg-value="{join_url}"')

    def test_poster_encodes_same_invite_as_invite_page(self) -> None:
        self.client.force_login(self.owner)

        poster_join_url = self.client.get(self.poster_url).context["join_url"]
        invite_join_url = self.client.get(self.invite_url).context["join_url"]

        # Tokens embed a signing timestamp, so compare what they decode to.
        self.assertEqual(
            InviteSigner.unsign_invite(self._join_token(poster_join_url)),
            InviteSigner.unsign_invite(self._join_token(invite_join_url)),
        )
        for join_url in (poster_join_url, invite_join_url):
            self.assertEqual(
                resolve(urlparse(join_url).path).view_name,
                "borrowd_groups:group-join",
            )

    def test_poster_invite_url_lets_outsider_join(self) -> None:
        self.client.force_login(self.owner)
        join_url = self.client.get(self.poster_url).context["join_url"]

        self.client.force_login(self.outsider)
        response = self.client.get(urlparse(join_url).path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maple Street Neighbours")

    def test_invite_page_links_to_poster(self) -> None:
        self.client.force_login(self.owner)

        response = self.client.get(self.invite_url)

        self.assertContains(response, f'href="{self.poster_url}"')
        self.assertContains(response, "Create sharing poster")

    def test_group_detail_page_links_to_poster(self) -> None:
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("borrowd_groups:group-detail", args=[self.group.pk])
        )

        self.assertContains(response, f'href="{self.poster_url}"')
        self.assertContains(response, "Create sharing poster")
