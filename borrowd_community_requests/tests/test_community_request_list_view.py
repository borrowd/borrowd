from typing import Any

from django.test import RequestFactory, TestCase
from django.urls import reverse

from borrowd_community_requests.context_processors import community_request_count
from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import ItemCategory
from borrowd_users.models import BorrowdUser


def _requests(cards: list[dict[str, Any]]) -> list[CommunityRequest]:
    return [card["request"] for card in cards]


class CommunityRequestListViewTestBase(TestCase):
    requester: BorrowdUser
    group_member: BorrowdUser
    outsider: BorrowdUser
    category_tools: ItemCategory
    group: BorrowdGroup

    @classmethod
    def setUpTestData(cls) -> None:
        cls.requester = BorrowdUser.objects.create(
            username="requester", email="requester@example.com"
        )
        cls.group_member = BorrowdUser.objects.create(
            username="group_member", email="group_member@example.com"
        )
        cls.outsider = BorrowdUser.objects.create(
            username="outsider", email="outsider@example.com"
        )
        cls.category_tools = ItemCategory.objects.create(name="Tools")

        cls.group = BorrowdGroup.objects.create_group(
            name="Shared Group",
            created_by=cls.requester,
            updated_by=cls.requester,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.group_member)


class CommunityRequestListViewTabTests(CommunityRequestListViewTestBase):
    def setUp(self) -> None:
        self.client.force_login(self.group_member)

    def test_default_tab_is_all_requests(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        response = self.client.get(reverse("community-request-list"))

        self.assertEqual(response.context["active_tab"], "all")
        self.assertIn(request, _requests(response.context["community_requests"]))

    def test_all_tab_shows_requests_visible_to_the_user(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "all"})

        self.assertIn(request, _requests(response.context["community_requests"]))

    def test_all_tab_excludes_the_viewers_own_requests(self) -> None:
        own_request = CommunityRequest.objects.create(
            requester=self.group_member,
            category=self.category_tools,
            item_name="Ladder",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "all"})

        self.assertNotIn(own_request, _requests(response.context["community_requests"]))

    def test_mine_tab_shows_only_the_viewers_own_requests(self) -> None:
        own_request = CommunityRequest.objects.create(
            requester=self.group_member,
            category=self.category_tools,
            item_name="Ladder",
        )
        other_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "mine"})

        self.assertEqual(response.context["active_tab"], "mine")
        requests = _requests(response.context["community_requests"])
        self.assertIn(own_request, requests)
        self.assertNotIn(other_request, requests)

    def test_mine_tab_excludes_cancelled_requests(self) -> None:
        cancelled_request = CommunityRequest.objects.create(
            requester=self.group_member,
            category=self.category_tools,
            item_name="Ladder",
            status=CommunityRequestStatus.CANCELLED,
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "mine"})

        self.assertNotIn(
            cancelled_request, _requests(response.context["community_requests"])
        )

    def test_unrecognized_tab_value_falls_back_to_all(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "bogus"})

        self.assertEqual(response.context["active_tab"], "all")
        self.assertIn(request, _requests(response.context["community_requests"]))


class CommunityRequestListViewVisibilityTests(CommunityRequestListViewTestBase):
    def test_user_in_no_shared_group_sees_nothing(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        self.client.force_login(self.outsider)
        response = self.client.get(reverse("community-request-list"))

        self.assertEqual(len(response.context["community_requests"]), 0)

    def test_user_in_a_shared_group_sees_the_request(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        self.client.force_login(self.group_member)
        response = self.client.get(reverse("community-request-list"))

        self.assertIn(request, _requests(response.context["community_requests"]))

    def test_a_user_who_dismissed_a_request_does_not_see_it_again(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        request.dismissals.create(user=self.group_member)

        self.client.force_login(self.group_member)
        response = self.client.get(reverse("community-request-list"))

        self.assertNotIn(request, _requests(response.context["community_requests"]))


class CommunityRequestListViewOrderingTests(CommunityRequestListViewTestBase):
    def setUp(self) -> None:
        self.client.force_login(self.group_member)

    def test_all_tab_is_ordered_newest_first(self) -> None:
        older = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        newer = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Ladder",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "all"})

        community_requests = _requests(response.context["community_requests"])
        self.assertEqual(community_requests, [newer, older])

    def test_mine_tab_is_ordered_newest_first(self) -> None:
        self.client.force_login(self.requester)
        older = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        newer = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Ladder",
        )

        response = self.client.get(reverse("community-request-list"), {"tab": "mine"})

        community_requests = _requests(response.context["community_requests"])
        self.assertEqual(community_requests, [newer, older])


class CommunityRequestListViewEmptyStateTests(CommunityRequestListViewTestBase):
    def setUp(self) -> None:
        self.client.force_login(self.group_member)

    def test_empty_state_copy_renders_when_all_tab_has_no_requests(self) -> None:
        response = self.client.get(reverse("community-request-list"), {"tab": "all"})

        self.assertContains(response, "There are no community requests right now.")

    def test_empty_state_copy_renders_when_mine_tab_has_no_requests(self) -> None:
        response = self.client.get(reverse("community-request-list"), {"tab": "mine"})

        self.assertContains(response, "There are no community requests right now.")


class CommunityRequestGetAbsoluteUrlTests(CommunityRequestListViewTestBase):
    def test_get_absolute_url_resolves_to_the_list_view(self) -> None:
        request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        self.assertEqual(request.get_absolute_url(), reverse("community-request-list"))


class CommunityRequestCountContextProcessorTests(CommunityRequestListViewTestBase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_returns_the_correct_count(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Ladder",
        )

        request = self.factory.get("/")
        request.user = self.group_member

        self.assertEqual(community_request_count(request)["community_request_count"], 2)

    def test_returns_empty_dict_for_anonymous_users(self) -> None:
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/")
        request.user = AnonymousUser()

        self.assertEqual(community_request_count(request), {})

    def test_excludes_the_viewers_own_requests(self) -> None:
        CommunityRequest.objects.create(
            requester=self.group_member,
            category=self.category_tools,
            item_name="Ladder",
        )

        request = self.factory.get("/")
        request.user = self.group_member

        self.assertEqual(community_request_count(request)["community_request_count"], 0)

    def test_count_updates_after_a_dismiss(self) -> None:
        community_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        request = self.factory.get("/")
        request.user = self.group_member
        self.assertEqual(community_request_count(request)["community_request_count"], 1)

        community_request.dismissals.create(user=self.group_member)

        self.assertEqual(community_request_count(request)["community_request_count"], 0)

    def test_count_updates_after_a_cancel(self) -> None:
        community_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
        )

        request = self.factory.get("/")
        request.user = self.group_member
        self.assertEqual(community_request_count(request)["community_request_count"], 1)

        community_request.cancel()

        self.assertEqual(community_request_count(request)["community_request_count"], 0)
