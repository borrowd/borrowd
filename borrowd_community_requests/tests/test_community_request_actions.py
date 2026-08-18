from typing import Any

from django.test import TestCase
from django.urls import reverse

from borrowd_community_requests.exceptions import CannotActOnOwnRequestException
from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


def _requests(cards: list[dict[str, Any]]) -> list[CommunityRequest]:
    return [card["request"] for card in cards]


class CommunityRequestActionsTestBase(TestCase):
    """Base class with shared users/categories/groups for lender-action tests."""

    requester: BorrowdUser
    lender: BorrowdUser
    other_lender: BorrowdUser
    category: ItemCategory
    group: BorrowdGroup

    @classmethod
    def setUpTestData(cls) -> None:
        cls.requester = BorrowdUser.objects.create_user(
            username="requester", email="requester@example.com", password="password"
        )
        cls.lender = BorrowdUser.objects.create_user(
            username="lender", email="lender@example.com", password="password"
        )
        cls.other_lender = BorrowdUser.objects.create_user(
            username="other_lender",
            email="other_lender@example.com",
            password="password",
        )
        cls.category = ItemCategory.objects.create(name="Tools")

        cls.group = BorrowdGroup.objects.create_group(
            name="Shared Group",
            created_by=cls.requester,
            updated_by=cls.requester,
            membership_requires_approval=False,
        )
        cls.group.add_user(cls.lender)
        cls.group.add_user(cls.other_lender)

    def _make_item(self, owner: BorrowdUser, name: str = "Drill") -> Item:
        item = Item.objects.create(
            name=name,
            description="A description",
            owner=owner,
            created_by=owner,
            updated_by=owner,
        )
        item.categories.add(self.category)
        return item

    def _make_request(self) -> CommunityRequest:
        return CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category,
            item_name="Drill",
        )


class AddResponseTests(CommunityRequestActionsTestBase):
    def test_add_response_creates_a_response(self) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)

        response = community_request.add_response(item)

        self.assertIsNotNone(response)
        assert response is not None  # narrows for mypy
        self.assertEqual(response.request, community_request)
        self.assertEqual(response.item, item)
        self.assertTrue(community_request.responses.filter(item=item).exists())

    def test_add_response_allows_multiple_lenders_to_respond(self) -> None:
        """The request stays OPEN and accepts responses from any number of
        lenders — there is no single-slot "already fulfilled" limit."""
        community_request = self._make_request()
        first_item = self._make_item(self.lender, name="First drill")
        second_item = self._make_item(self.other_lender, name="Second drill")

        first_response = community_request.add_response(first_item)
        second_response = community_request.add_response(second_item)

        self.assertIsNotNone(first_response)
        self.assertIsNotNone(second_response)
        self.assertEqual(community_request.responses.count(), 2)
        self.assertEqual(
            set(community_request.responses.values_list("item", flat=True)),
            {first_item.pk, second_item.pk},
        )

    def test_add_response_is_idempotent_for_the_same_item(self) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)

        community_request.add_response(item)
        community_request.add_response(item)

        self.assertEqual(community_request.responses.filter(item=item).count(), 1)

    def test_add_response_allows_concurrent_responses_from_different_lenders(
        self,
    ) -> None:
        """Two lenders submitting "Add Item" for the same request at nearly
        the same time both succeed — each response is independent, unlike
        the old single-FK "first wins" behavior."""
        community_request = self._make_request()
        first_item = self._make_item(self.lender, name="First drill")
        second_item = self._make_item(self.other_lender, name="Second drill")

        # Two independently-fetched copies, standing in for two concurrent
        # request-handling processes.
        first_lenders_copy = CommunityRequest.objects.get(pk=community_request.pk)
        second_lenders_copy = CommunityRequest.objects.get(pk=community_request.pk)

        first_result = first_lenders_copy.add_response(first_item)
        second_result = second_lenders_copy.add_response(second_item)

        self.assertIsNotNone(first_result)
        self.assertIsNotNone(second_result)
        self.assertEqual(community_request.responses.count(), 2)

    def test_add_response_rejects_a_response_concurrent_with_a_cancel(self) -> None:
        """A request cancelled concurrently with an incoming response still
        correctly rejects that response — the locked re-check is on
        status == OPEN, not on any per-response state."""
        community_request = self._make_request()
        item = self._make_item(self.lender)

        # Simulates the request being cancelled by the requester in another
        # process just before the lender's response is processed.
        community_request.cancel()

        result = community_request.add_response(item)

        self.assertIsNone(result)
        self.assertEqual(community_request.responses.count(), 0)

    def test_add_response_raises_when_requester_tries_to_fulfill_own_request(
        self,
    ) -> None:
        community_request = self._make_request()
        own_item = self._make_item(self.requester)

        with self.assertRaises(CannotActOnOwnRequestException):
            community_request.add_response(own_item)

        self.assertEqual(community_request.responses.count(), 0)

    def test_add_response_is_a_no_op_on_a_cancelled_request(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        item = self._make_item(self.lender)

        result = community_request.add_response(item)

        self.assertIsNone(result)
        self.assertEqual(community_request.responses.count(), 0)


class DismissForTests(CommunityRequestActionsTestBase):
    def test_dismiss_for_creates_a_dismissal(self) -> None:
        community_request = self._make_request()

        community_request.dismiss_for(self.lender)

        self.assertTrue(community_request.dismissals.filter(user=self.lender).exists())

    def test_dismiss_for_is_idempotent(self) -> None:
        community_request = self._make_request()

        community_request.dismiss_for(self.lender)
        community_request.dismiss_for(self.lender)

        self.assertEqual(
            community_request.dismissals.filter(user=self.lender).count(), 1
        )

    def test_dismiss_for_raises_when_requester_dismisses_own_request(self) -> None:
        community_request = self._make_request()

        with self.assertRaises(CannotActOnOwnRequestException):
            community_request.dismiss_for(self.requester)

        self.assertFalse(
            community_request.dismissals.filter(user=self.requester).exists()
        )


class CommunityRequestDismissViewTests(CommunityRequestActionsTestBase):
    def test_dismiss_creates_a_dismissal_and_redirects_with_success_message(
        self,
    ) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("community-request-list"))
        self.assertTrue(community_request.dismissals.filter(user=self.lender).exists())
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("Request hidden.", messages_list)

    def test_dismiss_is_idempotent_on_double_submit(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)

        url = reverse("community-request-dismiss", args=[community_request.pk])
        self.client.post(url)
        self.client.post(url)

        self.assertEqual(
            community_request.dismissals.filter(user=self.lender).count(), 1
        )

    def test_dismiss_404s_for_a_nonexistent_pk(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(reverse("community-request-dismiss", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_dismiss_404s_for_a_cancelled_request(self) -> None:
        community_request = self._make_request()
        community_request.status = CommunityRequestStatus.CANCELLED
        community_request.save(update_fields=["status"])
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_dismiss_handles_self_dismissal_without_a_500(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("community-request-list"))
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("You can't hide your own request.", messages_list)
        self.assertFalse(
            community_request.dismissals.filter(user=self.requester).exists()
        )


class DismissedRequestVisibilityTests(CommunityRequestActionsTestBase):
    def test_dismissed_request_disappears_from_the_dismissing_users_requests_tab(
        self,
    ) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)
        self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        response = self.client.get(reverse("community-request-list"))

        self.assertNotIn(
            community_request, _requests(response.context["community_requests"])
        )

    def test_dismissed_request_remains_visible_to_other_users(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)
        self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        self.client.force_login(self.other_lender)
        response = self.client.get(reverse("community-request-list"))

        self.assertIn(
            community_request, _requests(response.context["community_requests"])
        )


class ResponseCountIndicatorTests(CommunityRequestActionsTestBase):
    def test_request_with_one_response_shows_singular_count_on_other_users_cards(
        self,
    ) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)
        community_request.add_response(item)

        self.client.force_login(self.other_lender)
        response = self.client.get(reverse("community-request-list"))

        self.assertContains(response, "1 person has responded")
        self.assertContains(response, 'data-testid="community-request-response-count"')

    def test_request_with_multiple_responses_shows_plural_count(self) -> None:
        community_request = self._make_request()
        community_request.add_response(self._make_item(self.lender, name="First"))
        community_request.add_response(
            self._make_item(self.other_lender, name="Second")
        )

        # A third, unrelated user with no group ties to either lender's
        # item, just sharing the requester's group.
        third_lender = BorrowdUser.objects.create_user(
            username="third_lender", email="third_lender@example.com", password="pw"
        )
        self.group.add_user(third_lender)
        self.client.force_login(third_lender)

        response = self.client.get(reverse("community-request-list"))

        self.assertContains(response, "2 people have responded")

    def test_request_with_no_responses_shows_no_count(self) -> None:
        self._make_request()

        self.client.force_login(self.lender)
        response = self.client.get(reverse("community-request-list"))

        self.assertNotContains(
            response, 'data-testid="community-request-response-count"'
        )

    def test_response_count_is_not_shown_on_the_requesters_own_card(self) -> None:
        community_request = self._make_request()
        community_request.add_response(self._make_item(self.lender))

        self.client.force_login(self.requester)
        response = self.client.get(f"{reverse('community-request-list')}?tab=mine")

        self.assertNotContains(
            response, 'data-testid="community-request-response-count"'
        )


class CommunityRequestCancelViewTests(CommunityRequestActionsTestBase):
    def test_cancel_transitions_status_and_redirects_with_success_message(
        self,
    ) -> None:
        community_request = self._make_request()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-cancel", args=[community_request.pk]),
            follow=True,
        )

        self.assertRedirects(response, f"{reverse('community-request-list')}?tab=mine")
        community_request.refresh_from_db()
        self.assertEqual(community_request.status, CommunityRequestStatus.CANCELLED)
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("Your request has been cancelled.", messages_list)

    def test_cancel_404s_for_a_non_owner(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-cancel", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)
        community_request.refresh_from_db()
        self.assertEqual(community_request.status, CommunityRequestStatus.OPEN)

    def test_cancel_404s_for_a_lender_who_dismissed_the_request(self) -> None:
        community_request = self._make_request()
        community_request.dismiss_for(self.lender)
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-cancel", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cancel_404s_for_a_lender_who_responded_to_the_request(self) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)
        community_request.add_response(item)
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-cancel", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cancel_404s_for_an_already_cancelled_request(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-cancel", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cancel_404s_for_a_nonexistent_pk(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(reverse("community-request-cancel", args=[999999]))

        self.assertEqual(response.status_code, 404)


class CancelledRequestVisibilityAndActionsTests(CommunityRequestActionsTestBase):
    def test_cancelled_request_disappears_from_requesters_mine_tab(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        self.client.force_login(self.requester)

        response = self.client.get(f"{reverse('community-request-list')}?tab=mine")

        self.assertNotIn(
            community_request, _requests(response.context["community_requests"])
        )

    def test_cancelled_request_disappears_from_other_users_requests_tab(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        self.client.force_login(self.lender)

        response = self.client.get(f"{reverse('community-request-list')}?tab=all")

        self.assertNotIn(
            community_request, _requests(response.context["community_requests"])
        )

    def test_cancelled_request_cannot_be_dismissed(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)


class MarkFulfilledTests(CommunityRequestActionsTestBase):
    def test_mark_fulfilled_transitions_status(self) -> None:
        community_request = self._make_request()

        community_request.mark_fulfilled()

        self.assertEqual(community_request.status, CommunityRequestStatus.FULFILLED)

    def test_mark_fulfilled_does_not_require_any_responses(self) -> None:
        """The requester may have borrowed the item off-platform, or from a
        response not tracked in-app — mark_fulfilled() doesn't require
        picking a specific CommunityRequestResponse."""
        community_request = self._make_request()
        self.assertEqual(community_request.responses.count(), 0)

        community_request.mark_fulfilled()

        self.assertEqual(community_request.status, CommunityRequestStatus.FULFILLED)


class CommunityRequestMarkFulfilledViewTests(CommunityRequestActionsTestBase):
    def test_mark_fulfilled_transitions_status_and_redirects_with_success_message(
        self,
    ) -> None:
        community_request = self._make_request()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-mark-fulfilled", args=[community_request.pk]),
            follow=True,
        )

        self.assertRedirects(response, f"{reverse('community-request-list')}?tab=mine")
        community_request.refresh_from_db()
        self.assertEqual(community_request.status, CommunityRequestStatus.FULFILLED)
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("Your request has been marked as fulfilled.", messages_list)

    def test_mark_fulfilled_404s_for_a_non_owner(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-mark-fulfilled", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)
        community_request.refresh_from_db()
        self.assertEqual(community_request.status, CommunityRequestStatus.OPEN)

    def test_mark_fulfilled_404s_for_an_already_cancelled_request(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-mark-fulfilled", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_mark_fulfilled_404s_for_an_already_fulfilled_request(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-mark-fulfilled", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_mark_fulfilled_404s_for_a_nonexistent_pk(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-mark-fulfilled", args=[999999])
        )

        self.assertEqual(response.status_code, 404)


class FulfilledRequestVisibilityAndActionsTests(CommunityRequestActionsTestBase):
    def test_fulfilled_request_disappears_from_requesters_mine_tab(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()
        self.client.force_login(self.requester)

        response = self.client.get(f"{reverse('community-request-list')}?tab=mine")

        self.assertNotIn(community_request, response.context["community_requests"])

    def test_fulfilled_request_disappears_from_other_users_requests_tab(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()
        self.client.force_login(self.lender)

        response = self.client.get(f"{reverse('community-request-list')}?tab=all")

        self.assertNotIn(community_request, response.context["community_requests"])

    def test_fulfilled_request_is_excluded_from_the_badge_count(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()

        count = CommunityRequest.objects.visible_to(self.lender).exclude(
            requester=self.lender
        )

        self.assertNotIn(community_request, count)

    def test_fulfilled_request_cannot_be_dismissed(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_fulfilled_request_cannot_receive_new_responses(self) -> None:
        community_request = self._make_request()
        community_request.mark_fulfilled()
        item = self._make_item(self.lender)

        result = community_request.add_response(item)

        self.assertIsNone(result)
        self.assertEqual(community_request.responses.count(), 0)
