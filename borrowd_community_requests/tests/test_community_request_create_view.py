from django.test import TestCase
from django.urls import reverse

from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import ItemCategory
from borrowd_users.models import BorrowdUser

MAX_ACTIVE_REQUESTS_PER_USER = 3


class CommunityRequestCreateViewTestBase(TestCase):
    requester: BorrowdUser
    other_user: BorrowdUser
    category_tools: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        cls.requester = BorrowdUser.objects.create(
            username="requester", email="requester@example.com"
        )
        cls.other_user = BorrowdUser.objects.create(
            username="other_user", email="other_user@example.com"
        )
        cls.category_tools = ItemCategory.objects.create(name="Tools")
        BorrowdGroup.objects.create_group(
            name="Requester's Group",
            created_by=cls.requester,
            updated_by=cls.requester,
        )
        BorrowdGroup.objects.create_group(
            name="Other User's Group",
            created_by=cls.other_user,
            updated_by=cls.other_user,
        )

    def setUp(self) -> None:
        self.client.force_login(self.requester)


class CommunityRequestCreateViewPrefillTests(CommunityRequestCreateViewTestBase):
    def test_prefills_item_name_from_item_name_query_param(self) -> None:
        response = self.client.get(
            reverse("community-request-create"), {"item_name": "Cordless drill"}
        )

        self.assertEqual(
            response.context["form"].initial["item_name"], "Cordless drill"
        )

    def test_prefills_item_name_from_search_query_param(self) -> None:
        response = self.client.get(
            reverse("community-request-create"), {"search": "Step ladder"}
        )

        self.assertEqual(response.context["form"].initial["item_name"], "Step ladder")

    def test_item_name_query_param_takes_precedence_over_search(self) -> None:
        response = self.client.get(
            reverse("community-request-create"),
            {"item_name": "Drill", "search": "Ladder"},
        )

        self.assertEqual(response.context["form"].initial["item_name"], "Drill")

    def test_prefill_is_truncated_to_fifty_characters(self) -> None:
        long_name = "x" * 80

        response = self.client.get(
            reverse("community-request-create"), {"item_name": long_name}
        )

        self.assertEqual(response.context["form"].initial["item_name"], "x" * 50)

    def test_no_prefill_when_no_query_param_given(self) -> None:
        response = self.client.get(reverse("community-request-create"))

        self.assertNotIn("item_name", response.context["form"].initial)


class CommunityRequestCreateViewSubmissionTests(CommunityRequestCreateViewTestBase):
    def test_successful_submission_auto_assigns_the_logged_in_user_as_requester(
        self,
    ) -> None:
        self.client.post(
            reverse("community-request-create"),
            {
                "item_name": "Drill",
                "description": "A basic power drill.",
                "category": self.category_tools.pk,
            },
        )

        created = CommunityRequest.objects.get(item_name="Drill")
        self.assertEqual(created.requester, self.requester)

    def test_successful_submission_redirects_to_the_yours_scope(self) -> None:
        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": "Drill",
                "description": "A basic power drill.",
                "category": self.category_tools.pk,
            },
            follow=True,
        )

        self.assertRedirects(
            response, f"{reverse('community-request-list')}?scope=yours"
        )

    def test_successful_submission_shows_a_success_message(self) -> None:
        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": "Drill",
                "description": "A basic power drill.",
                "category": self.category_tools.pk,
            },
            follow=True,
        )

        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn(
            "Your request is posted. We'll let you know if someone responds.",
            messages_list,
        )

    def test_duplicate_request_surfaces_as_a_form_error_not_a_500(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": "Drill",
                "description": "",
                "category": self.category_tools.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn(
            "You already have an open request for this item in that category.",
            response.context["form"].non_field_errors(),
        )
        self.assertEqual(
            CommunityRequest.objects.filter(requester=self.requester).count(), 1
        )

    def test_exceeding_the_active_request_cap_surfaces_as_a_form_error_not_a_500(
        self,
    ) -> None:
        for i in range(MAX_ACTIVE_REQUESTS_PER_USER):
            CommunityRequest.objects.create(
                requester=self.requester,
                category=self.category_tools,
                item_name=f"Item {i}",
                status=CommunityRequestStatus.OPEN,
            )

        response = self.client.post(
            reverse("community-request-create"),
            {
                "item_name": "One too many",
                "description": "",
                "category": self.category_tools.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertEqual(
            CommunityRequest.objects.filter(requester=self.requester).count(),
            MAX_ACTIVE_REQUESTS_PER_USER,
        )


class CommunityRequestCreateViewBackUrlTests(CommunityRequestCreateViewTestBase):
    def test_back_url_falls_back_to_the_list_page(self) -> None:
        response = self.client.get(reverse("community-request-create"))

        self.assertEqual(
            response.context["back_url"], reverse("community-request-list")
        )

    def test_back_url_honors_a_trusted_referer(self) -> None:
        response = self.client.get(
            reverse("community-request-create"),
            HTTP_REFERER="http://testserver" + reverse("item-list"),
        )

        self.assertEqual(response.context["back_url"], reverse("item-list"))
