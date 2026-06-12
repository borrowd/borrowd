"""
Tests for closing out a loan outside the normal dual-confirmation flow:
the `Transaction.force_resolve` primitive,
the `RESOLVE_TRANSACTION` action surfaced when a counterparty's account is gone,
and the action endpoint'shandling of soft-deleted items.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from guardian.shortcuts import assign_perm

from borrowd.models import TrustLevel
from borrowd_items.models import (
    Item,
    ItemAction,
    ItemStatus,
    ResolutionReason,
    Transaction,
    TransactionStatus,
)
from borrowd_permissions.models import ItemOLP
from borrowd_users.models import BorrowdUser


def _user(username: str) -> BorrowdUser:
    return BorrowdUser.objects.create_user(
        username=username, email=f"{username}@example.com", password="password"
    )


def _item(owner: BorrowdUser, status: ItemStatus = ItemStatus.BORROWED) -> Item:
    return Item.objects.create(
        name="Drill",
        description="A useful thing",
        owner=owner,
        status=status,
        created_by=owner,
        updated_by=owner,
        trust_level_required=TrustLevel.STANDARD,
    )


def _txn(
    item: Item,
    party1: BorrowdUser,
    party2: BorrowdUser,
    status: TransactionStatus,
) -> Transaction:
    return Transaction.objects.create(
        item=item,
        party1=party1,
        party2=party2,
        status=status,
        created_by=party1,
        updated_by=party1,
    )


class ForceResolveTests(TestCase):
    def setUp(self) -> None:
        self.owner = _user("owner")
        self.borrower = _user("borrower")

    def test_sets_status_reason_and_frees_active_item(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)

        txn.force_resolve(
            resolved_by=self.borrower,
            reason=ResolutionReason.COUNTERPARTY_UNRESPONSIVE,
        )

        txn.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.RESOLVED)
        self.assertEqual(
            txn.resolution_reason, ResolutionReason.COUNTERPARTY_UNRESPONSIVE
        )
        self.assertEqual(txn.updated_by, self.borrower)
        # An active (not deleted) item is freed for reuse.
        self.assertEqual(item.status, ItemStatus.AVAILABLE)

    def test_leaves_soft_deleted_item_status_alone(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        item.soft_delete(self.owner)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)

        txn.force_resolve(
            resolved_by=self.borrower, reason=ResolutionReason.OWNER_ACCOUNT_DELETED
        )

        txn.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.RESOLVED)
        # A soft-deleted item (the gone owner's) isn't "freed" -- left as-is.
        self.assertEqual(item.status, ItemStatus.BORROWED)

    def test_resolved_transaction_is_no_longer_the_current_one(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)

        txn.force_resolve(
            resolved_by=self.borrower, reason=ResolutionReason.MODERATOR_OVERRIDE
        )
        # The transaction is no longer assigned to the user
        self.assertIsNone(item.get_current_transaction_for_user(self.borrower))


class ResolveActionAvailabilityTests(TestCase):
    def setUp(self) -> None:
        self.owner = _user("owner")
        self.borrower = _user("borrower")

    def test_item_available_to_borrower_when_owner_inactive(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)
        self.owner.is_active = False
        self.owner.save()

        # The borrower can still see the item and has the option to resolve the transaction,
        self.assertEqual(
            item.get_actions_for(self.borrower), (ItemAction.RESOLVE_TRANSACTION,)
        )

    def test_not_offered_when_both_parties_active(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)

        # Normal dual-confirm flow instead.
        self.assertEqual(
            item.get_actions_for(self.borrower), (ItemAction.MARK_RETURNED,)
        )

    def test_process_action_uses_owner_deleted_reason(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)
        self.owner.is_active = False
        self.owner.deleted_at = timezone.now()
        self.owner.save()

        item.process_action(user=self.borrower, action=ItemAction.RESOLVE_TRANSACTION)

        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.RESOLVED)
        self.assertEqual(txn.resolution_reason, ResolutionReason.OWNER_ACCOUNT_DELETED)

    def test_process_action_uses_unresponsive_reason_when_not_deleted(self) -> None:
        # Inactive but not a self-closed account (deleted_at is None).
        item = _item(self.owner, status=ItemStatus.BORROWED)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)
        self.owner.is_active = False
        self.owner.save()

        item.process_action(user=self.borrower, action=ItemAction.RESOLVE_TRANSACTION)

        txn.refresh_from_db()
        self.assertEqual(
            txn.resolution_reason, ResolutionReason.COUNTERPARTY_UNRESPONSIVE
        )


class ResolveTransactionEndpointTests(TestCase):
    def setUp(self) -> None:
        self.owner = _user("owner")
        self.borrower = _user("borrower")

    def test_borrower_closes_out_loan_on_soft_deleted_item(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        txn = _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)
        assign_perm(ItemOLP.VIEW, self.borrower, item)
        # Owner closed their account: inactive + item soft-deleted.
        self.owner.is_active = False
        self.owner.deleted_at = timezone.now()
        self.owner.save()
        item.soft_delete(self.owner)

        self.client.force_login(self.borrower)
        response = self.client.post(
            reverse("item-borrow", args=[item.pk]),
            {"action": ItemAction.RESOLVE_TRANSACTION.value},
        )

        self.assertEqual(response.status_code, 302)
        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.RESOLVED)

    def test_other_actions_404_on_soft_deleted_item(self) -> None:
        item = _item(self.owner, status=ItemStatus.BORROWED)
        _txn(item, self.owner, self.borrower, TransactionStatus.COLLECTED)
        assign_perm(ItemOLP.VIEW, self.borrower, item)
        item.soft_delete(self.owner)

        self.client.force_login(self.borrower)
        response = self.client.post(
            reverse("item-borrow", args=[item.pk]),
            {"action": ItemAction.MARK_RETURNED.value},
        )

        self.assertEqual(response.status_code, 404)
