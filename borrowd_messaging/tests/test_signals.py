from django.test import TestCase

from borrowd_items.models import Item
from borrowd_messaging.models import ChatThread
from borrowd_permissions.models import ChatThreadOLP
from borrowd_users.models import BorrowdUser


class ChatThreadPermissionSignalTests(TestCase):
    def setUp(self) -> None:
        self.lender = BorrowdUser.objects.create_user(
            username="lender",
            email="lender@example.com",
            password="password",
        )
        self.borrower = BorrowdUser.objects.create_user(
            username="borrower",
            email="borrower@example.com",
            password="password",
        )
        self.item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )
        self.thread = ChatThread.objects.create(
            item=self.item,
            lender=self.lender,
            borrower=self.borrower,
            created_by=self.borrower,
            updated_by=self.borrower,
        )

    def test_both_parties_can_view_the_thread(self) -> None:
        self.assertTrue(self.lender.has_perm(ChatThreadOLP.VIEW, self.thread))
        self.assertTrue(self.borrower.has_perm(ChatThreadOLP.VIEW, self.thread))

    def test_outsiders_cannot_view_the_thread(self) -> None:
        outsider = BorrowdUser.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="password",
        )

        self.assertFalse(outsider.has_perm(ChatThreadOLP.VIEW, self.thread))
