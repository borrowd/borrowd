from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from borrowd_items.events import delivery_status, replay, skip
from borrowd_items.models import LifecycleEvent
from borrowd_users.models import BorrowdUser


class Command(BaseCommand):
    help = (
        "Check on lifecycle event delivery and unstick it. `status` shows what's "
        "waiting or parked, `replay` retries events now, and `skip` marks an "
        "event handled without running its consumers, recording who and why."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        operations = parser.add_subparsers(dest="operation", required=True)
        operations.add_parser("status", help="Counts, and every parked event.")
        replaying = operations.add_parser("replay", help="Retry events now.")
        replaying.add_argument("event_ids", nargs="+", type=UUID)
        skipping = operations.add_parser("skip", help="Give up on one event.")
        skipping.add_argument("event_id", type=UUID)
        skipping.add_argument("--reason", required=True)
        skipping.add_argument(
            "--by", required=True, help="Username of whoever decided to skip it."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        operation = options["operation"]
        if operation == "status":
            self._status()
        elif operation == "replay":
            for event in self._events(options["event_ids"]):
                replay(event)
                self.stdout.write(f"Replayed {event.pk}.")
        else:
            (event,) = self._events([options["event_id"]])
            user = BorrowdUser.objects.filter(username=options["by"]).first()
            if user is None:
                raise CommandError(f"No user named {options['by']!r}.")
            skip(event, by=user, reason=options["reason"])
            self.stdout.write(f"Skipped {event.pk}.")

    def _status(self) -> None:
        status = delivery_status()
        oldest = status.oldest_waiting.isoformat() if status.oldest_waiting else "-"
        self.stdout.write(
            f"{status.waiting} waiting (oldest {oldest}), {status.parked} parked."
        )
        parked = LifecycleEvent.objects.filter(
            processed_at__isnull=True, failed_at__isnull=False
        ).order_by("failed_at")
        for event in parked:
            error = event.last_error.splitlines()[0] if event.last_error else ""
            self.stdout.write(f"Parked {event.pk} ({event}): {error}")

    def _events(self, event_ids: list[UUID]) -> list[LifecycleEvent]:
        events = list(LifecycleEvent.objects.filter(pk__in=event_ids))
        missing = set(event_ids) - {event.pk for event in events}
        if missing:
            raise CommandError(
                f"No such event(s): {', '.join(str(pk) for pk in missing)}"
            )
        return events
