from django.test import TestCase
from django.urls import reverse

from borrowd_items.models import Item, ItemStatus, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser


class InventoryViewScopeTests(TestCase):
    def setUp(self) -> None:
        self.owner = BorrowdUser.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.other = BorrowdUser.objects.create_user(
            username="other", email="other@example.com", password="password"
        )
        self.client.force_login(self.owner)

    def _make_item(
        self, owner: BorrowdUser, name: str, status: ItemStatus = ItemStatus.AVAILABLE
    ) -> Item:
        return Item.objects.create(
            name=name,
            description="A description",
            owner=owner,
            status=status,
            created_by=owner,
            updated_by=owner,
        )

    def test_default_scope_is_all(self) -> None:
        response = self.client.get(reverse("profile-inventory"))

        self.assertEqual(response.context["active_scope"], "all")

    def test_unrecognized_scope_falls_back_to_all(self) -> None:
        response = self.client.get(reverse("profile-inventory"), {"scope": "bogus"})

        self.assertEqual(response.context["active_scope"], "all")

    def test_lending_scope_includes_only_lending_sections(self) -> None:
        self._make_item(self.owner, "Available Drill")

        lent_item = self._make_item(
            self.owner, "Lent Ladder", status=ItemStatus.BORROWED
        )
        Transaction.objects.create(
            item=lent_item,
            party1=self.owner,
            party2=self.other,
            status=TransactionStatus.ACCEPTED,
            created_by=self.owner,
            updated_by=self.owner,
        )

        requested_item = self._make_item(
            self.owner, "Requested Saw", status=ItemStatus.REQUESTED
        )
        Transaction.objects.create(
            item=requested_item,
            party1=self.owner,
            party2=self.other,
            status=TransactionStatus.REQUESTED,
            created_by=self.other,
            updated_by=self.other,
        )

        # An item the owner is BORROWING from someone else must not appear.
        borrowed_item = self._make_item(
            self.other, "Borrowed Sander", status=ItemStatus.BORROWED
        )
        Transaction.objects.create(
            item=borrowed_item,
            party1=self.other,
            party2=self.owner,
            status=TransactionStatus.ACCEPTED,
            created_by=self.other,
            updated_by=self.other,
        )

        response = self.client.get(reverse("profile-inventory"), {"scope": "lending"})

        names = {card["name"] for card in response.context["item_cards"]}
        self.assertEqual(names, {"Available Drill", "Lent Ladder", "Requested Saw"})

    def test_borrowing_scope_includes_only_borrowing_sections(self) -> None:
        # The owner's own items must not appear in Borrowing.
        self._make_item(self.owner, "Available Drill")

        outgoing_item = self._make_item(
            self.other, "Outgoing Saw", status=ItemStatus.REQUESTED
        )
        Transaction.objects.create(
            item=outgoing_item,
            party1=self.other,
            party2=self.owner,
            status=TransactionStatus.REQUESTED,
            created_by=self.owner,
            updated_by=self.owner,
        )

        borrowed_item = self._make_item(
            self.other, "Borrowed Sander", status=ItemStatus.BORROWED
        )
        Transaction.objects.create(
            item=borrowed_item,
            party1=self.other,
            party2=self.owner,
            status=TransactionStatus.ACCEPTED,
            created_by=self.other,
            updated_by=self.other,
        )

        response = self.client.get(reverse("profile-inventory"), {"scope": "borrowing"})

        names = {card["name"] for card in response.context["item_cards"]}
        self.assertEqual(names, {"Outgoing Saw", "Borrowed Sander"})

    def test_empty_state_copy_for_lending_scope(self) -> None:
        response = self.client.get(reverse("profile-inventory"), {"scope": "lending"})

        self.assertContains(response, "You have nothing out to lend right now.")

    def test_empty_state_copy_for_borrowing_scope(self) -> None:
        response = self.client.get(reverse("profile-inventory"), {"scope": "borrowing"})

        self.assertContains(response, "You're not borrowing anything right now.")

    def test_empty_state_copy_for_all_scope(self) -> None:
        response = self.client.get(reverse("profile-inventory"))

        self.assertContains(response, "You have no items yet.")
