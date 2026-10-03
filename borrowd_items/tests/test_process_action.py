"""`Item.process_action` hands transaction-bound actions to the executor."""

from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from borrowd_items.exceptions import InvalidItemAction
from borrowd_items.models import Item, ItemAction, TransactionStatus
from borrowd_items.tests.test_flow_execution import ExecutionTestCase


class ProcessActionGoesThroughTheExecutorTests(ExecutionTestCase):
    def test_passing_the_listed_actions_check_is_not_enough(self) -> None:
        """The executor decides for itself; the earlier check is not trusted."""
        item, tx = self.open_transaction(TransactionStatus.REQUESTED)
        with mock.patch.object(
            Item, "get_actions_for", return_value=(ItemAction.ACCEPT_REQUEST,)
        ):
            with self.assertRaises(InvalidItemAction):
                item.process_action(self.borrower, ItemAction.ACCEPT_REQUEST)
        self.assert_untouched(tx, TransactionStatus.REQUESTED)

    def test_a_request_reads_the_items_transactions_once(self) -> None:
        item = Item.objects.create(
            name="Ladder",
            description="A ladder",
            owner=self.lender,
            created_by=self.lender,
            updated_by=self.lender,
        )
        with CaptureQueriesContext(connection) as queries:
            item.process_action(self.borrower, ItemAction.REQUEST_ITEM)

        statements = [query["sql"] for query in queries.captured_queries]
        insert_at = next(
            index
            for index, sql in enumerate(statements)
            if sql.startswith('INSERT INTO "borrowd_items_transaction"')
        )
        reads = [
            sql
            for sql in statements[:insert_at]
            if sql.startswith("SELECT") and 'FROM "borrowd_items_transaction"' in sql
        ]
        self.assertEqual(len(reads), 1, reads)
