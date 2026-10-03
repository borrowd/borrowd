from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from borrowd_items.models import ItemCommandRecord


class Command(BaseCommand):
    help = (
        "Deletes lifecycle command records older than --days. A retry older "
        "than that is refused as stale instead of being answered from its "
        "record, so this only limits how long a lost response can be "
        "recovered, never whether a command can run twice."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Keep records this many days old or newer (default 30).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = ItemCommandRecord.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f"Pruned {deleted} command record(s) older than {days} days.")
