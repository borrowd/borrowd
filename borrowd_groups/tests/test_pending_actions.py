from django.test import TestCase

from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_groups.views import get_memberships_with_pending_actions
from borrowd_users.models import BorrowdUser


class GetMembershipsWithPendingActionsTests(TestCase):
    def setUp(self) -> None:
        self.moderator = BorrowdUser.objects.create(
            username="moderator", email="moderator@example.com"
        )
        self.member = BorrowdUser.objects.create(
            username="member", email="member@example.com"
        )
        self.requester = BorrowdUser.objects.create(
            username="requester", email="requester@example.com"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=self.moderator,
            updated_by=self.moderator,
        )

    def _moderator_memberships(self) -> list[Membership]:
        return list(Membership.objects.filter(user=self.moderator))

    def test_moderator_sees_group_with_pending_request(self) -> None:
        """
        A group where the user is a moderator and a pending membership request
        exists should be included in the result.
        """
        # The requester joins — approval required, so status is PENDING
        self.group.membership_requires_approval = True
        self.group.save()
        self.group.add_user(self.requester)

        memberships = self._moderator_memberships()
        result = get_memberships_with_pending_actions(memberships)

        self.assertIn(self.group.pk, result)

    def test_group_without_pending_requests_not_included(self) -> None:
        """
        A group with no pending membership requests should not appear in the
        returned set, even if the user is a moderator.
        """
        # Disable approval requirement so the new member is ACTIVE immediately
        self.group.membership_requires_approval = False
        self.group.save()
        self.group.add_user(self.member)

        memberships = self._moderator_memberships()
        result = get_memberships_with_pending_actions(memberships)

        self.assertNotIn(self.group.pk, result)

    def test_non_moderator_does_not_see_pending_actions(self) -> None:
        """
        A regular member should not get any pending action group IDs back,
        even if there are pending requests in the group.
        """
        self.group.membership_requires_approval = True
        self.group.save()
        self.group.add_user(self.member)
        self.group.add_user(self.requester)

        member_memberships = list(Membership.objects.filter(user=self.member))
        result = get_memberships_with_pending_actions(member_memberships)

        self.assertEqual(result, set())

    def test_approved_memberships_are_not_counted_as_pending(self) -> None:
        """
        A membership with ACTIVE status should not contribute to pending action
        group IDs.
        """
        self.group.add_user(self.requester)
        # Ensure the requester's membership is ACTIVE, not PENDING
        Membership.objects.filter(user=self.requester, group=self.group).update(
            status=MembershipStatus.ACTIVE
        )

        memberships = self._moderator_memberships()
        result = get_memberships_with_pending_actions(memberships)

        self.assertNotIn(self.group.pk, result)

    def test_non_pending_statuses_are_not_counted_as_pending(self) -> None:
        """
        Memberships with ENDED or SUSPENDED status should not contribute to
        pending action group IDs.
        """
        self.group.membership_requires_approval = True
        self.group.save()
        self.group.add_user(self.requester)
        Membership.objects.filter(user=self.requester, group=self.group).update(
            status=MembershipStatus.ENDED
        )

        memberships = self._moderator_memberships()
        result = get_memberships_with_pending_actions(memberships)

        self.assertNotIn(self.group.pk, result)

    def test_only_moderated_groups_are_returned(self) -> None:
        """
        Pending requests in a group the user does not moderate should not be
        returned.
        """
        other_moderator = BorrowdUser.objects.create(
            username="other_mod", email="other_mod@example.com"
        )
        other_group = BorrowdGroup.objects.create_group(
            name="Other Group",
            created_by=other_moderator,
            updated_by=other_moderator,
            membership_requires_approval=True,
        )
        # self.moderator is a plain member in other_group
        other_group.add_user(self.moderator)
        # requester has a pending request in other_group
        other_group.add_user(self.requester)

        # Memberships for self.moderator across both groups
        memberships = list(Membership.objects.filter(user=self.moderator))
        result = get_memberships_with_pending_actions(memberships)

        # self.group has no pending requests — should not be in result
        self.assertNotIn(self.group.pk, result)
        # other_group has a pending request, but self.moderator is not a moderator there
        self.assertNotIn(other_group.pk, result)

    def test_empty_memberships_returns_empty_set(self) -> None:
        """
        Passing an empty list should return an empty set without errors.
        """
        result = get_memberships_with_pending_actions([])
        self.assertEqual(result, set())
