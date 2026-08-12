from urllib.parse import quote

from django.test import SimpleTestCase
from django.urls import reverse
from notifications.models import Notification

from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup, Membership, MembershipStatus
from borrowd_items.models import Item, ItemCategory, ListingType
from borrowd_notifications.models import NotificationType
from borrowd_users.models import BorrowdUser


class CommunityRequestEndToEndFlowTest(SimpleTestCase):
    """
    End-to-end happy path across every phase of the Community Requests
    feature, driven entirely through the real views via the Django test
    client rather than by calling model methods directly: a zero-result
    search with no groups shows no CTA; joining a group unlocks the CTA;
    creating a request notifies shared-group members; a lender adds an
    item from the request card and the requester is notified with a
    working item link; and cancelling a second, separate request removes
    it from both parties' views.

    See RejectedFlowTest in tests/test_borrowing_flows.py for why this is
    structured as a sequence of numbered test_NNN methods sharing
    class-level fixtures rather than independent tests. SimpleTestCase
    (instead of TestCase) matters here for a second reason beyond that
    state-sharing: notification dispatch runs via transaction.on_commit()
    (see the send_notification receiver in borrowd_notifications/signals.py),
    which only fires synchronously when there is no enclosing atomic
    block. TestCase wraps every test in one, which would leave every
    notification's borrowd_metadata.visible_in_app at its False default
    and make the "working item link" assertion below 404 instead of
    exercising the real behavior.
    """

    requester: BorrowdUser
    lender: BorrowdUser
    category: ItemCategory
    group: BorrowdGroup
    community_request: CommunityRequest
    second_request: CommunityRequest
    item: Item
    # SimpleTestCase expects no database access;
    # setting this class attribute makes it allowed again.
    databases = "__all__"

    SEARCH_TERM = "Cordless Drill"
    SECOND_ITEM_NAME = "Step Ladder"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.requester = BorrowdUser.objects.create_user(
            username="cr_flow_requester",
            email="cr_flow_requester@example.com",
            password="password",
            first_name="Alice",
        )
        cls.lender = BorrowdUser.objects.create_user(
            username="cr_flow_lender",
            email="cr_flow_lender@example.com",
            password="password",
            first_name="Bob",
        )
        cls.category = ItemCategory.objects.create(name="Cr Flow Tools")
        # Only the lender belongs to this group at first -- the requester
        # joins it in test_020, which is what unlocks the CTA in test_030.
        cls.group = BorrowdGroup.objects.create_group(
            name="Cr Flow Neighbors",
            created_by=cls.lender,
            updated_by=cls.lender,
            membership_requires_approval=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "item"):
            cls.item.delete()
        cls.group.delete()
        cls.requester.delete()
        cls.lender.delete()
        cls.category.delete()
        super().tearDownClass()

    def test_010_requester_with_no_groups_sees_no_cta_on_empty_search(self) -> None:
        """A zero-result search with no group memberships shows the plain
        empty-state message and no Community Request CTA."""
        self.client.force_login(self.requester)

        response = self.client.get(reverse("item-list"), {"search": self.SEARCH_TERM})

        self.assertContains(response, f"We couldn't find any {self.SEARCH_TERM}.")
        self.assertNotContains(response, "Community Request")
        self.assertNotContains(response, reverse("community-request-create"))

    def test_020_requester_joins_the_lenders_group(self) -> None:
        """Direct group setup (not a view under test in this feature) --
        mirrors how borrowd_community_requests' own tests wire up shared
        group membership."""
        self.group.add_user(self.requester)

        self.assertTrue(
            Membership.objects.filter(
                user=self.requester,
                group=self.group,
                status=MembershipStatus.ACTIVE,
            ).exists()
        )

    def test_030_requester_with_a_group_sees_the_cta_on_empty_search(self) -> None:
        """Now that the requester shares a group, the same zero-result
        search surfaces the Community Request CTA, prefilled with the
        search term."""
        self.client.force_login(self.requester)

        response = self.client.get(reverse("item-list"), {"search": self.SEARCH_TERM})

        self.assertContains(
            response,
            f"We couldn't find any {self.SEARCH_TERM}. Would you like to make a "
            "Community Request?",
        )
        expected_link = (
            f"{reverse('community-request-create')}?item_name={quote(self.SEARCH_TERM)}"
        )
        self.assertContains(response, expected_link)
        self.assertContains(response, "Request Item")

    def test_040_requester_creates_a_community_request(self) -> None:
        """Submitting the CTA's create form creates an open request owned
        by the requester and redirects to the success page."""
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": self.SEARCH_TERM,
                "description": "A basic cordless drill.",
                "category": self.category.pk,
            },
            follow=True,
        )

        type(self).community_request = CommunityRequest.objects.get(
            item_name=self.SEARCH_TERM
        )
        self.assertRedirects(
            response,
            reverse(
                "community-request-success",
                kwargs={"pk": self.community_request.pk},
            ),
        )
        self.assertEqual(self.community_request.requester, self.requester)
        self.assertEqual(self.community_request.status, CommunityRequestStatus.OPEN)

    def test_050_lender_sees_the_request_on_the_requests_tab(self) -> None:
        """The lender shares the group with the requester, so the new
        request shows up on their (default) "Requests" tab."""
        self.client.force_login(self.lender)

        response = self.client.get(reverse("community-request-list"))

        self.assertEqual(response.context["active_tab"], "all")
        self.assertIn(self.community_request, response.context["community_requests"])
        self.assertContains(response, self.SEARCH_TERM)

    def test_060_lender_receives_a_posted_notification(self) -> None:
        """Creating the request fans out a COMMUNITY_REQUEST_POSTED
        notification to the lender, targeting the shared group."""
        posted = Notification.objects.get(
            recipient=self.lender,
            verb=NotificationType.COMMUNITY_REQUEST_POSTED.value,
        )

        self.assertEqual(posted.action_object, self.community_request)
        self.assertEqual(posted.target, self.group)

    def test_070_lenders_add_item_link_is_prefilled(self) -> None:
        """The request card's "Add Item" link carries the item name and
        category through to the item-create form, which prefills them."""
        self.client.force_login(self.lender)
        add_item_url = (
            f"{reverse('item-create')}?name={quote(self.community_request.item_name)}"
            f"&category={self.community_request.category_id}"
            f"&fulfills_request={self.community_request.pk}"
        )

        # Regression check that the card actually renders this exact link.
        list_response = self.client.get(reverse("community-request-list"))
        self.assertContains(list_response, add_item_url)

        response = self.client.get(add_item_url)

        self.assertEqual(
            response.context["form"].initial["name"], self.community_request.item_name
        )
        self.assertEqual(
            response.context["form"].initial["categories"], [self.category.pk]
        )
        self.assertEqual(
            response.context["fulfills_request"], str(self.community_request.pk)
        )

    def test_080_lender_submits_the_add_item_form(self) -> None:
        """Submitting the prefilled form creates the item and links it back
        to the community request via the hidden fulfills_request field."""
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("item-create"),
            {
                "name": self.community_request.item_name,
                "description": "A basic cordless drill, ready to lend.",
                "categories": [self.category.pk],
                "listing_type": ListingType.LEND,
                "share_with_all_groups": "on",
                "fulfills_request": str(self.community_request.pk),
            },
            follow=True,
        )

        type(self).item = Item.objects.get(
            name=self.community_request.item_name, owner=self.lender
        )
        self.community_request.refresh_from_db()
        self.assertEqual(self.community_request.fulfilled_by_item, self.item)
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn(
            "Your item has been linked to the community request.", messages_list
        )

    def test_090_requester_receives_a_fulfilled_notification_with_a_working_link(
        self,
    ) -> None:
        """The requester is notified exactly once, and the notification's
        action link genuinely resolves to the new item's detail page."""
        fulfilled = Notification.objects.get(
            recipient=self.requester,
            verb=NotificationType.COMMUNITY_REQUEST_FULFILLED.value,
        )
        self.assertEqual(fulfilled.action_object, self.item)
        self.assertEqual(fulfilled.target, self.community_request)

        self.client.force_login(self.requester)
        response = self.client.post(
            reverse("notification-open", args=[fulfilled.pk]), follow=True
        )

        self.assertRedirects(response, reverse("item-detail", args=[self.item.pk]))
        self.assertContains(response, self.item.name)

    def test_100_requester_creates_a_second_separate_request(self) -> None:
        """A second, independent request the requester will cancel later."""
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": self.SECOND_ITEM_NAME,
                "description": "",
                "category": self.category.pk,
            },
            follow=True,
        )

        type(self).second_request = CommunityRequest.objects.get(
            item_name=self.SECOND_ITEM_NAME
        )
        self.assertRedirects(
            response,
            reverse("community-request-success", kwargs={"pk": self.second_request.pk}),
        )

    def test_110_lender_sees_the_second_request_before_it_is_cancelled(self) -> None:
        """Sanity check ahead of cancellation: the second request is
        visible to the lender just like the first one was."""
        self.client.force_login(self.lender)

        response = self.client.get(reverse("community-request-list"))

        self.assertIn(self.second_request, response.context["community_requests"])

    def test_120_requester_cancels_the_second_request(self) -> None:
        """Cancelling redirects to the requester's own "Your requests" tab
        and transitions the request's status."""
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("community-request-cancel", args=[self.second_request.pk]),
            follow=True,
        )

        self.assertRedirects(response, f"{reverse('community-request-list')}?tab=mine")
        self.second_request.refresh_from_db()
        self.assertEqual(self.second_request.status, CommunityRequestStatus.CANCELLED)
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("Your request has been cancelled.", messages_list)

    def test_130_cancelled_request_disappears_from_both_parties_views(self) -> None:
        """The cancelled request is gone from the requester's own "Your
        requests" tab and from the lender's "Requests" tab."""
        self.client.force_login(self.requester)
        mine_response = self.client.get(
            reverse("community-request-list"), {"tab": "mine"}
        )
        self.assertNotIn(
            self.second_request, mine_response.context["community_requests"]
        )

        self.client.force_login(self.lender)
        all_response = self.client.get(
            reverse("community-request-list"), {"tab": "all"}
        )
        self.assertNotIn(
            self.second_request, all_response.context["community_requests"]
        )
