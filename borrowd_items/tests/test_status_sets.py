"""Verify transaction status classifications and their item status mappings."""

from django.test import SimpleTestCase

from borrowd_items.models import (
    BORROWER_TRANSACTION_STATUSES,
    DUAL_CONFIRMATION_TRANSACTION_STATUSES,
    GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES,
    ITEM_STATUS_FOR_TRANSACTION,
    OPEN_TRANSACTION_STATUSES,
    PRE_COLLECTION_TRANSACTION_STATUSES,
    REQUEST_TRANSACTION_STATUSES,
    TERMINAL_TRANSACTION_STATUSES,
    ItemStatus,
    TransactionStatus,
)


class TransactionStatusSetTests(SimpleTestCase):
    def test_every_status_is_either_open_or_terminal(self) -> None:
        self.assertEqual(
            set(OPEN_TRANSACTION_STATUSES) | set(TERMINAL_TRANSACTION_STATUSES),
            set(TransactionStatus),
        )
        self.assertEqual(
            set(OPEN_TRANSACTION_STATUSES) & set(TERMINAL_TRANSACTION_STATUSES),
            set(),
        )

    def test_every_open_status_is_either_a_request_or_has_a_borrower(self) -> None:
        self.assertEqual(
            set(REQUEST_TRANSACTION_STATUSES) | set(BORROWER_TRANSACTION_STATUSES),
            set(OPEN_TRANSACTION_STATUSES),
        )
        self.assertEqual(
            set(REQUEST_TRANSACTION_STATUSES) & set(BORROWER_TRANSACTION_STATUSES),
            set(),
        )

    def test_every_open_status_is_pre_collection_or_dual_confirmation(self) -> None:
        self.assertEqual(
            set(PRE_COLLECTION_TRANSACTION_STATUSES)
            | set(DUAL_CONFIRMATION_TRANSACTION_STATUSES),
            set(OPEN_TRANSACTION_STATUSES),
        )
        self.assertEqual(
            set(PRE_COLLECTION_TRANSACTION_STATUSES)
            & set(DUAL_CONFIRMATION_TRANSACTION_STATUSES),
            set(),
        )

    def test_accepted_is_the_only_borrower_status_awaiting_collection(self) -> None:
        self.assertEqual(
            set(BORROWER_TRANSACTION_STATUSES)
            - set(DUAL_CONFIRMATION_TRANSACTION_STATUSES),
            {TransactionStatus.ACCEPTED},
        )

    def test_membership_is_unchanged(self) -> None:
        """Keep expected values explicit so classification changes require a test update."""
        self.assertEqual(
            [status.value for status in OPEN_TRANSACTION_STATUSES],
            [10, 15, 30, 40, 50, 52, 55, 60, 65],
        )
        self.assertEqual(
            [status.value for status in BORROWER_TRANSACTION_STATUSES],
            [30, 40, 50, 52, 55, 60, 65],
        )
        self.assertEqual(
            [status.value for status in DUAL_CONFIRMATION_TRANSACTION_STATUSES],
            [40, 50, 52, 55, 60, 65],
        )
        self.assertEqual(
            [status.value for status in PRE_COLLECTION_TRANSACTION_STATUSES],
            [10, 15, 30],
        )

    def test_group_leave_blockers_are_a_subset_of_the_in_hand_statuses(self) -> None:
        self.assertEqual(
            [status.value for status in GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES],
            [50, 60],
        )
        self.assertLessEqual(
            set(GROUP_LEAVE_BLOCKING_TRANSACTION_STATUSES),
            set(DUAL_CONFIRMATION_TRANSACTION_STATUSES),
        )


class ItemStatusProjectionTests(SimpleTestCase):
    def test_every_transaction_status_maps_to_an_item_status(self) -> None:
        """Missing mappings would raise KeyError during lifecycle actions."""
        self.assertEqual(set(ITEM_STATUS_FOR_TRANSACTION), set(TransactionStatus))

    def test_a_finished_transaction_frees_the_item(self) -> None:
        for status in TERMINAL_TRANSACTION_STATUSES:
            with self.subTest(status.name):
                self.assertEqual(
                    ITEM_STATUS_FOR_TRANSACTION[status], ItemStatus.AVAILABLE
                )
