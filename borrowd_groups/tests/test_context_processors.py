from unittest.mock import PropertyMock, patch

from django.test import RequestFactory, TestCase

from borrowd_groups.context_processors import groups_needing_moderator
from borrowd_groups.models import BorrowdGroup, Membership
from borrowd_users.models import BorrowdUser


class GroupsNeedingModeratorContextProcessorTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(username="owner")
        self.member = BorrowdUser.objects.create_user(username="member")
        self.factory = RequestFactory()

    def test_reports_group_needing_moderator_without_property_lookup(self) -> None:
        group = BorrowdGroup.objects.create_group(
            name="Test Group",
            created_by=self.owner,
            updated_by=self.owner,
            membership_requires_approval=False,
        )
        group.add_user(self.member)
        Membership.objects.filter(user=self.owner, group=group).update(
            is_moderator=False
        )

        request = self.factory.get("/")
        request.user = self.member

        with patch.object(
            BorrowdGroup,
            "needs_moderator",
            new_callable=PropertyMock,
            side_effect=AssertionError("context processor should use an EXISTS query"),
        ):
            context = groups_needing_moderator(request)

        self.assertEqual(context, {"has_groups_needing_moderator": True})
