from django.test import TestCase

from borrowd_community_requests.forms import CommunityRequestForm
from borrowd_community_requests.models import CommunityRequest, CommunityRequestStatus
from borrowd_groups.models import BorrowdGroup
from borrowd_items.models import ItemCategory
from borrowd_users.models import BorrowdUser


class CommunityRequestFormTestBase(TestCase):
    requester: BorrowdUser
    category_tools: ItemCategory
    category_electronics: ItemCategory

    @classmethod
    def setUpTestData(cls) -> None:
        cls.requester = BorrowdUser.objects.create(
            username="requester", email="requester@example.com"
        )
        cls.category_tools = ItemCategory.objects.create(name="Tools")
        cls.category_electronics = ItemCategory.objects.create(name="Electronics")
        BorrowdGroup.objects.create_group(
            name="Requester's Group",
            created_by=cls.requester,
            updated_by=cls.requester,
        )

    def _form_for(self, **field_overrides: object) -> CommunityRequestForm:
        data = {
            "item_name": "Drill",
            "description": "",
            "category": self.category_tools.pk,
        }
        data.update(field_overrides)

        form = CommunityRequestForm(data=data)
        form.instance.requester = self.requester
        return form


class CommunityRequestFormDuplicateValidationTests(CommunityRequestFormTestBase):
    def test_rejects_duplicate_open_request_for_same_item_and_category(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        form = self._form_for()

        self.assertFalse(form.is_valid())
        self.assertIn(
            "You already have an open request for this item in that category.",
            form.non_field_errors(),
        )

    def test_allows_same_item_name_in_a_different_category(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        form = self._form_for(category=self.category_electronics.pk)

        self.assertTrue(form.is_valid())

    def test_allows_resubmitting_the_same_item_name_once_cancelled(self) -> None:
        CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.CANCELLED,
        )

        form = self._form_for()

        self.assertTrue(form.is_valid())

    def test_editing_an_existing_open_request_does_not_conflict_with_itself(
        self,
    ) -> None:
        existing = CommunityRequest.objects.create(
            requester=self.requester,
            category=self.category_tools,
            item_name="Drill",
            status=CommunityRequestStatus.OPEN,
        )

        form = CommunityRequestForm(
            data={
                "item_name": "Drill",
                "description": "Updated description",
                "category": self.category_tools.pk,
            },
            instance=existing,
        )

        self.assertTrue(form.is_valid())

    def test_valid_form_with_no_duplicate_saves_successfully(self) -> None:
        form = self._form_for()

        self.assertTrue(form.is_valid())
        saved = form.save()

        self.assertEqual(saved.item_name, "Drill")
        self.assertEqual(saved.requester, self.requester)
