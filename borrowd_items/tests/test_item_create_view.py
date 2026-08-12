from typing import Any

from django.test import TestCase
from django.urls import reverse

from borrowd_community_requests.models import CommunityRequest
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import Item, ItemCategory, ListingType
from borrowd_users.models import BorrowdUser


class ItemCreateViewTestBase(TestCase):
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

    def _valid_post_data(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": "Drill",
            "description": "A description",
            "categories": [self.category.pk],
            "listing_type": ListingType.LEND,
            "share_with_all_groups": "on",
        }
        data.update(overrides)
        return data


class ItemCreateViewGetInitialTests(ItemCreateViewTestBase):
    def setUp(self) -> None:
        self.client.force_login(self.lender)

    def test_prefills_name_from_get_param(self) -> None:
        response = self.client.get(reverse("item-create"), {"name": "Cordless drill"})

        self.assertEqual(response.context["form"].initial["name"], "Cordless drill")

    def test_prefills_name_truncated_to_40_chars(self) -> None:
        long_name = "x" * 60

        response = self.client.get(reverse("item-create"), {"name": long_name})

        self.assertEqual(response.context["form"].initial["name"], "x" * 40)

    def test_prefills_categories_from_valid_digit_param(self) -> None:
        response = self.client.get(
            reverse("item-create"), {"category": str(self.category.pk)}
        )

        self.assertEqual(
            response.context["form"].initial["categories"], [self.category.pk]
        )

    def test_missing_category_param_leaves_categories_unset(self) -> None:
        response = self.client.get(reverse("item-create"))

        self.assertNotIn("categories", response.context["form"].initial)

    def test_non_digit_category_param_is_ignored(self) -> None:
        response = self.client.get(reverse("item-create"), {"category": "not-a-number"})

        self.assertNotIn("categories", response.context["form"].initial)

    def test_missing_name_param_leaves_name_unset(self) -> None:
        response = self.client.get(reverse("item-create"))

        self.assertNotIn("name", response.context["form"].initial)


class ItemCreateViewFulfillsRequestTests(ItemCreateViewTestBase):
    def setUp(self) -> None:
        self.community_request = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category,
            item_name="Drill",
        )

    def test_add_item_links_the_created_item_to_the_community_request(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("item-create"),
            self._valid_post_data(fulfills_request=str(self.community_request.pk)),
        )

        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(name="Drill")
        self.community_request.refresh_from_db()
        self.assertEqual(self.community_request.fulfilled_by_item, item)

    def test_successful_link_flashes_success_message(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("item-create"),
            self._valid_post_data(fulfills_request=str(self.community_request.pk)),
            follow=True,
        )

        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn(
            "Your item has been linked to the community request.", messages_list
        )

    def test_second_lenders_item_does_not_overwrite_an_existing_link(self) -> None:
        self.client.force_login(self.lender)
        self.client.post(
            reverse("item-create"),
            self._valid_post_data(
                name="First drill", fulfills_request=str(self.community_request.pk)
            ),
        )
        first_item = Item.objects.get(name="First drill")

        self.client.force_login(self.other_lender)
        self.client.post(
            reverse("item-create"),
            self._valid_post_data(
                name="Second drill", fulfills_request=str(self.community_request.pk)
            ),
        )

        self.community_request.refresh_from_db()
        self.assertEqual(self.community_request.fulfilled_by_item, first_item)
        # The second lender's item is still created — only the link is a no-op.
        self.assertTrue(Item.objects.filter(name="Second drill").exists())

    def test_requester_cannot_fulfill_own_request(self) -> None:
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse("item-create"),
            self._valid_post_data(fulfills_request=str(self.community_request.pk)),
            follow=True,
        )

        self.community_request.refresh_from_db()
        self.assertIsNone(self.community_request.fulfilled_by_item)
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertIn("You can't fulfill your own request.", messages_list)
        # The item creation itself still succeeds — only the link is rejected.
        self.assertTrue(
            Item.objects.filter(name="Drill", owner=self.requester).exists()
        )

    def test_item_creation_without_fulfills_request_does_not_flash_link_message(
        self,
    ) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("item-create"), self._valid_post_data(), follow=True
        )

        messages_list = [str(m) for m in response.context["messages"]]
        self.assertEqual(messages_list, [])

    def test_nonexistent_fulfills_request_pk_is_ignored(self) -> None:
        self.client.force_login(self.lender)

        response = self.client.post(
            reverse("item-create"),
            self._valid_post_data(fulfills_request="999999"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Item.objects.filter(name="Drill").exists())
