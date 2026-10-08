from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from borrowd_items.flow import available_actions
from borrowd_items.flow_parity import legacy_actions_for
from borrowd_items.models import Transaction
from borrowd_items.statuses import (
    OPEN_TRANSACTION_STATUSES,
    ItemAction,
    TransactionStatus,
)


class Command(BaseCommand):
    help = (
        "Compare legacy and table actions for both parties on every open transaction "
        "in the configured database. Read-only; exits nonzero for mismatches or "
        "evaluation errors. Use --details to show each finding."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--details",
            action="store_true",
            help="Show item and transaction IDs, status, actor role, and both answers.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        transactions_checked = 0
        comparisons = 0
        mismatched_transactions = 0
        mismatched_comparisons = 0
        comparisons_with_errors = 0

        transactions = (
            Transaction.objects.filter(status__in=OPEN_TRANSACTION_STATUSES)
            .select_related("item", "party1", "party2")
            .order_by("pk")
        )
        self.stdout.write(f"Comparison time: {now.isoformat()}")
        for tx in transactions.iterator(chunk_size=500):
            transactions_checked += 1
            has_mismatch = False
            for role, actor in (("lender", tx.party1), ("borrower", tx.party2)):
                comparisons += 1
                legacy, legacy_text = _evaluate(
                    lambda: legacy_actions_for(tx.item, tx, actor, now=now)
                )
                table, table_text = _evaluate(
                    lambda: available_actions(tx, actor, now=now)
                )
                if legacy is None or table is None:
                    comparisons_with_errors += 1
                    finding = "Evaluation error"
                elif legacy != table:
                    has_mismatch = True
                    mismatched_comparisons += 1
                    finding = "Mismatch"
                else:
                    continue

                if options["details"]:
                    self.stdout.write(
                        f"{finding}: item={tx.item_id} transaction={tx.pk} "
                        f"status={TransactionStatus(tx.status).name} "
                        f"role={role} actor={actor.pk} "
                        f"legacy={legacy_text} table={table_text}"
                    )
            if has_mismatch:
                mismatched_transactions += 1

        self.stdout.write(
            f"Transactions checked: {transactions_checked}\n"
            f"Actor comparisons: {comparisons}\n"
            f"Transactions with mismatches: {mismatched_transactions}\n"
            f"Mismatched comparisons: {mismatched_comparisons}\n"
            f"Comparisons with errors: {comparisons_with_errors}"
        )
        if mismatched_comparisons or comparisons_with_errors:
            raise CommandError(
                "Action comparison found mismatches or evaluation errors."
                + ("" if options["details"] else " Run with --details to inspect them.")
            )


def _evaluate(
    evaluate: Callable[[], tuple[ItemAction, ...]],
) -> tuple[tuple[ItemAction, ...] | None, str]:
    try:
        actions = evaluate()
    except Exception as exc:
        # Keep scanning so one failed evaluation does not hide other findings.
        return None, f"ERROR({type(exc).__name__}: {str(exc)!r})"
    return actions, "[" + ", ".join(action.value for action in actions) + "]"
