"""Verify the database audit of legacy and table actions."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from borrowd_items import flow_parity
from borrowd_items.flow import available_actions
from borrowd_items.models import Item, ItemAction, Transaction, TransactionStatus
from borrowd_users.models import BorrowdUser

COMMAND_MODULE = "borrowd_items.management.commands.audit_item_flow"


class AuditItemFlowTests(TestCase):
    owner: BorrowdUser
    borrower: BorrowdUser
    other: BorrowdUser

    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner, cls.borrower, cls.other = (
            BorrowdUser.objects.create_user(username=name)
            for name in ("audit_owner", "audit_borrower", "audit_other")
        )

    def make_transaction(
        self, status: TransactionStatus = TransactionStatus.REQUESTED
    ) -> Transaction:
        item = Item.objects.create(
            name="Drill",
            description="A drill",
            owner=self.owner,
            created_by=self.owner,
            updated_by=self.owner,
        )
        return Transaction.objects.create(
            item=item,
            party1=self.owner,
            party2=self.borrower,
            status=status,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def run_audit(self, *args: str, fails: bool = False) -> str:
        out = StringIO()
        if fails:
            with self.assertRaises(CommandError):
                call_command("audit_item_flow", *args, stdout=out)
        else:
            call_command("audit_item_flow", *args, stdout=out)
        return out.getvalue()

    def test_empty_database(self) -> None:
        out = self.run_audit()
        self.assertIn("Transactions checked: 0", out)
        self.assertIn("Actor comparisons: 0", out)
        self.assertIn("Mismatched comparisons: 0", out)
        self.assertIn("Comparisons with errors: 0", out)

    def test_checks_both_parties_and_excludes_closed_transactions(self) -> None:
        self.make_transaction()
        self.make_transaction(TransactionStatus.RETURNED)
        out = self.run_audit("--details")
        self.assertIn("Transactions checked: 1", out)
        self.assertIn("Actor comparisons: 2", out)
        self.assertIn("Mismatched comparisons: 0", out)
        self.assertNotIn("Mismatch:", out)

    @override_settings(ITEMS_FLOW_PARITY_CHECK=False)
    def test_reports_real_lender_owner_mismatch_even_with_runtime_check_disabled(
        self,
    ) -> None:
        tx = self.make_transaction()
        Item.all_objects.filter(pk=tx.item_id).update(owner=self.other)
        summary = self.run_audit(fails=True)
        self.assertIn("Transactions with mismatches: 1", summary)
        self.assertIn("Mismatched comparisons: 1", summary)
        self.assertNotIn("legacy=", summary)

        out = self.run_audit("--details", fails=True)
        self.assertIn(f"item={tx.item_id} transaction={tx.pk}", out)
        self.assertIn(f"status=REQUESTED role=lender actor={self.owner.pk}", out)
        self.assertIn("legacy=[CANCEL_REQUEST]", out)
        self.assertIn("table=[REJECT_REQUEST, ACCEPT_REQUEST]", out)

    def test_counts_transactions_separately_from_actor_mismatches(self) -> None:
        self.make_transaction()
        self.make_transaction()
        with mock.patch(f"{COMMAND_MODULE}.available_actions", return_value=()):
            out = self.run_audit("--details", fails=True)
        self.assertIn("Transactions with mismatches: 2", out)
        self.assertIn("Mismatched comparisons: 4", out)
        self.assertEqual(out.count("Mismatch:"), 4)
        self.assertIn("table=[]", out)

    def test_action_order_is_part_of_the_comparison(self) -> None:
        self.make_transaction()
        with mock.patch(
            f"{COMMAND_MODULE}.available_actions",
            side_effect=[
                (ItemAction.ACCEPT_REQUEST, ItemAction.REJECT_REQUEST),
                (ItemAction.CANCEL_REQUEST,),
            ],
        ):
            out = self.run_audit(fails=True)
        self.assertIn("Mismatched comparisons: 1", out)

    def test_evaluation_errors_do_not_stop_the_scan_or_count_as_mismatches(
        self,
    ) -> None:
        self.make_transaction()
        self.make_transaction()
        for implementation in ("legacy_actions_for", "available_actions"):
            with self.subTest(implementation=implementation):
                with mock.patch(
                    f"{COMMAND_MODULE}.{implementation}",
                    side_effect=ValueError("bad rule"),
                ) as evaluate:
                    out = self.run_audit("--details", fails=True)
                self.assertEqual(evaluate.call_count, 4)
                self.assertIn("Actor comparisons: 4", out)
                self.assertIn("Transactions with mismatches: 0", out)
                self.assertIn("Mismatched comparisons: 0", out)
                self.assertIn("Comparisons with errors: 4", out)
                self.assertEqual(out.count("Evaluation error:"), 4)
                self.assertIn("ERROR(ValueError: 'bad rule')", out)

    def test_both_rules_use_one_time_at_the_dispute_deadline(self) -> None:
        now = timezone.now()
        tx = self.make_transaction(TransactionStatus.RETURN_REQUESTED)
        tx.return_requested_at = now - timedelta(days=settings.RETURN_DISPUTE_WAIT_DAYS)
        tx.save(update_fields=["return_requested_at"])
        with (
            mock.patch(f"{COMMAND_MODULE}.timezone.now", return_value=now),
            mock.patch(
                f"{COMMAND_MODULE}.legacy_actions_for",
                wraps=flow_parity.legacy_actions_for,
            ) as legacy,
            mock.patch(
                f"{COMMAND_MODULE}.available_actions", wraps=available_actions
            ) as table,
        ):
            out = self.run_audit()
        self.assertIn("Mismatched comparisons: 0", out)
        for call in legacy.call_args_list + table.call_args_list:
            self.assertIs(call.kwargs["now"], now)

    def test_includes_deleted_items_and_inactive_parties(self) -> None:
        tx = self.make_transaction(TransactionStatus.COLLECTED)
        Item.all_objects.filter(pk=tx.item_id).update(deleted_at=timezone.now())
        BorrowdUser.objects.filter(pk=self.owner.pk).update(is_active=False)
        with mock.patch(
            f"{COMMAND_MODULE}.available_actions", wraps=available_actions
        ) as table:
            out = self.run_audit()
        self.assertEqual(table.call_count, 2)
        self.assertIn("Transactions checked: 1", out)
        self.assertIn("Mismatched comparisons: 0", out)

    def test_reads_in_one_query_without_runtime_reporting(self) -> None:
        tx = self.make_transaction()
        Item.all_objects.filter(pk=tx.item_id).update(owner=self.other)
        self.make_transaction(TransactionStatus.COLLECTED)
        counts = flow_parity.comparison_counts()
        with (
            CaptureQueriesContext(connection) as queries,
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_message"
            ) as report,
            mock.patch(
                "borrowd_items.flow_parity.sentry_sdk.capture_exception"
            ) as error,
        ):
            self.run_audit("--details", fails=True)
        self.assertEqual(len(queries), 1)
        sql = queries[0]["sql"].lstrip().upper()
        self.assertTrue(
            sql.startswith("SELECT") or (sql.startswith("DECLARE") and "SELECT" in sql)
        )
        self.assertEqual(flow_parity.comparison_counts(), counts)
        report.assert_not_called()
        error.assert_not_called()
