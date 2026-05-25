from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse

from borrowd.models import TrustLevel
from borrowd_items.models import Item, ItemStatus, Transaction, TransactionStatus
from borrowd_items.views import ItemDetailView
from borrowd_users.models import BorrowdUser


class ItemDeletionTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
        )
        self.factory = RequestFactory()

    def create_item(self, status: ItemStatus = ItemStatus.AVAILABLE) -> Item:
        return Item.objects.create(
            name="Test Item",
            description="Test description",
            owner=self.owner,
            status=status,
            created_by=self.owner,
            updated_by=self.owner,
            trust_level_required=TrustLevel.STANDARD,
        )

    def test_owner_can_delete_available_item_with_transaction_history(self) -> None:
        item = self.create_item()
        transaction = Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.borrower,
            status=TransactionStatus.CANCELLED,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

        self.client.force_login(self.owner)
        response = self.client.post(reverse("item-delete", args=[item.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("profile-inventory"))
        item.refresh_from_db()
        transaction.refresh_from_db()
        self.assertIsNotNone(item.deleted_at)
        self.assertEqual(item.deleted_by, self.owner)
        self.assertEqual(transaction.item, item)

    def test_deleted_item_is_not_viewable(self) -> None:
        item = self.create_item()

        self.client.force_login(self.owner)
        self.client.post(reverse("item-delete", args=[item.pk]))
        request = self.factory.get(reverse("item-detail", args=[item.pk]))
        request.user = self.owner

        with self.assertRaises(Http404):
            ItemDetailView.as_view()(request, pk=item.pk)

    def test_owner_cannot_delete_item_that_is_not_available(self) -> None:
        item = self.create_item(status=ItemStatus.REQUESTED)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("item-delete", args=[item.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("item-detail", args=[item.pk]),
        )
        item.refresh_from_db()
        self.assertIsNone(item.deleted_at)
