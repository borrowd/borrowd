from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from borrowd_items.models import (
    OPEN_TRANSACTION_STATUSES,
    PRE_COLLECTION_TRANSACTION_STATUSES,
    Transaction,
    TransactionStatus,
)


class Command(BaseCommand):
    help = (
        "Check open transactions for lender/owner mismatches and requests on "
        "soft-deleted items before collection. Read-only; prints findings and "
        "exits nonzero if any are found."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        open_transactions = Transaction.objects.filter(
            status__in=OPEN_TRANSACTION_STATUSES
        )
        findings = 0

        mismatched = (
            open_transactions.exclude(party1_id=F("item__owner_id"))
            .order_by("status", "pk")
            .values(
                "pk",
                "status",
                "item_id",
                "party1_id",
                "party2_id",
                owner_id=F("item__owner_id"),
                item_deleted_at=F("item__deleted_at"),
            )
        )
        for row in mismatched:
            findings += 1
            self.stdout.write(
                f"Lender is not owner: transaction={row['pk']} "
                f"status={TransactionStatus(row['status']).name} "
                f"item={row['item_id']} lender={row['party1_id']} "
                f"owner={row['owner_id']} borrower={row['party2_id']} "
                f"item_deleted={row['item_deleted_at'] is not None}"
            )

        # Account closure can delete an item during an ongoing loan.
        # Flag only transactions where collection has not been asserted.
        stranded = (
            open_transactions.filter(
                status__in=PRE_COLLECTION_TRANSACTION_STATUSES,
                item__deleted_at__isnull=False,
            )
            .order_by("pk")
            .values("pk", "status", "item_id", "party1_id", "party2_id")
        )
        for stuck in stranded:
            findings += 1
            self.stdout.write(
                f"Stuck on a deleted item: transaction={stuck['pk']} "
                f"status={TransactionStatus(stuck['status']).name} "
                f"item={stuck['item_id']} lender={stuck['party1_id']} "
                f"borrower={stuck['party2_id']}"
            )

        if findings:
            raise CommandError(f"{findings} finding(s).")
        self.stdout.write(self.style.SUCCESS("No findings."))
