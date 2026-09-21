from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from borrowd_items.models import (
    ITEM_STATUS_FOR_TRANSACTION,
    OPEN_TRANSACTION_STATUSES,
    Item,
    ItemStatus,
    Transaction,
    TransactionStatus,
)


class Command(BaseCommand):
    help = (
        "Re-derives Item.status from each item's open transaction and reports "
        "or repairs any that disagree. Item.status is a stored summary of the "
        "transaction lifecycle rather than state of its own, so drift is "
        "always repairable: the transaction is the record, the item status is "
        "the copy. An item with no open transaction is AVAILABLE. Soft-deleted "
        "items are skipped, matching sync_item_status. Safe to re-run; "
        "already-correct rows are a no-op."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report items whose status has drifted without changing them.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]

        # One pass over the open transactions, so the scan below is a single
        # consistent snapshot rather than a query per item.
        open_statuses_by_item: dict[int, list[TransactionStatus]] = {}
        for item_id, status in Transaction.objects.filter(
            status__in=OPEN_TRANSACTION_STATUSES
        ).values_list("item_id", "status"):
            open_statuses_by_item.setdefault(item_id, []).append(
                TransactionStatus(status)
            )

        scanned_count = 0
        drifted_count = 0
        repaired_count = 0
        conflicted_count = 0

        for item in Item.objects.order_by("pk").iterator():
            scanned_count += 1
            open_statuses = open_statuses_by_item.get(item.pk, [])

            if len(open_statuses) > 1:
                # More than one open transaction means the item's real state is
                # ambiguous, so there is nothing to derive. Resolve the
                # transactions with their parties rather than picking a winner.
                conflicted_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Ambiguous: item={item.pk} '{item}' has "
                        f"{len(open_statuses)} open transactions "
                        f"({', '.join(s.name for s in open_statuses)}); skipped."
                    )
                )
                continue

            expected = (
                ITEM_STATUS_FOR_TRANSACTION[open_statuses[0]]
                if open_statuses
                else ItemStatus.AVAILABLE
            )
            if item.status == expected:
                continue

            drifted_count += 1
            current = ItemStatus(item.status)
            self.stdout.write(
                f"Drifted: item={item.pk} '{item}' is {current.name}, "
                f"should be {expected.name}"
            )
            if dry_run:
                continue

            item.status = expected
            item.save(update_fields=("status", "updated_at"))
            repaired_count += 1

        summary = f"{drifted_count} of {scanned_count} item(s) had a drifted status"
        if dry_run:
            self.stdout.write(self.style.WARNING(f"{summary} (dry run)."))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"{summary}; {repaired_count} repaired.")
            )
        if conflicted_count:
            self.stderr.write(
                self.style.ERROR(f"{conflicted_count} item(s) skipped as ambiguous.")
            )
