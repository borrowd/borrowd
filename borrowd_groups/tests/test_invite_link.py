from urllib.parse import urlparse

from django.test import TestCase
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup
from borrowd_groups.views import InviteSigner
from borrowd_users.models import BorrowdUser


class InviteLinkTests(TestCase):
    """
    Invite links are signed with the group's ID and invite code, so they
    survive renames and stop working when a moderator resets the code.
    """

    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create_user(
            username="moderator", email="moderator@example.com", password="password"
        )
        self.member = BorrowdUser.objects.create_user(
            username="member", email="member@example.com", password="password"
        )
        self.outsider = BorrowdUser.objects.create_user(
            username="outsider", email="outsider@example.com", password="password"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="Maple Street Neighbours",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=False,
        )
        self.group.add_user(self.member)
        self.invite_url = reverse("borrowd_groups:group-invite", args=[self.group.pk])
        self.reset_url = reverse(
            "borrowd_groups:reset-invite-link", args=[self.group.pk]
        )

    def join_path(self) -> str:
        """The join path from the invite page, as the moderator sees it."""
        self.client.force_login(self.moderator)
        join_url: str = self.client.get(self.invite_url).context["join_url"]
        return urlparse(join_url).path

    def legacy_join_path(self) -> str:
        """A link signed with the group name, before groups had invite codes."""
        encoded = InviteSigner.sign_invite(self.group.pk, self.group.name)
        return reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})

    def assert_link_works(self, path: str) -> None:
        self.client.force_login(self.outsider)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.group.name)

    def assert_link_invalid(self, path: str) -> None:
        self.client.force_login(self.outsider)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Invite link invalid", status_code=400)

    def reset(self) -> None:
        self.client.force_login(self.moderator)
        self.client.post(self.reset_url)
        self.group.refresh_from_db()

    def test_groups_get_distinct_invite_codes(self) -> None:
        other = BorrowdGroup.objects.create_group(
            name="Other", created_by=self.moderator, updated_by=self.moderator
        )
        self.assertTrue(self.group.invite_code)
        self.assertNotEqual(self.group.invite_code, other.invite_code)

    def test_link_survives_a_rename(self) -> None:
        path = self.join_path()

        self.group.name = "Maple Street Neighbors"
        self.group.save()

        self.assert_link_works(path)

    def test_reset_invalidates_old_link_and_new_link_works(self) -> None:
        old_path = self.join_path()
        old_code = self.group.invite_code

        self.reset()

        self.assertNotEqual(self.group.invite_code, old_code)
        self.assertIsNotNone(self.group.invite_code_reset_at)
        self.assertEqual(self.group.updated_by, self.moderator)
        self.assert_link_invalid(old_path)
        self.assert_link_works(self.join_path())

    def test_reset_redirects_to_invite_page_with_message(self) -> None:
        self.client.force_login(self.moderator)

        response = self.client.post(self.reset_url, follow=True)

        self.assertRedirects(response, self.invite_url)
        self.assertContains(response, "Invite link reset.")

    def test_reset_keeps_existing_members(self) -> None:
        self.reset()

        self.assertTrue(self.group.users.filter(pk=self.member.pk).exists())

    def test_member_who_is_not_a_moderator_cannot_reset(self) -> None:
        code = self.group.invite_code
        self.client.force_login(self.member)

        response = self.client.post(self.reset_url)

        self.assertEqual(response.status_code, 404)
        self.group.refresh_from_db()
        self.assertEqual(self.group.invite_code, code)

    def test_outsider_cannot_reset(self) -> None:
        self.client.force_login(self.outsider)

        self.assertEqual(self.client.post(self.reset_url).status_code, 404)

    def test_reset_requires_post(self) -> None:
        self.client.force_login(self.moderator)

        self.assertEqual(self.client.get(self.reset_url).status_code, 405)

    def test_reset_button_shows_only_for_moderators(self) -> None:
        self.client.force_login(self.moderator)
        self.assertContains(self.client.get(self.invite_url), self.reset_url)

        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(self.invite_url), self.reset_url)

    def test_legacy_name_link_works_until_first_reset(self) -> None:
        path = self.legacy_join_path()
        self.assert_link_works(path)

        self.reset()

        self.assert_link_invalid(path)

    def test_legacy_name_link_stops_working_after_a_rename(self) -> None:
        path = self.legacy_join_path()

        self.group.name = "Maple Street Neighbors"
        self.group.save()

        self.assert_link_invalid(path)

    def test_link_for_a_missing_group_is_invalid(self) -> None:
        encoded = InviteSigner.sign_invite(self.group.pk + 1000, "anything")

        self.assert_link_invalid(
            reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})
        )
