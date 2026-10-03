from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

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
        "Repair item statuses to match their open transactions. Items without "
        "an open transaction become AVAILABLE. Skip soft-deleted items and "
        "items with multiple open transactions. Repairs recheck each item under "
        "a row lock, so the command can run while the app is serving."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report incorrect item statuses without changing them",
        )

    def _repair(self, item_pk: int) -> bool:
        """Fix one item on current state. False if it no longer needs fixing."""
        with transaction.atomic():
            item = Item.lock_for_update(item_pk)
            open_statuses = list(
                Transaction.objects.filter(
                    item=item, status__in=OPEN_TRANSACTION_STATUSES
                ).values_list("status", flat=True)
            )
            if item.deleted_at is not None or len(open_statuses) > 1:
                return False
            expected = (
                ITEM_STATUS_FOR_TRANSACTION[TransactionStatus(open_statuses[0])]
                if open_statuses
                else ItemStatus.AVAILABLE
            )
            if item.status == expected:
                return False
            item.status = expected
            item.save(update_fields=("status", "updated_at"))
            return True

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]

        # Fetch open transactions once to find candidates.
        # Each repair rechecks the item under its row lock.
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
                # Multiple open transactions make the expected status ambiguous.
                # Skip the item until those transactions are resolved.
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

            if self._repair(item.pk):
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
