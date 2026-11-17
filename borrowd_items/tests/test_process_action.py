"""Verify that Item.process_action uses the transition executor."""

from unittest import mock

from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.models import Item, ItemAction, TransactionStatus
from borrowd_items.tests.test_flow_execution import ExecutionTestCase


class ProcessActionGoesThroughTheExecutorTests(ExecutionTestCase):
    def test_passing_the_listed_actions_check_is_not_enough(self) -> None:
        """The executor rejects an ineligible action even when get_actions_for lists it."""
        item, tx = self.open_transaction(TransactionStatus.REQUESTED)
        with mock.patch.object(
            Item, "get_actions_for", return_value=(ItemAction.ACCEPT_REQUEST,)
        ):
            with self.assertRaises(InvalidItemAction):
                item.process_action(self.borrower, ItemAction.ACCEPT_REQUEST)
        self.assert_untouched(tx, TransactionStatus.REQUESTED)
