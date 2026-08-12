from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from borrowd_community_requests.models import (
    MAX_ACTIVE_REQUESTS_PER_USER,
    CommunityRequest,
    CommunityRequestDismissal,
    CommunityRequestStatus,
)
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import ItemCategory
from borrowd_users.models import BorrowdUser


class CommunityRequestModelTestBase(TestCase):
    """Base class with shared users/categories for community request tests."""

    requester: BorrowdUser
    other_member: BorrowdUser
    outsider: BorrowdUser
    category_tools: ItemCategory
    category_electronics: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        cls.requester = BorrowdUser.objects.create(
            username="requester", email="requester@example.com"
        )
        cls.other_member = BorrowdUser.objects.create(
            username="other_member", email="other_member@example.com"
        )
        cls.outsider = BorrowdUser.objects.create(
            username="outsider", email="outsider@example.com"
        )
        cls.category_tools = ItemCategory.objects.create(name="Tools")
        cls.category_electronics = ItemCategory.objects.create(name="Electronics")


class CommunityRequestCleanTests(CommunityRequestModelTestBase):
    def _make_group_with_active_membership(self, user: BorrowdUser) -> BorrowdGroup:
        group = BorrowdGroup.objects.create_group(
            name=f"{user.username}'s Group",
            created_by=user,
            updated_by=user,
        )
        return group

    def test_clean_raises_when_requester_has_no_active_group_membership(
        self,
    ) -> None:
        request = CommunityRequest(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        with self.assertRaises(ValidationError):
            request.clean()

    def test_clean_passes_when_requester_has_active_group_membership(self) -> None:
        self._make_group_with_active_membership(self.requester)

        request = CommunityRequest(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        # Should not raise.
        request.clean()

    def test_clean_enforces_max_active_requests_per_user(self) -> None:
        self._make_group_with_active_membership(self.requester)

        for i in range(MAX_ACTIVE_REQUESTS_PER_USER):
            CommunityRequest.objects.create(
                requester=self.requester,
                category=self.category_tools,
                item_name=f"Item {i}",
                status=CommunityRequestStatus.OPEN,
            )

        over_the_cap = CommunityRequest(
            requester=self.requester,
            category=self.category_tools,
            item_name="One too many",
        )

        with self.assertRaises(ValidationError):
            over_the_cap.clean()

    def test_clean_ignores_cancelled_requests_when_counting_the_cap(self) -> None:
        self._make_group_with_active_membership(self.requester)

        for i in range(MAX_ACTIVE_REQUESTS_PER_USER):
            CommunityRequest.objects.create(
                requester=self.requester,
                category=self.category_tools,
                item_name=f"Cancelled item {i}",
                status=CommunityRequestStatus.CANCELLED,
            )

        under_the_cap = CommunityRequest(
            requester=self.requester,
            category=self.category_tools,
            item_name="Still allowed",
        )

        # Should not raise: cancelled requests don't count toward the cap.
        under_the_cap.clean()

    def test_clean_excludes_own_pk_when_re_validating_an_existing_request(
        self,
    ) -> None:
        self._make_group_with_active_membership(self.requester)

        for i in range(MAX_ACTIVE_REQUESTS_PER_USER):
            CommunityRequest.objects.create(
                requester=self.requester,
                category=self.category_tools,
                item_name=f"Item {i}",
                status=CommunityRequestStatus.OPEN,
            )

        existing = CommunityRequest.objects.filter(requester=self.requester).first()
        assert existing is not None

        # Re-validating an already-saved, already-counted request should not
        # trip the cap against itself.
        existing.clean()


class CommunityRequestUniqueConstraintTests(CommunityRequestModelTestBase):
    def test_duplicate_open_request_violates_db_constraint(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            CommunityRequest.objects.create(
                requester=self.requester,
                category=self.category_tools,
                item_name="Drill",
                status=CommunityRequestStatus.OPEN,
            )

    def test_duplicate_cancelled_request_does_not_violate_db_constraint(
        self,
    ) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.CANCELLED,
        )

        # Should not raise: the unique constraint only applies to OPEN requests.
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.CANCELLED,
        )

    def test_same_item_name_different_category_does_not_violate_constraint(
        self,
    ) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        # Should not raise: category differs, so it's a distinct request.
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_electronics,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )


class CommunityRequestVisibleToTests(CommunityRequestModelTestBase):
    def setUp(self) -> None:
        self.group = BorrowdGroup.objects.create_group(
            name="Shared Group",
            created_by=self.requester,
            updated_by=self.requester,
            membership_requires_approval=False,
        )
        self.group.add_user(self.other_member)

    def test_visible_to_includes_requests_from_shared_group_members(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        visible = CommunityRequest.objects.visible_to(self.other_member)

        self.assertIn(request, visible)

    def test_visible_to_includes_the_requesters_own_requests(self) -> None:
        """
        The requester sees their own open requests via visible_to() too — later
        phases (e.g. the community requests feed) rely on this exact behavior.
        """
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        visible = CommunityRequest.objects.visible_to(self.requester)

        self.assertIn(request, visible)

    def test_visible_to_excludes_requests_from_users_outside_shared_groups(
        self,
    ) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        visible = CommunityRequest.objects.visible_to(self.outsider)

        self.assertNotIn(request, visible)

    def test_visible_to_excludes_dismissed_requests(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        CommunityRequestDismissal.objects.create(
            request=request, user=self.other_member
        )

        visible = CommunityRequest.objects.visible_to(self.other_member)

        self.assertNotIn(request, visible)

    def test_visible_to_excludes_cancelled_requests(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.CANCELLED,
        )

        visible = CommunityRequest.objects.visible_to(self.other_member)

        self.assertNotIn(request, visible)

    def test_visible_to_excludes_requests_from_a_group_the_viewer_left(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        self.group.remove_user(self.other_member)

        visible = CommunityRequest.objects.visible_to(self.other_member)

        self.assertNotIn(request, visible)


class CommunityRequestOwnedByTests(CommunityRequestModelTestBase):
    def test_owned_by_returns_only_the_given_users_requests(self) -> None:
        own_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        CommunityRequest.objects.create(
            requester=self.other_member,
            category=self.category_tools,
            item_name="Ladder",
        )

        owned = CommunityRequest.objects.owned_by(self.requester)

        self.assertIn(own_request, owned)
        self.assertEqual(owned.count(), 1)

    def test_owned_by_returns_requests_of_every_status(self) -> None:
        open_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )
        cancelled_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_electronics,
            item_name="Ladder",
            status=CommunityRequestStatus.CANCELLED,
        )

        owned = CommunityRequest.objects.owned_by(self.requester)

        self.assertIn(open_request, owned)
        self.assertIn(cancelled_request, owned)
