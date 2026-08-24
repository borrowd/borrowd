from django.test import TestCase
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_groups.views import InviteSigner
from borrowd_items.models import Item
from borrowd_permissions.models import BorrowdGroupOLP, ItemOLP
from borrowd_users.models import BorrowdUser


class MembershipApprovalFlowTests(TestCase):
    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create_user(
            username="moderator", password="password"
        )
        self.requester = BorrowdUser.objects.create_user(
            username="requester", password="password"
        )

    def _join_url_for(self, group: BorrowdGroup) -> str:
        encoded = InviteSigner.sign_invite(group.pk, group.name)
        return reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})

    def test_private_group_join_creates_pending_membership_and_blocks_access(
        self,
    ) -> None:
        group = BorrowdGroup.objects.create(
            name="Private Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )

        self.client.force_login(self.requester)
        response = self.client.post(self._join_url_for(group))

        membership = Membership.objects.get(user=self.requester, group=group)

        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertEqual(membership.status, MembershipStatus.PENDING)
        self.assertFalse(self.requester.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertEqual(
            self.client.get(
                reverse("borrowd_groups:group-detail", args=[group.pk])
            ).status_code,
            403,
        )

    def test_private_group_creator_stays_active_moderator(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Moderator Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )

        group_creator_membership = Membership.objects.get(
            user=self.moderator,
            group=group,
        )

        self.assertEqual(group_creator_membership.status, MembershipStatus.ACTIVE)
        self.assertTrue(group_creator_membership.is_moderator)
        self.assertTrue(self.moderator.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertTrue(self.moderator.has_perm(BorrowdGroupOLP.EDIT, group))
        self.assertTrue(self.moderator.has_perm(BorrowdGroupOLP.DELETE, group))

    def test_non_private_group_still_auto_joins(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Public Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=False,
        )

        self.client.force_login(self.requester)
        response = self.client.post(self._join_url_for(group))

        membership = Membership.objects.get(user=self.requester, group=group)

        self.assertRedirects(
            response, reverse("borrowd_groups:group-detail", args=[group.pk])
        )
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertTrue(self.requester.has_perm(BorrowdGroupOLP.VIEW, group))

    def test_moderator_can_approve_pending_and_grant_group_and_item_access(
        self,
    ) -> None:
        group = BorrowdGroup.objects.create(
            name="Approval Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        item = Item.objects.create(
            name="Shared Item",
            owner=self.moderator,
            created_by=self.moderator,
            updated_by=self.moderator,
        )
        membership = group.add_user(self.requester)

        self.client.force_login(self.moderator)
        response = self.client.post(
            reverse("borrowd_groups:approve-member", args=[membership.pk])
        )

        membership.refresh_from_db()

        self.assertRedirects(
            response, reverse("borrowd_groups:group-detail", args=[group.pk])
        )
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertTrue(self.requester.has_perm(BorrowdGroupOLP.VIEW, group))
        self.assertTrue(self.requester.has_perm(ItemOLP.VIEW, item))

    def test_moderator_can_deny_pending_and_remove_membership(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Deny Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        membership = group.add_user(self.requester)

        self.client.force_login(self.moderator)
        response = self.client.post(
            reverse("borrowd_groups:deny-member", args=[membership.pk])
        )

        self.assertRedirects(
            response, reverse("borrowd_groups:group-detail", args=[group.pk])
        )
        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        self.assertFalse(self.requester.has_perm(BorrowdGroupOLP.VIEW, group))

    def test_non_moderator_gets_403_on_approve_and_deny(self) -> None:
        helper = BorrowdUser.objects.create_user(username="helper", password="password")
        group = BorrowdGroup.objects.create(
            name="Guarded Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        BorrowdGroup.objects.filter(pk=group.pk).update(
            membership_requires_approval=False
        )
        group.refresh_from_db()
        group.add_user(helper)
        BorrowdGroup.objects.filter(pk=group.pk).update(
            membership_requires_approval=True
        )
        group.refresh_from_db()
        membership = group.add_user(self.requester)

        self.client.force_login(helper)

        approve_response = self.client.post(
            reverse("borrowd_groups:approve-member", args=[membership.pk])
        )
        deny_response = self.client.post(
            reverse("borrowd_groups:deny-member", args=[membership.pk])
        )

        membership.refresh_from_db()

        self.assertEqual(approve_response.status_code, 403)
        self.assertEqual(deny_response.status_code, 403)
        self.assertEqual(membership.status, MembershipStatus.PENDING)

    def test_only_moderators_get_pending_members_in_group_detail_context(self) -> None:
        active_member = BorrowdUser.objects.create_user(
            username="active_member", password="password"
        )
        pending_user = BorrowdUser.objects.create_user(
            username="pending_user", password="password"
        )

        group = BorrowdGroup.objects.create(
            name="Context Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=False,
        )
        group.add_user(active_member)
        pending_membership = Membership.objects.create(
            user=pending_user,
            group=group,
            status=MembershipStatus.PENDING,
            is_moderator=False,
        )

        self.client.force_login(self.moderator)
        moderator_response = self.client.get(
            reverse("borrowd_groups:group-detail", args=[group.pk])
        )

        self.client.force_login(active_member)
        member_response = self.client.get(
            reverse("borrowd_groups:group-detail", args=[group.pk])
        )

        self.assertEqual(moderator_response.status_code, 200)
        self.assertIn("pending_members", moderator_response.context)
        self.assertIn(
            pending_membership,
            list(moderator_response.context["pending_members"]),
        )

        self.assertEqual(member_response.status_code, 200)
        self.assertNotIn("pending_members", member_response.context)


class CancelMembershipRequestTests(TestCase):
    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create_user(
            username="cancel_moderator", password="password"
        )
        self.requester = BorrowdUser.objects.create_user(
            username="cancel_requester", password="password"
        )
        self.group = BorrowdGroup.objects.create(
            name="Cancel Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )

    def _cancel_url(self) -> str:
        return reverse("borrowd_groups:cancel-membership-request", args=[self.group.pk])

    def test_requester_can_cancel_their_own_pending_request(self) -> None:
        membership = self.group.add_user(self.requester)
        self.assertEqual(membership.status, MembershipStatus.PENDING)

        self.client.force_login(self.requester)
        response = self.client.post(self._cancel_url(), follow=True)

        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("Your request has been cancelled.", messages_list)

    def test_cancelling_does_not_affect_other_pending_requesters(self) -> None:
        other_requester = BorrowdUser.objects.create_user(
            username="cancel_other_requester", password="password"
        )
        membership = self.group.add_user(self.requester)
        other_membership = self.group.add_user(other_requester)

        self.client.force_login(self.requester)
        self.client.post(self._cancel_url())

        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        other_membership.refresh_from_db()
        self.assertEqual(other_membership.status, MembershipStatus.PENDING)

    def test_cancel_requires_login(self) -> None:
        self.group.add_user(self.requester)

        response = self.client.post(self._cancel_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

    def test_cancel_404s_for_a_nonexistent_group(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("borrowd_groups:cancel-membership-request", args=[999999])
        )

        self.assertEqual(response.status_code, 404)

    def test_user_without_a_pending_request_gets_an_error_message(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(self._cancel_url(), follow=True)

        self.assertRedirects(response, reverse("borrowd_groups:group-list"))
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("You don't have a pending request for this group.", messages_list)

    def test_active_member_cannot_cancel_their_active_membership_via_this_view(
        self,
    ) -> None:
        active_member = BorrowdUser.objects.create_user(
            username="cancel_active_member", password="password"
        )
        BorrowdGroup.objects.filter(pk=self.group.pk).update(
            membership_requires_approval=False
        )
        self.group.refresh_from_db()
        membership = self.group.add_user(active_member)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

        self.client.force_login(active_member)
        response = self.client.post(
            reverse("borrowd_groups:cancel-membership-request", args=[self.group.pk]),
            follow=True,
        )

        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("You don't have a pending request for this group.", messages_list)
        self.assertTrue(Membership.objects.filter(pk=membership.pk).exists())
