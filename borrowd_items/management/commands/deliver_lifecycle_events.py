from typing import Any

from django.core.management.base import BaseCommand

from borrowd_items.events import deliver_due, delivery_status


class Command(BaseCommand):
    help = (
        "Delivers lifecycle events that are due: any a crash left undelivered "
        "and retries after a consumer error. Cron runs this every five minutes. "
        "Safe to run alongside the app and alongside itself."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        delivered = deliver_due()
        status = delivery_status()
        self.stdout.write(
            f"Delivered {delivered} event(s). {status.waiting} waiting, "
            f"{status.parked} parked."
        )
