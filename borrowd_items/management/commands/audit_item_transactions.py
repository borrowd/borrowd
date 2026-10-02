from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F

from borrowd_items.models import (
    OPEN_TRANSACTION_STATUSES,
    PRE_COLLECTION_TRANSACTION_STATUSES,
    Transaction,
    TransactionStatus,
)


class Command(BaseCommand):
    help = (
        "Read-only. Reports open transactions that break a lifecycle invariant: "
        "the recorded lender is not the item's owner, an item has more than one "
        "open transaction, or a request is stuck on a soft-deleted item. Prints "
        "IDs only and exits non-zero if it finds anything."
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

        crowded_items = list(
            open_transactions.values("item_id")
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .values_list("item_id", flat=True)
        )
        by_item: dict[int, list[str]] = {}
        for item_id, pk, status in (
            open_transactions.filter(item_id__in=crowded_items)
            .order_by("item_id", "pk")
            .values_list("item_id", "pk", "status")
        ):
            by_item.setdefault(item_id, []).append(
                f"{pk} ({TransactionStatus(status).name})"
            )
        for item_id, transactions in by_item.items():
            findings += 1
            self.stdout.write(
                f"More than one open transaction: item={item_id} "
                f"transactions={', '.join(transactions)}"
            )

        # An in-hand transaction on a deleted item is expected: its owner left
        # and the borrower can resolve it. A request there has no way forward.
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
