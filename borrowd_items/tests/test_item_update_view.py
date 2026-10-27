from django.test import TestCase
from django.urls import reverse

from borrowd_items.models import Item, ItemCategory
from borrowd_users.models import BorrowdUser
from tests.helpers import link_href_by_text


class ItemUpdateViewBackUrlTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.category = ItemCategory.objects.create(name="Tools")
        self.item = Item.objects.create(
            name="Drill",
            description="A description",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.item.categories.add(self.category)
        self.client.force_login(self.owner)

    def test_back_url_falls_back_to_the_item_detail_page(self) -> None:
        response = self.client.get(reverse("item-edit", args=[self.item.pk]))

        self.assertEqual(
            response.context["back_url"], reverse("item-detail", args=[self.item.pk])
        )

    def test_back_url_honors_a_trusted_referer(self) -> None:
        response = self.client.get(
            reverse("item-edit", args=[self.item.pk]),
            HTTP_REFERER="http://testserver" + reverse("profile-inventory"),
        )

        self.assertEqual(response.context["back_url"], reverse("profile-inventory"))

    def test_cancel_link_points_at_the_back_url(self) -> None:
        response = self.client.get(
            reverse("item-edit", args=[self.item.pk]),
            HTTP_REFERER="http://testserver" + reverse("profile-inventory"),
        )

        self.assertEqual(
            link_href_by_text(response, "Cancel"), reverse("profile-inventory")
        )

    def test_edit_title_and_submit_label_are_unchanged(self) -> None:
        response = self.client.get(reverse("item-edit", args=[self.item.pk]))

        self.assertContains(response, "Edit item")
        self.assertContains(response, "Save changes")

    def test_listing_type_is_not_shown_on_edit(self) -> None:
        response = self.client.get(reverse("item-edit", args=[self.item.pk]))

        self.assertNotContains(response, "How do you want to share it?")
