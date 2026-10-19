from django.test import TestCase
from django.urls import reverse

from borrowd_groups.exceptions import ModeratorRequiredException
from borrowd_groups.models import (
    BorrowdGroup,
    DepartureReason,
    Membership,
    MembershipDeparture,
    MembershipJoinMethod,
    MembershipStatus,
)
from borrowd_groups.views import InviteSigner
from borrowd_users.models import BorrowdUser


def _join_url_for(group: BorrowdGroup) -> str:
    encoded = InviteSigner.sign_invite(group.pk, group.name)
    return reverse("borrowd_groups:group-join", kwargs={"encoded": encoded})


class JoinMethodTests(TestCase):
    def setUp(self) -> None:
        self.creator = BorrowdUser.objects.create_user(
            username="jm_creator", password="password"
        )
        self.joiner = BorrowdUser.objects.create_user(
            username="jm_joiner", password="password"
        )

    def test_group_creation_records_group_creator(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Creator Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=False,
        )

        membership = Membership.objects.get(user=self.creator, group=group)

        self.assertEqual(membership.join_method, MembershipJoinMethod.GROUP_CREATOR)

    def test_invite_join_records_joined_group_when_approval_not_required(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Open Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=False,
        )

        self.client.force_login(self.joiner)
        self.client.post(_join_url_for(group))

        membership = Membership.objects.get(user=self.joiner, group=group)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.join_method, MembershipJoinMethod.JOINED_GROUP)

    def test_invite_join_records_joined_group_even_while_pending_approval(
        self,
    ) -> None:
        group = BorrowdGroup.objects.create(
            name="Private Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=True,
        )

        self.client.force_login(self.joiner)
        self.client.post(_join_url_for(group))

        membership = Membership.objects.get(user=self.joiner, group=group)
        self.assertEqual(membership.status, MembershipStatus.PENDING)
        self.assertEqual(membership.join_method, MembershipJoinMethod.JOINED_GROUP)

    def test_direct_add_user_call_also_records_joined_group(self) -> None:
        group = BorrowdGroup.objects.create(
            name="Direct Add Group",
            created_by=self.creator,
            updated_by=self.creator,
            membership_requires_approval=False,
        )

        membership = group.add_user(self.joiner)

        self.assertEqual(membership.join_method, MembershipJoinMethod.JOINED_GROUP)


class MembershipDepartureTests(TestCase):
    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create_user(
            username="dep_moderator", password="password"
        )
        self.member = BorrowdUser.objects.create_user(
            username="dep_member", password="password"
        )
        self.group = BorrowdGroup.objects.create(
            name="Departure Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=False,
        )
        self.member_membership = self.group.add_user(self.member)

    def test_leaving_writes_one_departure_row_with_no_remover(self) -> None:
        joined_at = self.member_membership.joined_at

        self.client.force_login(self.member)
        self.client.post(reverse("borrowd_groups:leave-group", args=[self.group.pk]))

        departures = list(
            MembershipDeparture.objects.filter(user=self.member, group=self.group)
        )
        self.assertEqual(len(departures), 1)
        departure = departures[0]
        self.assertEqual(departure.joined_at, joined_at)
        self.assertIsNone(departure.removed_by)
        self.assertEqual(departure.departure_reason, DepartureReason.LEFT_VOLUNTARILY)
        self.assertEqual(departure.username, self.member.username)
        self.assertEqual(departure.group_name, self.group.name)
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_moderator_removal_writes_one_departure_row_with_remover(self) -> None:
        joined_at = self.member_membership.joined_at

        self.client.force_login(self.moderator)
        self.client.post(
            reverse(
                "borrowd_groups:remove-member", args=[self.group.pk, self.member.pk]
            )
        )

        departures = list(
            MembershipDeparture.objects.filter(user=self.member, group=self.group)
        )
        self.assertEqual(len(departures), 1)
        departure = departures[0]
        self.assertEqual(departure.joined_at, joined_at)
        self.assertEqual(departure.removed_by, self.moderator)
        self.assertEqual(
            departure.departure_reason, DepartureReason.REMOVED_BY_MODERATOR
        )
        self.assertFalse(
            Membership.objects.filter(user=self.member, group=self.group).exists()
        )

    def test_failed_removal_leaves_no_departure_row_and_keeps_membership(self) -> None:
        # The group's only moderator can't be removed; remove_user() should
        # roll back the departure row it wrote right before the failed delete.
        with self.assertRaises(ModeratorRequiredException):
            self.group.remove_user(self.moderator)

        self.assertFalse(
            MembershipDeparture.objects.filter(
                user=self.moderator, group=self.group
            ).exists()
        )
        self.assertTrue(
            Membership.objects.filter(user=self.moderator, group=self.group).exists()
        )

    def test_denying_a_pending_request_does_not_write_a_departure_row(self) -> None:
        private_group = BorrowdGroup.objects.create(
            name="Deny Departure Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        requester = BorrowdUser.objects.create_user(
            username="dep_requester", password="password"
        )
        membership = private_group.add_user(requester)
        self.assertEqual(membership.status, MembershipStatus.PENDING)

        self.client.force_login(self.moderator)
        self.client.post(reverse("borrowd_groups:deny-member", args=[membership.pk]))

        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        self.assertFalse(
            MembershipDeparture.objects.filter(
                user=requester, group=private_group
            ).exists()
        )

    def test_departure_survives_hard_deletion_of_the_user(self) -> None:
        self.group.remove_user(self.member, bypass_last_moderator_check=True)
        departure = MembershipDeparture.objects.get(group=self.group)
        departed_username = self.member.username

        self.member.delete()

        departure.refresh_from_db()
        self.assertIsNone(departure.user)
        self.assertEqual(departure.username, departed_username)
        self.assertEqual(departure.group, self.group)

    def test_departure_survives_hard_deletion_of_the_group(self) -> None:
        self.group.remove_user(self.member, bypass_last_moderator_check=True)
        departure = MembershipDeparture.objects.get(user=self.member)
        group_name = self.group.name

        self.group.delete()

        departure.refresh_from_db()
        self.assertIsNone(departure.group)
        self.assertEqual(departure.group_name, group_name)
        self.assertEqual(departure.user, self.member)

    def test_cancelling_a_pending_request_does_not_write_a_departure_row(self) -> None:
        private_group = BorrowdGroup.objects.create(
            name="Cancel Departure Group",
            created_by=self.moderator,
            updated_by=self.moderator,
            membership_requires_approval=True,
        )
        requester = BorrowdUser.objects.create_user(
            username="dep_canceller", password="password"
        )
        membership = private_group.add_user(requester)
        self.assertEqual(membership.status, MembershipStatus.PENDING)

        self.client.force_login(requester)
        self.client.post(
            reverse("borrowd_groups:cancel-membership-request", args=[private_group.pk])
        )

        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        self.assertFalse(
            MembershipDeparture.objects.filter(
                user=requester, group=private_group
            ).exists()
        )
