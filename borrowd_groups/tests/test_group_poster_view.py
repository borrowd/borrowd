from urllib.parse import urlparse

from django.test import TestCase
from django.urls import resolve, reverse

from borrowd_groups.models import BorrowdGroup, MembershipStatus
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

    def test_member_who_is_not_active_is_refused(self) -> None:
        membership = self.group.add_user(self.outsider)
        self.client.force_login(self.outsider)

        for status in (
            MembershipStatus.PENDING,
            MembershipStatus.SUSPENDED,
            MembershipStatus.BANNED,
            MembershipStatus.ENDED,
        ):
            with self.subTest(status=status):
                # save() rather than update(), so permissions sync.
                membership.status = status
                membership.save()
                self.assertEqual(self.client.get(self.poster_url).status_code, 404)

    def test_group_name_is_escaped(self) -> None:
        self.group.name = 'Café "Ünity" <Tools> & Co'
        self.group.save()
        self.client.force_login(self.owner)

        response = self.client.get(self.poster_url)

        escaped = "Café &quot;Ünity&quot; &lt;Tools&gt; &amp; Co"
        self.assertContains(response, f"{escaped} poster")  # <title>
        self.assertContains(response, escaped, count=2)  # <title> and <h1>
        self.assertNotContains(response, "<Tools>")
        join_url = response.context["join_url"]
        self.assertContains(response, f'data-qr-svg-value="{join_url}"')

    def test_qr_box_has_fallback_until_the_code_renders(self) -> None:
        self.client.force_login(self.owner)

        response = self.client.get(self.poster_url)

        self.assertContains(response, "QR code unavailable.")

    def test_long_names_get_a_smaller_wrapping_size(self) -> None:
        self.client.force_login(self.owner)
        cases = {
            "Short Name": 'class="poster-group-name"',
            "A" * 25: 'class="poster-group-name is-long"',
            "A" * 41: 'class="poster-group-name is-very-long"',
        }
        for name, expected in cases.items():
            with self.subTest(length=len(name)):
                self.group.name = name
                self.group.save()
                self.assertContains(self.client.get(self.poster_url), expected)
