from django.test import TestCase
from django.urls import reverse

from borrowd_groups.forms import GroupCreateForm, GroupUpdateForm
from borrowd_groups.models import BorrowdGroup, MembershipStatus
from borrowd_users.models import BorrowdUser


class InviteLinkSharingTests(TestCase):
    """
    Moderators can always share a group's invite link and poster. Other
    active members can unless the group requires approval to join and
    `members_can_share_invite_link` is off.
    """

    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create_user(
            username="moderator", email="moderator@example.com", password="password"
        )
        self.member = BorrowdUser.objects.create_user(
            username="member", email="member@example.com", password="password"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="Maple Street Neighbours",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        membership = self.group.add_user(self.member)
        membership.status = MembershipStatus.ACTIVE
        membership.save()
        self.share_urls = [
            reverse("borrowd_groups:group-invite", args=[self.group.pk]),
            reverse("borrowd_groups:group-poster", args=[self.group.pk]),
        ]
        self.detail_url = reverse("borrowd_groups:group-detail", args=[self.group.pk])

    def configure(self, *, requires_approval: bool, members_can_share: bool) -> None:
        self.group.membership_requires_approval = requires_approval
        self.group.members_can_share_invite_link = members_can_share
        self.group.save()

    def assert_can_share(self, user: BorrowdUser, expected: bool) -> None:
        self.client.force_login(user)
        for url in self.share_urls:
            with self.subTest(url=url):
                status = self.client.get(url).status_code
                self.assertEqual(status, 200 if expected else 404)
        detail = self.client.get(self.detail_url)
        if expected:
            self.assertContains(detail, self.share_urls[0])
        else:
            self.assertNotContains(detail, self.share_urls[0])

    def test_members_can_share_by_default(self) -> None:
        self.assertTrue(self.group.members_can_share_invite_link)
        self.assert_can_share(self.member, True)

    def test_turning_it_off_limits_sharing_to_moderators(self) -> None:
        self.configure(requires_approval=True, members_can_share=False)

        self.assert_can_share(self.member, False)
        self.assert_can_share(self.moderator, True)

    def test_setting_is_ignored_when_anyone_can_join(self) -> None:
        self.configure(requires_approval=False, members_can_share=False)

        self.assert_can_share(self.member, True)

    def test_only_the_edit_form_has_the_setting(self) -> None:
        self.assertIn("members_can_share_invite_link", GroupUpdateForm().fields)
        self.assertNotIn("members_can_share_invite_link", GroupCreateForm().fields)

    def test_moderator_turns_it_off_from_the_edit_page(self) -> None:
        self.client.force_login(self.moderator)
        edit_url = reverse("borrowd_groups:group-edit", args=[self.group.pk])

        page = self.client.get(edit_url)
        self.assertContains(page, "Group members can share invitation links")
        self.assertContains(page, 'x-show="requiresApproval"')

        self.client.post(
            edit_url,
            {
                "name": self.group.name,
                "description": "",
                "membership_requires_approval": "on",
                # Unticked checkboxes are absent from the POST.
            },
        )

        self.group.refresh_from_db()
        self.assertFalse(self.group.members_can_share_invite_link)
        self.assert_can_share(self.member, False)
