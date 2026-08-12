from django.test import TestCase
from django.urls import reverse

from borrowd_community_requests.exceptions import CannotActOnOwnRequestException
from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser


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


class LinkResponseItemTests(CommunityRequestActionsTestBase):
    def test_link_response_item_sets_fulfilled_by_item(self) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)

        linked = community_request.link_response_item(item)

        self.assertTrue(linked)
        community_request.refresh_from_db()
        self.assertEqual(community_request.fulfilled_by_item, item)

    def test_link_response_item_is_a_no_op_on_an_already_fulfilled_request(
        self,
    ) -> None:
        community_request = self._make_request()
        first_item = self._make_item(self.lender, name="First drill")
        second_item = self._make_item(self.other_lender, name="Second drill")

        self.assertTrue(community_request.link_response_item(first_item))
        self.assertFalse(community_request.link_response_item(second_item))

        community_request.refresh_from_db()
        self.assertEqual(community_request.fulfilled_by_item, first_item)

    def test_link_response_item_is_atomic_against_concurrent_fulfillment(
        self,
    ) -> None:
        """
        Simulates two lenders submitting "Add Item" for the same request at
        nearly the same time: both fetch the request while it is still
        unfulfilled, then both attempt to link their item. Only the first
        conditional update should succeed; the second must see the row is
        no longer eligible and back off, rather than overwriting the link
        or racing past an in-memory check that both instances would pass.
        """
        community_request = self._make_request()
        first_item = self._make_item(self.lender, name="First drill")
        second_item = self._make_item(self.other_lender, name="Second drill")

        # Two independently-fetched copies, both still showing no
        # fulfillment, standing in for two concurrent request-handling
        # processes.
        first_lenders_copy = CommunityRequest.objects.get(pk=community_request.pk)
        second_lenders_copy = CommunityRequest.objects.get(pk=community_request.pk)
        self.assertIsNone(first_lenders_copy.fulfilled_by_item_id)
        self.assertIsNone(second_lenders_copy.fulfilled_by_item_id)

        first_result = first_lenders_copy.link_response_item(first_item)
        second_result = second_lenders_copy.link_response_item(second_item)

        self.assertTrue(first_result)
        self.assertFalse(second_result)

        community_request.refresh_from_db()
        self.assertEqual(community_request.fulfilled_by_item, first_item)

    def test_link_response_item_raises_when_requester_tries_to_fulfill_own_request(
        self,
    ) -> None:
        community_request = self._make_request()
        own_item = self._make_item(self.requester)

        with self.assertRaises(CannotActOnOwnRequestException):
            community_request.link_response_item(own_item)

        community_request.refresh_from_db()
        self.assertIsNone(community_request.fulfilled_by_item)

    def test_link_response_item_is_a_no_op_on_a_cancelled_request(self) -> None:
        community_request = self._make_request()
        community_request.cancel()
        item = self._make_item(self.lender)

        linked = community_request.link_response_item(item)

        self.assertFalse(linked)
        community_request.refresh_from_db()
        self.assertIsNone(community_request.fulfilled_by_item)


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

        self.assertNotIn(community_request, response.context["community_requests"])

    def test_dismissed_request_remains_visible_to_other_users(self) -> None:
        community_request = self._make_request()
        self.client.force_login(self.lender)
        self.client.post(
            reverse("community-request-dismiss", args=[community_request.pk])
        )

        self.client.force_login(self.other_lender)
        response = self.client.get(reverse("community-request-list"))

        self.assertIn(community_request, response.context["community_requests"])


class FulfilledRequestIndicatorTests(CommunityRequestActionsTestBase):
    def test_fulfilled_request_shows_indicator_on_other_users_cards(self) -> None:
        community_request = self._make_request()
        item = self._make_item(self.lender)
        community_request.link_response_item(item)

        self.client.force_login(self.other_lender)
        response = self.client.get(reverse("community-request-list"))

        self.assertContains(response, "Someone's already responded")
        self.assertContains(
            response, 'data-testid="community-request-fulfilled-indicator"'
        )
