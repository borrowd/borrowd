from django.test import TestCase
from django.urls import reverse

from borrowd_groups.models import BorrowdGroup
from borrowd_users.models import BorrowdUser
from tests.helpers import link_href_by_text


class GroupCreateViewBackUrlTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.client.force_login(self.owner)

    def test_back_url_falls_back_to_the_group_list(self) -> None:
        response = self.client.get(reverse("borrowd_groups:group-create"))

        self.assertEqual(
            response.context["back_url"], reverse("borrowd_groups:group-list")
        )

    def test_back_url_honors_a_trusted_referer(self) -> None:
        response = self.client.get(
            reverse("borrowd_groups:group-create"),
            HTTP_REFERER="http://testserver" + reverse("item-list"),
        )

        self.assertEqual(response.context["back_url"], reverse("item-list"))


class GroupCreateViewTemplateTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.client.force_login(self.owner)

    def test_page_title_is_create_group(self) -> None:
        response = self.client.get(reverse("borrowd_groups:group-create"))

        self.assertContains(response, "Create group")

    def test_cancel_link_points_at_the_back_url(self) -> None:
        response = self.client.get(
            reverse("borrowd_groups:group-create"),
            HTTP_REFERER="http://testserver" + reverse("item-list"),
        )

        self.assertEqual(link_href_by_text(response, "Cancel"), reverse("item-list"))

    def test_name_and_description_fields_have_visible_labels_and_counters(
        self,
    ) -> None:
        response = self.client.get(reverse("borrowd_groups:group-create"))

        self.assertContains(response, "Group name")
        self.assertContains(response, "Group description")
        self.assertContains(response, "/50")
        self.assertContains(response, "/500")

    def test_name_and_description_fields_have_a_programmatic_label(self) -> None:
        response = self.client.get(reverse("borrowd_groups:group-create"))

        self.assertContains(response, 'id="id_name-label"')
        self.assertContains(response, 'aria-labelledby="id_name-label"')
        self.assertContains(response, 'id="id_description-label"')
        self.assertContains(response, 'aria-labelledby="id_description-label"')

    def test_submit_button_disables_itself_on_submit(self) -> None:
        response = self.client.get(reverse("borrowd_groups:group-create"))

        self.assertContains(response, '@submit="submitForm($event)"')
        self.assertContains(response, 'x-bind:disabled="isSubmitting"')


class GroupUpdateViewBackUrlTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.group = BorrowdGroup.objects.create_group(
            name="Group 1",
            created_by=self.owner,
            updated_by=self.owner,
        )
        self.client.force_login(self.owner)

    def test_back_url_falls_back_to_the_group_detail_page(self) -> None:
        response = self.client.get(
            reverse("borrowd_groups:group-edit", args=[self.group.pk])
        )

        self.assertEqual(
            response.context["back_url"],
            reverse("borrowd_groups:group-detail", args=[self.group.pk]),
        )

    def test_back_url_honors_a_trusted_referer(self) -> None:
        response = self.client.get(
            reverse("borrowd_groups:group-edit", args=[self.group.pk]),
            HTTP_REFERER="http://testserver" + reverse("borrowd_groups:group-list"),
        )

        self.assertEqual(
            response.context["back_url"], reverse("borrowd_groups:group-list")
        )

    def test_edit_title_and_submit_label(self) -> None:
        response = self.client.get(
            reverse("borrowd_groups:group-edit", args=[self.group.pk])
        )

        self.assertContains(response, "Edit group")
        self.assertContains(response, "Save changes")
