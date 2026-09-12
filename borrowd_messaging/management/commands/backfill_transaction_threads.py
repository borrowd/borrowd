from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction as db_transaction

from borrowd_items.models import (
    TERMINAL_TRANSACTION_STATUSES,
    Transaction,
    TransactionStatus,
)
from borrowd_messaging.models import ChatThread
from borrowd_messaging.services import MessagingService
from borrowd_users.models import BorrowdUser
from borrowd_users.system import get_system_user


class Command(BaseCommand):
    help = (
        "Give every open Transaction that has no conversation its thread. "
        "Works with MESSAGING_ENABLED off, and is idempotent. "
        "Transactions created while the flag is off don't get a thread, "
        "so run it again right after turning the flag on."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many open transactions need a thread without creating any.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Removing an Item archives its conversations, so don't open a new one.
        missing_ids = list(
            Transaction.objects.filter(
                chat_thread__isnull=True, item__deleted_at__isnull=True
            )
            .exclude(status__in=TERMINAL_TRANSACTION_STATUSES)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing_ids)} open transaction(s) have no conversation"
                    " (dry run)."
                )
            )
            return

        system_user = get_system_user()
        linked_count = 0
        failed_count = 0
        for transaction_id in missing_ids:
            try:
                linked = self._backfill(transaction_id, system_user)
            except Exception as e:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(f"Failed on transaction {transaction_id}: {e}")
                )
                continue
            if linked:
                linked_count += 1

        skipped_count = len(missing_ids) - linked_count - failed_count
        summary = f"Linked {linked_count} of {len(missing_ids)} open transaction(s) to a conversation"
        if skipped_count:
            summary += f", {skipped_count} skipped (changed since the scan)"
        if failed_count:
            summary += f", {failed_count} failed"
        summary += "."
        if failed_count:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

    def _backfill(self, transaction_id: int, actor: BorrowdUser) -> bool:
        """Lock the Transaction and its Item, then add a thread if still needed."""
        with db_transaction.atomic():
            # Locking the Item too makes a concurrent removal wait for this
            # commit, so its archive pass sees the new thread.
            transaction = (
                Transaction.objects.select_for_update(of=("self", "item"))
                .select_related("item")
                .filter(pk=transaction_id)
                .first()
            )
            if (
                transaction is None
                or transaction.status in TERMINAL_TRANSACTION_STATUSES
                or transaction.item.deleted_at is not None
                or ChatThread.objects.filter(transaction=transaction).exists()
            ):
                return False

            thread = MessagingService.attach_thread_to(transaction, actor=actor)
            if transaction.status == TransactionStatus.DISPUTED:
                MessagingService.post_dispute_notice(thread)
            return True
